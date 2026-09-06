from typing import Any, Dict, List, Optional

import json
import time
from uuid import uuid4
from datetime import datetime
from pathlib import Path

from ..domain.schemas import AnalysisInput, MonitorInput, TaskEvent, FeedbackRoundInput, ReplanRequest
from ..domain.store import analysis_store
from ..agents import APPROVER, COMMANDER, RECON, SIMULATOR, SUPPORT, SUPPRESSION
from ..agents.blackboard import post_message
from ..pipeline import run_demo_analysis, simulate_monitor
from ..skills.orchestrator import SkillExecutionError, SkillOrchestrator
from ..tools.core import analyze_with_vlm, resolve_wind_band

ROOT = Path(__file__).resolve().parents[3]
REPORTS_DIR = ROOT / "data" / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def _rising_streak(rounds, current_flp) -> int:
    """尾部连续「带压制仍净上涨」的轮数（含本轮），供研判识别趋势而非单轮噪声。"""
    streak = 0
    prev = current_flp
    for round_item in reversed(rounds or []):
        after = round_item.after.fire_load_flp if round_item.after else None
        before = round_item.before.fire_load_flp if round_item.before else None
        if after is None or before is None:
            break
        if prev is not None and prev > before + 1e-9:
            streak += 1
            prev = before
        else:
            break
    return streak


def _normalize_scenario(raw: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """演训模拟场景（FE-18）钳位校验：非法类型 → 422，数值越界 → 钳到演示合理区间。"""
    if not raw:
        return None
    if not isinstance(raw, dict):
        raise ValueError("scenario 必须是对象")
    origin = raw.get("fire_origin") or {}
    try:
        x = float(origin.get("x"))
        y = float(origin.get("y"))
        area = float(raw.get("fire_area_m2"))
        growth = float(raw.get("growth_rate", 0.42))
    except (TypeError, ValueError) as exc:
        raise ValueError("scenario.fire_origin/fire_area_m2/growth_rate 数值非法") from exc
    failure_round = raw.get("uav_failure_round")
    normalized = {
        "fire_origin": {"x": min(max(x, -500.0), 700.0), "y": min(max(y, -1000.0), 800.0)},
        "fire_area_m2": min(max(area, 200.0), 12000.0),
        "growth_rate": min(max(growth, 0.05), 1.5),
    }
    if failure_round is not None:
        try:
            normalized["uav_failure_round"] = min(max(int(failure_round), 1), 20)
        except (TypeError, ValueError):
            pass
    shift = raw.get("wind_shift")
    if isinstance(shift, dict):
        try:
            normalized["wind_shift"] = {
                "round": min(max(int(shift.get("round")), 1), 20),
                "speed": min(max(float(shift.get("speed")), 0.5), 15.0),
            }
        except (TypeError, ValueError):
            pass
    return normalized


class AnalysisService:

    """统一分析应用服务：所有入口共享同一份任务、规则和 Agent 链结果。"""

    def __init__(self, orchestrator: Optional[SkillOrchestrator] = None):
        self.orchestrator = orchestrator or SkillOrchestrator()

    def create_and_run(self, request: AnalysisInput, frame_paths: Optional[List[str]] = None) -> Dict[str, Any]:
        item = analysis_store.create(request.model_dump())
        analysis_store.update(item.analysis_id, status="running")
        analysis_store.add_event(
            item.analysis_id,
            "ingest",
            "影像输入已接收",
            "upload" if request.image_path else "api",
        )
        try:
            scenario = _normalize_scenario(request.scenario)
            # 多帧序列：frames 为早前帧，主文件自动作为最新一帧（api-contract §5.2）；同一序列供 VLM 时间对比（手册 §4.1）
            sequence_paths = ([*frame_paths, request.image_path] if request.image_path else list(frame_paths)) if frame_paths else []
            context = {
                "scene_id": request.scene_id,
                "scenario": scenario,
                "image_name": request.image_name or "default",
                "image_path": request.image_path,
                "image_paths": sequence_paths,
                "task_id": item.analysis_id,
                "round_index": 1,
                "latitude": request.latitude,
                "longitude": request.longitude,
                "environment_mode": request.environment_mode,
                "water_search_radius_m": request.water_search_radius_m,
                "road_search_radius_m": request.road_search_radius_m,
                "metadata": request.metadata,
                "use_vlm": request.use_vlm,
                "fire_type": request.fire_type,
                "people_status": request.people_status.value,
                "constraints": request.constraints,
                "strict_real": request.environment_mode == "real",
                "fire_center": ({"latitude": request.latitude, "longitude": request.longitude} if request.latitude is not None and request.longitude is not None else None),
            }
            people_label = {"confirmed": "在场", "absent": "不在场", "unknown": "情况不明"}.get(request.people_status.value, "情况不明")
            image_label = request.image_name or request.image_path or ("随机演训火情" if request.scenario else "未命名输入")
            try:
                COMMANDER.intake(item.analysis_id, image_label, people_label)
            except Exception:
                pass
            agent = self.orchestrator.run_analysis(context)
            # 观测数据显式驱动规则管线：小火上传按小火计算，而不是固定默认火情。
            chain = agent.get("skill_chain", {})
            observation = chain.get("fire_perception", {}).get("observation", {})
            # 演训模拟场景（FE-18）优先于影像观测：scenario 直接驱动火情数值
            if scenario:
                fire_override = {
                    "fire_area_m2": scenario["fire_area_m2"],
                    "smoke_area_m2": round(scenario["fire_area_m2"] * 2.33, 1),
                    "growth_rate": scenario["growth_rate"],
                }
            else:
                fire_override = {key: observation[key] for key in ("fire_area_m2", "smoke_area_m2", "growth_rate") if observation.get(key) is not None}
            # 多帧序列（api-contract §5.2）：frames 为早前帧，主文件自动作为最新一帧，趋势显式驱动火情重算。
            visual_sequence = None
            if sequence_paths:
                from ..tools.core import analyze_frame_sequence
                visual_sequence = analyze_frame_sequence(sequence_paths)
                frames = visual_sequence.get("frames") or []
                if frames:
                    last_frame = frames[-1]
                    for key in ("fire_area_m2", "smoke_area_m2"):
                        if last_frame.get(key) is not None:
                            fire_override[key] = last_frame[key]
                trend = visual_sequence.get("trend") or {}
                if trend.get("status") == "ok" and trend.get("growth_rate") is not None:
                    fire_override["growth_rate"] = trend["growth_rate"]
            result = run_demo_analysis(
                request.scene_id,
                request.image_name or request.image_path,
                fire_override=fire_override or None,
                fire_type=request.fire_type,
                people_status=request.people_status.value,
                constraints=request.constraints,
                dispatch_override=chain.get("candidate_generation", {}).get("v1_dispatch"),
                scenario=scenario,
            )
            self._merge_agent_result(result, agent)
            # ---- Agent 协作层（AG-1）：角色消息 + LLM advisory，任何失败不阻塞主管线 ----
            try:
                fire = result.get("fire_assessment", {})
                dispatch = result.get("dispatch_plan", {})
                people_label = {"confirmed": "在场", "absent": "不在场", "unknown": "情况不明"}.get(request.people_status.value, "情况不明")
                RECON.search_beat(item.analysis_id, (result.get("scene") or {}).get("fire_origin"), fire.get("level"))
                RECON.finding(item.analysis_id, fire, people_label)
                max_drones = int((request.constraints or {}).get("max_drones", 4) or 4)
                strategy, strategy_source = SUPPRESSION.size_strategy(fire, min(max_drones, 4))
                SUPPRESSION.plan(item.analysis_id, dispatch, fire, strategy, strategy_source, max_drones)
                SUPPORT.branch(item.analysis_id, request.people_status.value == "confirmed")
                APPROVER.prepare(item.analysis_id, result)
            except Exception:
                pass
            # 轮次触发的自动重规划不带 constraints，回读 result["constraints"] 继承用户约束。
            result["constraints"] = request.constraints
            if visual_sequence and visual_sequence.get("frame_count", 0) >= 2:
                result["visual_sequence"] = visual_sequence
            analysis_store.update_resources(item.analysis_id, result.get("fleet"), result.get("inventory"))
            analysis_store.update(
                item.analysis_id,
                status="awaiting_confirmation",
                result=result,
                stages=result.get("pipeline_stages", []),
                plan_versions=[{"schema_version": "uav-dispatch-v1", "plan_id": "plan-" + uuid4().hex[:10], "task_id": item.analysis_id, "plan_version": 1, "generated_at": datetime.now().isoformat(timespec="seconds"), **result.get("dispatch_plan", {})}],
            )
            analysis_store.add_event(item.analysis_id, "dispatch", "分析链完成并生成调度方案", "rules")
            self._persist_dispatch_report(item.analysis_id)
        except Exception as error:
            try:
                analysis_store.update(item.analysis_id, status="failed", error={"error_code": "analysis_failed", "message": str(error), "stage": "agent_chain"})
            finally:
                raise
        return analysis_store.dump(item.analysis_id)

    def get_plan(self, analysis_id: str) -> Dict[str, Any]:
        item = analysis_store.get(analysis_id)
        if not item or not item.plan_versions:
            raise KeyError(analysis_id)
        return {
            "schema_version": "uav-dispatch-v1",
            "task_id": analysis_id,
            "plan": item.plan_versions[-1],
            "versions": item.plan_versions,
        }

    def monitor_and_update(self, analysis_id: str, request: MonitorInput) -> Dict[str, Any]:
        def calculate(item):
            if item.status not in {"executing"}:
                raise ValueError("任务尚未批准执行，禁止监测")
            if not item.result:
                raise ValueError("分析任务尚未完成，不能监测")
            # The task-owned snapshots are authoritative.  Client snapshots are
            # accepted for backwards compatibility but must not fork task state.
            fleet_snapshot = analysis_store.fleet(analysis_id)
            inventory_snapshot = analysis_store.inventory(analysis_id)
            monitor_result = simulate_monitor(
                item.result,
                request.elapsed_minutes,
                request.extinguishing_liters,
                fleet_snapshot=fleet_snapshot,
                inventory=inventory_snapshot,
                image_name=request.image_name,
            )
            updated = dict(item.result)
            updated["fire_assessment"] = dict(updated["fire_assessment"])
            updated["fire_assessment"]["fire_area_m2"] = monitor_result["next_fire_area_m2"]
            updated["fleet"] = monitor_result["next_fleet"]
            updated["inventory"] = monitor_result["next_inventory"]
            analysis_store.update_resources(analysis_id, monitor_result["next_fleet"], monitor_result["next_inventory"])
            updated["dispatch_plan"] = {
                **updated.get("dispatch_plan", {}),
                "selected_uavs": updated.get("dispatch_plan", {}).get("selected_uavs", []),
                "fire_load_flp": monitor_result.get("next_fire_load_flp", updated.get("dispatch_plan", {}).get("fire_load_flp")),
                "battery_plan": monitor_result.get("battery_plan", updated.get("dispatch_plan", {}).get("battery_plan", [])),
                "resource_gap": monitor_result.get("resource_gap", updated.get("dispatch_plan", {}).get("resource_gap", [])),
            }
            return {
                "status": "completed" if monitor_result["action"] == "finish" else "executing",
                "result": updated | {"monitor": monitor_result},
                "events": [TaskEvent(stage="monitor", message="闭环监测完成：" + monitor_result["action"], source="rules"), *item.events],
            }

        updated = analysis_store.monitor_update(analysis_id, calculate)
        if updated.status == "completed":
            # 归档即释放：终态任务不得遗留资源锁（与 terminate/reject 同口径，自查发现 completed 曾带锁）。
            analysis_store.release_resources(analysis_id)
        self._persist_dispatch_report(analysis_id)
        return {**updated.model_dump(), "action": updated.result["monitor"]["action"]}

    def approve(self, analysis_id: str, request) -> Dict[str, Any]:
        approved = analysis_store.approval(analysis_id, request.action, request.plan_id, request.constraints, request.reason, request.idempotency_key)
        # Adjust is a transactional replacement: release the old lock and create
        # a new version which must be approved separately.
        if request.action == "adjust":
            result = self.replan(analysis_id, ReplanRequest(constraints=request.constraints, triggers=["manual_adjust"]))
            try:
                COMMANDER.arbitration(analysis_id, request.action, request.reason or "")
            except Exception:
                pass
            self._persist_dispatch_report(analysis_id)
            return result
        try:
            COMMANDER.arbitration(analysis_id, request.action, request.reason or "")
        except Exception:
            pass
        self._persist_dispatch_report(analysis_id)
        return approved.model_dump()

    def replan(self, analysis_id: str, request: ReplanRequest) -> Dict[str, Any]:
        item = analysis_store.get(analysis_id)
        if not item: raise KeyError(analysis_id)
        if item.status in {"completed", "terminated", "failed"}: raise ValueError("终态任务禁止重规划")
        # Replanning invalidates the old reservation before generating a new plan.
        analysis_store.release_resources(analysis_id)
        analysis_store.update(analysis_id, status="replanning")
        from ..pipeline import deterministic_v1_dispatch, load_demo_state, normalize_fleet, normalize_inventory
        state = load_demo_state(item.input.scene_id)
        result = dict(item.result or {})
        state["fleet"] = normalize_fleet(result.get("fleet", state["fleet"]))
        state["inventory"] = normalize_inventory(result.get("inventory", state["inventory"]))
        fire = dict(result.get("fire_assessment", {}))
        observation = request.observation or {}
        fire.update({k: observation[k] for k in ("fire_area_m2", "smoke_area_m2", "growth_rate", "fire_load_flp") if k in observation})
        people_status = request.people_status.value if request.people_status else result.get("dispatch_plan", {}).get("people_branch", item.input.people_status.value)
        plan = deterministic_v1_dispatch(state, fire, people_status, constraints=request.constraints or result.get("constraints"))
        version = len(item.plan_versions) + 1
        plan.update({"plan_id": "plan-" + uuid4().hex[:10], "task_id": analysis_id, "plan_version": version, "generated_at": datetime.now().isoformat(timespec="seconds"), "replan_trigger": request.triggers})
        if request.constraints: plan["constraints"] = request.constraints
        result["dispatch_plan"] = dict(plan)
        result["constraints"] = request.constraints or result.get("constraints")
        result["skill_chain"] = dict(result.get("skill_chain") or {})
        result["skill_chain"]["candidate_generation"] = {
            "v1_dispatch": plan,
            "candidates": plan.get("tasks", []),
            "selected_uavs": plan.get("selected_uavs", []),
            "source": "deterministic-v1",
        }
        analysis_store.update(analysis_id, status="awaiting_confirmation", result=result, plan_versions=[*item.plan_versions, plan])
        analysis_store.add_event(analysis_id, "replan", "已基于当前资源和约束重新生成方案", "rules")
        self._persist_dispatch_report(analysis_id)
        return self.get_plan(analysis_id)

    def add_round(self, analysis_id: str, request: FeedbackRoundInput) -> Dict[str, Any]:
        item = analysis_store.get(analysis_id)
        if not item: raise KeyError(analysis_id)
        if item.status not in {"executing"}:
            raise ValueError("任务尚未批准执行，禁止反馈")
        if item.status in {"completed", "terminated", "failed"}: raise ValueError("终态任务禁止反馈")
        if request.round != item.monitor_round + 1:
            raise ValueError("轮次必须按任务当前轮次递增")
        # 将本轮观测显式注入闭环计算，避免继续使用首轮固定参数。
        current = analysis_store.get(analysis_id)
        # before is always the Store-owned state, never client supplied values.
        before = {
            "fire_load_flp": (current.result or {}).get("dispatch_plan", {}).get("fire_load_flp"),
            "growth_rate": (current.result or {}).get("fire_assessment", {}).get("growth_rate"),
            "wind_speed": (current.result or {}).get("environment", {}).get("wind_speed"),
            "people_status": (current.result or {}).get("dispatch_plan", {}).get("people_branch", current.input.people_status.value),
            "fleet": analysis_store.fleet(analysis_id),
            "inventory": analysis_store.inventory(analysis_id),
        }
        observed = dict(current.result or {})
        observed["fire_assessment"] = dict(observed.get("fire_assessment", {}))
        if request.fire_load_flp is not None:
            observed["dispatch_plan"] = dict(observed.get("dispatch_plan", {}), fire_load_flp=request.fire_load_flp)
        observed["fire_assessment"].update({k: v for k, v in (("growth_rate", request.growth_rate),) if v is not None})
        if request.fire_load_flp is not None and request.growth_rate is not None:
            observed["fire_assessment"]["growth_flp_per_hour"] = round(request.fire_load_flp * request.growth_rate, 2)
            observed["dispatch_plan"] = dict(observed["dispatch_plan"], growth_flp_per_hour=round(request.fire_load_flp * request.growth_rate, 2))
        observed["environment"] = dict(observed.get("environment", {}))
        if request.wind_speed is not None:
            observed["environment"]["wind_speed"] = request.wind_speed
        if request.people_status is not None:
            observed["dispatch_plan"] = dict(observed.get("dispatch_plan", {}), people_branch=request.people_status.value)
        # ---- 风变演练（FE-35）：剧本轮次注入观测风速升档（一次性），monitor 比对风档
        # 触发 wind_band_changed → 重规划 → 新方案版本走审批门。
        scenario_now = getattr(current.input, "scenario", None) or {}
        shift = scenario_now.get("wind_shift") if isinstance(scenario_now, dict) else None
        if shift and request.round == int(shift.get("round", -1)):
            observed["environment"] = dict(observed.get("environment", {}), wind_speed=float(shift["speed"]))
            post_message(analysis_id, "INFO", "recon", "commander",
                         f"🌪 观测到风速 {shift['speed']} m/s，较方案基准发生跨档变化，已回传指挥中心复核风档。",
                         {"wind_speed": float(shift["speed"]), "round": request.round}, source="rules")
        analysis_store.update(analysis_id, result=observed)
        pass  # shift 注入完成后无需额外处理
        previous_wind = (current.result or {}).get("environment", {}).get("wind_speed")
        previous_flp = float((current.result or {}).get("dispatch_plan", {}).get("fire_load_flp", request.fire_load_flp or 0))
        # ---- 单机失能 → 方案内补位（FE-34）：轮次开始时按场景剧本注入失能。
        # 候选两档由规则算好、大脑只选人；方案内换机不过审批门，补位机当轮即出动。
        try:
            self._maybe_fail_and_backfill(analysis_id, current, request.round)
        except Exception:
            pass  # 演练注入失败不阻塞正常推演
        result = self.monitor_and_update(analysis_id, MonitorInput(elapsed_minutes=request.elapsed_minutes, extinguishing_liters=request.extinguishing_liters, fleet_snapshot=analysis_store.fleet(analysis_id), inventory=analysis_store.inventory(analysis_id)))
        monitor_data = result.get("result", {}).get("monitor", {})
        action = result.get("action")

        # 关键事件判定：风速按档位（0–4/4–6/6–8 m/s）而非数值比较。
        triggers = list(monitor_data.get("replan_triggers", []))
        if request.fire_load_flp is not None and previous_flp > 0 and request.fire_load_flp > previous_flp * 1.2 and "fire_load_increase_over_20_percent" not in triggers:
            triggers.append("fire_load_increase_over_20_percent")
        if request.wind_speed is not None and previous_wind is not None:
            previous_band = resolve_wind_band(float(previous_wind))["band"]
            current_band = resolve_wind_band(float(request.wind_speed))["band"]
            if previous_band != current_band and "wind_band_changed" not in triggers:
                triggers.append("wind_band_changed")
        if request.people_status is not None and "people_status_changed" not in triggers:
            triggers.append("people_status_changed")
        if action in {"resupply", "return"} and "resource_or_soc" not in triggers:
            triggers.append("resource_or_soc")
        # ---- 每轮自主研判（AG-2）：LLM 优先 / conservative 降级；仅 GLM 来源可追加 replan 触发器 ----
        try:
            fleet_now = analysis_store.fleet(analysis_id)
            snapshot = {
                "round": request.round,
                "flp_before": previous_flp,
                "flp_after": monitor_data.get("next_fire_load_flp"),
                "action": action,
                "triggers": list(triggers),
                "min_soc": min((unit.get("soc", 100) for unit in fleet_now), default=100),
                "water_liters": (analysis_store.inventory(analysis_id) or {}).get("water_liters"),
                "wind_speed": request.wind_speed or (result.get("result", {}).get("environment", {}) or {}).get("wind_speed"),
                "people": (result.get("result", {}).get("dispatch_plan", {}) or {}).get("people_branch"),
                # 趋势补强（FE-31）：给研判大脑可见的累计涨幅与连涨轮数——
                # 单轮 ±1% 的噪声看不出问题，累计越过 20% 线时 GLM 应能自主建议 replan
                "flp_initial": item.rounds[0].before.fire_load_flp if item.rounds and item.rounds[0].before else None,
                "flp_growth_pct_since_plan": (
                    round((monitor_data.get("next_fire_load_flp", 0) - item.rounds[0].before.fire_load_flp)
                          / max(item.rounds[0].before.fire_load_flp, 1e-6) * 100, 1)
                    if item.rounds and item.rounds[0].before and monitor_data.get("next_fire_load_flp") is not None else None),
                "flp_rising_streak": _rising_streak(item.rounds, monitor_data.get("next_fire_load_flp")),
            }
            judgment = SIMULATOR.judge(analysis_id, snapshot)
            # GLM replan 建议最低从第 2 轮起生效：首轮单样本噪声大，直接打断刚起步的推演
            # （失能演练、持续压制演示都会被截断）；建议本身仍落协作流可审计。
            if (judgment.get("decision") == "replan" and judgment.get("source") == "glm"
                    and request.round >= 2 and "llm_judgment_replan" not in triggers):
                triggers.append("llm_judgment_replan")
        except Exception:
            pass
        round_data = {
            "round": request.round,
            "before": before,
            "after": {
                **monitor_data,
                "fleet": analysis_store.fleet(analysis_id),
                "inventory": analysis_store.inventory(analysis_id),
            },
            "changes": {
                "fire_load_flp": ((monitor_data.get("next_fire_load_flp"), before.get("fire_load_flp")) if monitor_data.get("next_fire_load_flp") != before.get("fire_load_flp") else None),
                "action": action,
            },
            # finish（火情扑灭）是终态胜利，优先于任何重规划触发器（含 GLM 建议）——
            # 否则扑灭后 GLM 说 replan 会撞上终态守卫 409（test_monitor_finish 复现）
            "replan_required": action != "finish" and (bool(triggers) or action in {"reinforce", "resupply", "return"}),
            "replan_triggers": triggers,
            "next_action": "awaiting_confirmation" if triggers else action,
        }
        if analysis_store.get(analysis_id).status == "terminated":
            # 推演期间任务被终止：本轮作废，不得覆盖终态
            raise ValueError("任务已终止，本轮反馈作废")
        latest = analysis_store.get(analysis_id); analysis_store.update(analysis_id, rounds=[*latest.rounds, round_data])
        if triggers and action != "finish":
            analysis_store.add_event(analysis_id, "replan", "触发重规划关键事件：" + "、".join(triggers), "rules")
            # Generate and persist a new version immediately; it remains gated by
            # approval, so monitoring cannot continue on an unapproved plan.
            self.replan(analysis_id, ReplanRequest(triggers=triggers))
            round_data["next_action"] = "awaiting_confirmation"
        self._persist_dispatch_report(analysis_id)
        return round_data

    def _maybe_fail_and_backfill(self, analysis_id: str, item, round_number: int) -> None:
        """场景剧本的单机失能注入 + 补位决策（FE-34）：幂等（同轮只注入一次）。"""
        scenario = getattr(item.input, "scenario", None) or {}
        fail_round = scenario.get("uav_failure_round") if isinstance(scenario, dict) else None
        if not fail_round or int(fail_round) != round_number:
            return
        existing = analysis_store.get_messages(analysis_id)
        for message in existing:
            if message.get("msg_type") == "UAV_FAULT" and (message.get("data") or {}).get("round") == round_number:
                return
        from ..agents import backfill as backfill_mod
        result = item.result or {}
        dispatch = dict(result.get("dispatch_plan") or {})
        selected = [u for u in dispatch.get("selected_uavs", []) if str(u).startswith("E")]
        fleet = analysis_store.fleet(analysis_id)
        by_id = {d.get("uav_id"): d for d in fleet}
        flying = [u for u in selected if (by_id.get(u) or {}).get("status") in {"flying", "working"}]
        pool = flying or [u for u in selected if (by_id.get(u) or {}).get("status") != "fault"]
        if not pool:
            return
        import random
        victim_id = random.Random(f"fail-{analysis_id}").choice(pool)
        by_id[victim_id]["status"] = "fault"
        candidates = backfill_mod.build_candidates(fleet, set(selected), 20.0)
        decision = backfill_mod.decide(candidates, {"faulted": [victim_id], "fire_load_flp": dispatch.get("fire_load_flp")})
        backfill_mod.announce(analysis_id, victim_id, decision, candidates, round_number)
        choice = decision.get("choice")
        if choice and choice != "none" and choice in by_id:
            by_id[choice]["status"] = "assigned"
            dispatch["selected_uavs"] = [choice if u == victim_id else u for u in dispatch.get("selected_uavs", [])]
            dispatch["tasks"] = [dict(t, drone_id=choice) if t.get("drone_id") == victim_id else dict(t)
                                 for t in dispatch.get("tasks", [])]
            result["dispatch_plan"] = dispatch
            analysis_store.update(analysis_id, result=result)
        analysis_store.update_resources(analysis_id, fleet=fleet)

    def report(self, analysis_id: str) -> Dict[str, Any]:
        item = analysis_store.get(analysis_id)
        if not item:
            raise KeyError(analysis_id)
        report = {
            "task_id": analysis_id,
            "input": item.input.model_dump(),
            "status": item.status,
            "plan_versions": item.plan_versions,
            "rounds": item.rounds,
            "events": [e.model_dump() for e in item.events],
            "result": item.result,
        }
        self._persist_dispatch_report(analysis_id)
        return report

    def report_path(self, analysis_id: str) -> Path:
        item = analysis_store.get(analysis_id)
        if not item:
            raise KeyError(analysis_id)
        self._persist_dispatch_report(analysis_id)
        return REPORTS_DIR / analysis_id / "dispatch_plan.json"

    @staticmethod
    def _persist_dispatch_report(analysis_id: str) -> None:
        item = analysis_store.get(analysis_id)
        if not item:
            return
        target = REPORTS_DIR / analysis_id / "dispatch_plan.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({
            "task_id": analysis_id,
            "schema_version": "uav-dispatch-v1",
            "input": item.input.model_dump(),
            "status": item.status,
            "plan_versions": item.plan_versions,
            "rounds": item.rounds,
            "events": [event.model_dump() for event in item.events],
            "result": item.result,
            "approval": item.approval,
            "resource_locks": item.resource_locks,
        }, ensure_ascii=False, indent=2, default=str)
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(payload, encoding="utf-8")
            # Windows 下目标文件可能被并发读取/杀软扫描瞬时锁定，replace 重试几次
            last_error = None
            for _ in range(5):
                try:
                    temporary.replace(target)
                    last_error = None
                    break
                except PermissionError as error:
                    last_error = error
                    time.sleep(0.15)
            if last_error is not None:
                raise last_error
        finally:
            temporary.unlink(missing_ok=True)


    @staticmethod
    def _merge_agent_result(result: Dict[str, Any], agent: Dict[str, Any]) -> None:
        chain = agent.get("skill_chain", {})
        result["agent"] = agent
        observation = chain.get("fire_perception", {}).get("observation", {})
        explanation = chain.get("fire_perception", {}).get("explanation")
        if explanation:
            result["vlm_explanation"] = explanation
            result["explanation"] = explanation.get("summary") or result.get("explanation")
        assessment = chain.get("fire_assessment", {}).get("assessment", {}).get("data", {})
        if observation:
            result["fire_assessment"].update(
                {key: observation[key] for key in ("fire_area_m2", "smoke_area_m2", "growth_rate", "confidence") if key in observation}
            )
        if assessment:
            result["fire_assessment"].update(
                {key: assessment[key] for key in ("level", "label", "risk_score") if key in assessment}
            )
        resource = chain.get("resource_matching", {}).get("need", {}).get("data", {})
        assignment = chain.get("drone_dispatch", {}).get("assignment", {}).get("data", {})
        if resource:
            result["dispatch_plan"].update(
                {
                    "material_amount": resource.get("total_liters", result["dispatch_plan"].get("material_amount")),
                    "required_drones": chain.get("drone_dispatch", {}).get("count", {}).get("data", {}).get("required_drones", 1),
                }
            )
        if assignment and not result["dispatch_plan"].get("battery_plan"):
            result["dispatch_plan"]["tasks"] = assignment.get("tasks", result["dispatch_plan"].get("tasks", []))
        result["data_mode"] = agent.get("data_mode", result.get("data_mode"))
        env = chain.get("environment_assessment", {})
        if env.get("environment_source"):
            source = env["environment_source"]
            result["environment_source"] = source
            environment = env.get("environment") or {}
            # Keep the persisted analysis environment contract aligned with the
            # tool output, while retaining demo values when a field is absent.
            result["environment"].update({
                key: environment[key]
                for key in (
                    "mode", "status", "source", "wind_speed", "wind_direction",
                    "wind_direction_deg", "altitude", "terrain", "water_sources",
                    "nearest_water", "preferred_water", "road_context", "landcover", "raw", "location", "metadata", "stale",
                )
                if key in environment
            })
            if env.get("nearest_water_distance_m") is not None:
                result["environment"]["nearest_water_distance_m"] = env["nearest_water_distance_m"]
