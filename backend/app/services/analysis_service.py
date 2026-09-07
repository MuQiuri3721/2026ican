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
    """尾部连续「带压制仍净上涨」的轮数（含本轮），供研判识别趋势而非单轮噪声。

    store 的 rounds 是 List[Dict]（Envelope.rounds），必须按 dict 取值——
    曾误用模型属性访问（round_item.after.fire_load_flp）导致第 2 轮起 AttributeError。
    """
    streak = 0
    prev = current_flp
    for round_item in reversed(rounds or []):
        after = (round_item.get("after") or {}).get("fire_load_flp")
        before = (round_item.get("before") or {}).get("fire_load_flp")
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


_ADD_ROUND_SEQ = 0


def _file_sha16(path: Optional[str]) -> Optional[str]:
    """输入文件 SHA-256 前 16 位（溯源用）；文件缺失/不可读返回 None，不阻断分析。"""
    if not path:
        return None
    try:
        import hashlib
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]
    except OSError:
        return None


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
            # 单图上传也必须进 VLM 图片序列（BE-11：二级直连要求有可读图片，空序列会静默跳到规则回退）；
            # 帧 序 列工具（140 行）仍用 sequence_paths——单帧无趋势可比，保持原样跳过
            vlm_image_paths = sequence_paths or ([request.image_path] if request.image_path else [])
            context = {
                "scene_id": request.scene_id,
                "scenario": scenario,
                "image_name": request.image_name or "default",
                "image_path": request.image_path,
                "image_paths": vlm_image_paths,
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
            # 输入文件 hash 溯源（实现差异审计§八：provider/provenance）。
            result["input_provenance"] = {
                "image_name": request.image_name,
                "image_sha256_16": _file_sha16(request.image_path),
                "frame_sha256_16": [_file_sha16(p) for p in sequence_paths],
            }
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
            # BE-12：研判 FLP 与面积同步更新（此前面积动、FLP 停在初值，两个字段互相矛盾）
            updated["fire_assessment"]["fire_load_flp"] = monitor_result.get("next_fire_load_flp", updated["fire_assessment"].get("fire_load_flp"))
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
            # 结案回收（对照 firepatrol recover_round）：扑灭归档时把全部在外机撤回基地。
            self._recover_fleet_to_base(analysis_id, updated)
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
        if request.action == "approve":
            # BE-12：方案生效瞬间记录火情基线，闭环按「相对本方案的累计涨幅」触发重规划
            # （此前基线逐轮漂移，20% 阈值永远触不到——火翻倍仍恒 continue）
            live = analysis_store.get(analysis_id)
            live_result = dict(live.result or {})
            live_plan = dict(live_result.get("dispatch_plan") or {})
            live_plan["base_fire_load_flp"] = live_plan.get("fire_load_flp")
            live_result["dispatch_plan"] = live_plan
            analysis_store.update(analysis_id, result=live_result)
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
        # BE-12：重规划是「重新组织本任务」，在途/补给中的机不得因执行态被自己的重规划
        # 排除——dispatch 候选只认 available/assigned，曾致重规划方案只剩 R/S 甚至为空、
        # 压制归零、每轮触发累计涨幅的空转重规划循环（小火 60 轮不灭的根因）。
        # status 归位供候选筛选；SOC 原值保留（<35% 仍被 §4.2 硬约束拦下），
        # fault（FE-34 失能）继续排除。此处是规划用一次性副本，不影响运行态。
        state["fleet"] = [
            {**u, "status": ("available" if u.get("status") not in {"available", "assigned", "fault"} else u.get("status"))}
            for u in state["fleet"]
        ]
        state["inventory"] = normalize_inventory(result.get("inventory", state["inventory"]))
        fire = dict(result.get("fire_assessment", {}))
        observation = request.observation or {}
        fire.update({k: observation[k] for k in ("fire_area_m2", "smoke_area_m2", "growth_rate", "fire_load_flp") if k in observation})
        # 状态续接（FE-39）：重规划必须「带着当前火势与风况」重新组织，而不是回到起点——
        # 此前 fire_load_flp 用初始值、风用场景旧值，导致每轮重复触发 wind_band_changed
        # （方案打到 v13、FLP 永远回到 1800、E 机反复从基地重飞）。
        dispatch_now = result.get("dispatch_plan") or {}
        latest_flp = dispatch_now.get("fire_load_flp")
        if latest_flp is not None:
            fire["fire_load_flp"] = latest_flp
            # BE-12：面积按研判比率折算（area_per_flp 随场景 FLP 系数变化，禁硬编码 180）
            fire["fire_area_m2"] = round(latest_flp * float(fire.get("area_per_flp") or 180.0))
        latest_growth = dispatch_now.get("growth_flp_per_hour")
        if latest_growth is not None:
            fire["growth_flp_per_hour"] = latest_growth
        observed_wind = (result.get("environment") or {}).get("wind_speed")
        if observed_wind is not None:
            state["scene"]["wind_speed"] = observed_wind
            fire["wind_speed"] = observed_wind
            # 关键：dispatch 优先读 fire["wind_band"]（旧档位对象），必须同步重算，
            # 否则新方案风档停留在旧值 → 每轮重复触发 wind_band_changed（v13 死循环根因）
            from ..rules.engine import resolve_wind_band
            fire["wind_band"] = resolve_wind_band(observed_wind)
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
        global _ADD_ROUND_SEQ
        _ADD_ROUND_SEQ += 1
        print(f"[add-round-dbg] #{_ADD_ROUND_SEQ} tid={analysis_id[-6:]} round={request.round} status={item.status}")
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
        # ---- 单机失能 → 方案内补位（FE-34，两阶段）：轮次开始时标记故障机（先于监测，
        # 使重规划 regeneration 自动排除故障机）；监测/重规划之后再执行补位换机，
        # 避免同轮重规划的新名单覆盖补位结果（2026-09-08 修复）。
        try:
            victim_id = self._mark_fault(analysis_id, current, request.round)
        except Exception as error:
            import traceback
            print(f"[drill-debug] {type(error).__name__}: {error}")
            traceback.print_exc()
        result = self.monitor_and_update(analysis_id, MonitorInput(elapsed_minutes=request.elapsed_minutes, extinguishing_liters=request.extinguishing_liters, fleet_snapshot=analysis_store.fleet(analysis_id), inventory=analysis_store.inventory(analysis_id)))
        try:
            self._backfill_after_monitor(analysis_id, victim_id, request.round)
        except Exception as error:
            import traceback
            print(f"[drill-debug] backfill: {type(error).__name__}: {error}")
            traceback.print_exc()
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
        # ---- 失控安全网（BE-12）：累计涨幅必须对比「本方案批准时的基线」——
        # 此前 20% 阈值只有逐轮比较（每轮 +4% 永远到不了线），火翻一倍系统仍恒
        # continue 零触发器；approve 时 stamp 的 base_fire_load_flp 让失控可见。
        base_flp = (current.result or {}).get("dispatch_plan", {}).get("base_fire_load_flp")
        next_flp_now = monitor_data.get("next_fire_load_flp")
        # 绝对下限 20 FLP（≈3.6 ha）：余烬级清扫阶段的 ±3 FLP 波动即超相对阈值，
        # 曾在 6-12 FLP 时触发重规划风暴（每轮一个新方案版本）
        if base_flp and base_flp >= 20.0 and next_flp_now is not None and next_flp_now > base_flp * 1.2 and "fire_load_increase_over_20_percent" not in triggers:
            triggers.append("fire_load_increase_over_20_percent")
        # ---- 每轮自主研判（AG-2）：LLM 优先 / conservative 降级；仅 GLM 来源可追加 replan 触发器 ----
        # BE-12：rounds 存的是 dict（Envelope.rounds=List[Dict]），曾按模型属性访问
        # .before.fire_load_flp → 第 2 轮起 AttributeError 被 except 静默吞掉，
        # 自主研判从第 2 轮起整场消失。first_before 先按 dict 取出。
        first_before = (item.rounds[0].get("before") or {}).get("fire_load_flp") if item.rounds else None
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
                "flp_initial": first_before,
                "flp_growth_pct_since_plan": (
                    round((monitor_data.get("next_fire_load_flp", 0) - first_before)
                          / max(first_before, 1e-6) * 100, 1)
                    if first_before is not None and monitor_data.get("next_fire_load_flp") is not None else None),
                "flp_rising_streak": _rising_streak(item.rounds, monitor_data.get("next_fire_load_flp")),
            }
            judgment = SIMULATOR.judge(analysis_id, snapshot)
            # GLM replan 建议最低从第 2 轮起生效：首轮单样本噪声大，直接打断刚起步的推演
            # （失能演练、持续压制演示都会被截断）；建议本身仍落协作流可审计。
            # BE-12：再加趋势闸门（累计涨幅 ≥10% 或连涨 ≥3 轮）——压制轮次天然有
            # 「作业轮降、补给轮升」的锯齿，GLM 看到连涨 1-2 轮就建议 replan 会反复
            # 打断作业节奏（实测一次任务被打断 7 次）；硬安全网（相对基线 20%）不受影响。
            # BE-12：再加趋势闸门（相对当前方案基线累计 ≥10% 或连涨 ≥3 轮）——压制作业
            # 天然锯齿（作业轮降、补给轮升），GLM 看到连涨 1-2 轮就建议 replan 会反复
            # 打断作业节奏（实测一次任务被打断 7 次）；硬安全网（相对基线 20%）不受影响。
            # 基线必须用 base_fire_load_flp（当前方案批准时）——flp_growth_pct_since_plan
            # 用的是任务首轮值，火高于开局就恒开闸，等于没有闸门。
            pct_vs_base = ((next_flp_now - base_flp) / base_flp * 100) if (base_flp and next_flp_now is not None) else 0
            # 基线 <20 FLP（余烬清扫段）时趋势闸门恒关：±1 FLP 即超 10%，GLM 每轮都会建议 replan
            trend_gate = base_flp and base_flp >= 20.0 and (pct_vs_base >= 10 or (snapshot["flp_rising_streak"] or 0) >= 3)
            if (judgment.get("decision") == "replan" and judgment.get("source") == "glm"
                    and request.round >= 2 and trend_gate and "llm_judgment_replan" not in triggers):
                triggers.append("llm_judgment_replan")
        except Exception as error:  # 吞异常必须留痕，否则研判静默失联无从排查
            import traceback
            print(f"[judge-debug] R{request.round} 自主研判失败: {type(error).__name__}: {error}")
            traceback.print_exc()
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
            "next_action": action if action == "finish" else ("awaiting_confirmation" if triggers else action),
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

    def _recover_fleet_to_base(self, analysis_id: str, updated) -> None:
        """结案回收（对照 firepatrol recover_round，逐一清单②）：扑灭归档时把全部在外机撤回基地。

        按火点→基地航程扣减返航 SOC（rate×minutes/60，下限 0），故障机归位即停机检修；
        只更新机队与协作消息，不推进火情轮次（rounds 时间线止于扑灭轮）。
        后端 fleet.position 恒为基地位，因此归位即状态收敛，前端标记由推演钟停摆自然定格。
        """
        import math
        result = dict(updated.result or {})
        fleet = result.get("fleet") or []
        origin = (result.get("scene") or {}).get("fire_origin") or {"x": 0, "y": 0}
        pts = [u.get("position") or {} for u in fleet]
        base_x = sum(float(p.get("x", 0)) for p in pts) / max(len(pts), 1)
        base_y = sum(float(p.get("y", 0)) for p in pts) / max(len(pts), 1)
        distance_m = math.hypot(float(origin.get("x", 0)) - base_x, float(origin.get("y", 0)) - base_y)
        outbound, longest = [], 0.0
        for unit in fleet:
            if unit.get("status") in {"flying", "working", "returning", "servicing", "charging"}:
                speed = max(float(unit.get("speed_mps", 8)), 0.1)
                minutes = distance_m / speed / 60
                rate = float(unit.get("energy_rate_percent_per_hour", 180))
                unit["soc"] = round(max(0.0, float(unit.get("soc", 0)) - rate * minutes / 60), 2)
                longest = max(longest, minutes)
                outbound.append(unit.get("uav_id", "?"))
            if unit.get("status") != "fault":
                unit["status"] = "available"
        result["fleet"] = fleet
        analysis_store.update(analysis_id, result=result)
        analysis_store.update_resources(analysis_id, fleet, None)
        names = "、".join(outbound) if outbound else "全员"
        post_message(analysis_id, "RECOVERY", "human", "all",
                     f"任务结束，下令全员返航：{names} 共 {len(outbound) if outbound else len(fleet)} 架返回紫霞湖基地。",
                     {"returning": outbound or [u.get("uav_id") for u in fleet]}, source="rules")
        post_message(analysis_id, "RECOVERY", "human", "all",
                     f"全员返航完成：{len(fleet)} 架降落基地，最长航程 {longest:.1f} 分钟。故障机原地停机检修。",
                     {"longest_minutes": round(longest, 1)}, source="rules")
        analysis_store.add_event(analysis_id, "recovery",
                                 f"结案回收：{len(fleet)} 架归位基地，最长航程 {longest:.1f} 分钟", "rules")

    def _mark_fault(self, analysis_id: str, item, round_number: int) -> Optional[str]:
        """场景剧本单机失能注入（FE-34）第一阶段：幂等标记故障机，返回 victim_id。

        故障标记必须在监测/重规划之前完成，使重规划 regeneration 自动排除故障机；
        补位换机在监测之后执行（_backfill_after_monitor），避免同轮重规划覆盖补位名单。
        """
        scenario = getattr(item.input, "scenario", None) or {}
        fail_round = scenario.get("uav_failure_round") if isinstance(scenario, dict) else None
        if not fail_round or int(fail_round) != round_number:
            return None
        existing = analysis_store.get_messages(analysis_id)
        for message in existing:
            if message.get("msg_type") == "UAV_FAULT":
                return None  # 失能演练每任务一次（uav_failure_round 指定轮；重试/后续轮不得二次注入）
        result = item.result or {}
        dispatch = dict(result.get("dispatch_plan") or {})
        selected = list(dispatch.get("firefighting_uavs") or [u for u in dispatch.get("selected_uavs", []) if str(u).startswith("E")])
        fleet = analysis_store.fleet(analysis_id)
        by_id = {d.get("uav_id"): d for d in fleet}
        flying = [u for u in selected if (by_id.get(u) or {}).get("status") in {"flying", "working"}]
        pool = flying or [u for u in selected if (by_id.get(u) or {}).get("status") != "fault"]
        if not pool:
            post_message(analysis_id, "INFO", "recon", "commander",
                         f"失能演练跳过：当前方案（第 {round_number} 轮）无在飞灭火机，无失能目标。",
                         {"round": round_number, "skipped": True}, source="rules")
            return None
        import random
        victim_id = random.Random(f"fail-{analysis_id}").choice(pool)
        by_id[victim_id]["status"] = "fault"
        analysis_store.update_resources(analysis_id, fleet=fleet)
        post_message(analysis_id, "UAV_FAULT", "simulator", "commander",
                     f"⚠ {victim_id} 遥测中断、电量骤降，按机电故障处置，立即评估补位。",
                     {"faulted": victim_id, "round": round_number}, source="rules")
        return victim_id

    def _backfill_after_monitor(self, analysis_id: str, victim_id: Optional[str], round_number: int) -> None:
        """FE-34 第二阶段：监测/重规划尘埃落定后的补位换机。

        若同轮触发重规划，新方案版本已自动把故障机移出名单（候选池排除 fault），
        此时补位转为提示；未触发重规划时按两档候选换机（方案内换机，不过审批门）。
        """
        if not victim_id:
            return
        from ..agents import backfill as backfill_mod
        result = (analysis_store.get(analysis_id).result or {})
        dispatch = dict(result.get("dispatch_plan") or {})
        roster = list(dispatch.get("selected_uavs") or dispatch.get("firefighting_uavs") or [])
        fleet = analysis_store.fleet(analysis_id)
        if victim_id not in roster:
            post_message(analysis_id, "BACKFILL", "suppression", "commander",
                         f"🔁 {victim_id} 失能：同轮触发重规划，新方案版本已将故障机移出出动名单"
                         f"（当前出动 {roster}），无需单独补位。",
                         {"faulted": victim_id, "choice": "none", "round": round_number}, source="rules")
            return
        candidates = backfill_mod.build_candidates(fleet, set(roster) | {victim_id}, 20.0)
        decision = backfill_mod.decide(candidates, {"faulted": [victim_id], "fire_load_flp": dispatch.get("fire_load_flp")})
        choice = decision.get("choice")
        rationale = str(decision.get("rationale", ""))[:120]
        if choice and choice != "none" and choice in {d.get("uav_id") for d in fleet}:
            # 原位替换 victim→choice（旧推导式先过滤 victim 再判 u==victim，choice 永远插不进名单）
            dispatch["selected_uavs"] = [choice if u == victim_id else u for u in roster]
            dispatch["tasks"] = [dict(t, drone_id=choice) if t.get("drone_id") == victim_id else dict(t)
                                 for t in dispatch.get("tasks", []) if t.get("drone_id") != victim_id]
            fleet_by_id = {d.get("uav_id"): d for d in fleet}
            fleet_by_id[choice]["status"] = "assigned"
            result["dispatch_plan"] = dispatch
            analysis_store.update(analysis_id, result=result)
            analysis_store.update_resources(analysis_id, fleet=fleet)
            post_message(analysis_id, "BACKFILL", "suppression", "commander",
                         f"🔁 补位决策：{victim_id} 失能 → {choice} 顶替（方案内换机，不改目标与规模，"
                         f"无需重新审批）。{rationale}",
                         {"faulted": victim_id, "choice": choice, "candidates": candidates}, source=decision.get("source", "rules"))
        else:
            post_message(analysis_id, "BACKFILL", "suppression", "commander",
                         f"🔁 补位决策：{victim_id} 失能，无满足出动门槛的备用机；{rationale}。移交自主研判。",
                         {"faulted": victim_id, "choice": "none"}, source=decision.get("source", "rules"))

    @staticmethod
    def _build_review(item) -> Dict[str, Any]:
        """复盘档案（架构纪要§九）：初始/最终火势、轮次、方案版本、审批与结果，全部出自 Store 记录。"""
        rounds = item.rounds or []
        result = item.result or {}
        initial_flp = None
        if rounds and isinstance(rounds[0].get("before"), dict):
            initial_flp = rounds[0]["before"].get("fire_load_flp")
        if initial_flp is None:
            initial_flp = result.get("fire_assessment", {}).get("fire_load_flp")
        final_flp = None
        if rounds and isinstance(rounds[-1].get("after"), dict):
            final_flp = rounds[-1]["after"].get("fire_load_flp")
        if final_flp is None:
            final_flp = result.get("dispatch_plan", {}).get("fire_load_flp")
        numeric = isinstance(initial_flp, (int, float)) and isinstance(final_flp, (int, float))
        return {
            "initial_flp": initial_flp,
            "final_flp": final_flp,
            "flp_delta": round(final_flp - initial_flp, 2) if numeric else None,
            "extinguished": bool(numeric and final_flp <= 0),
            "round_count": len(rounds),
            "plan_version_count": len(item.plan_versions or []),
            "approval_event_count": sum(1 for e in item.events if "approval" in str(e.stage)),
            "status": item.status,
        }

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
            "review": self._build_review(item),
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
