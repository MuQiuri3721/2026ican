"""LLM 解释层路由（BE-9）：指挥员问答（api-contract §5.12）。

GLM 薄层直接复用 agentkit.llm（与多 Agent 整合共用同一实现，含 llm-status 超集，
该端点已在 task_routes 注册，此处不再重复）。本文件只负责：
- 任务黑板摘要（与前端面板同源的事实）作为回答接地数据；
- 同步 chat() 经 to_thread 进线程池，不阻塞事件循环；
- 数字事后审计（agentkit.audit_numbers，⚠ 内嵌标注，只标注不阻断）；
- 未配 Key / 调用失败回落确定性摘要，接口不 5xx。
"""
import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..agentkit import audit_numbers, chat, llm_available, llm_status
from ..services.knowledge import knowledge_stats, query_knowledge
from ..domain.store import analysis_store

router = APIRouter()

SAFETY_RULE = ("你是森林火灾救援调度系统的智能参谋。铁律：只允许解释和复述给定的任务数据，"
               "严禁编造或新增任何数值（FLP/SOC/时间/架次等必须来自给定数据）。"
               "回答不超过 160 字，直接给结论和依据，没有的信息就明说没有。")


class ChatQuestion(BaseModel):
    question: str


@router.get("/api/knowledge")
async def knowledge_endpoint(query: str = "", top_k: int = 3):
    """经验知识库检索（FE-27）：带 query 返回最相关片段，不带返回索引统计。"""
    if query:
        return query_knowledge(query, top_k=top_k)
    return knowledge_stats()


@router.post("/api/tasks/{task_id}/chat")
async def task_chat(task_id: str, payload: ChatQuestion):
    question = payload.question.strip()[:300]  # 防超长输入撑爆上下文
    if not question:
        raise HTTPException(status_code=400, detail="question 不能为空")
    item = analysis_store.get(task_id)
    if item is None:
        raise HTTPException(status_code=404, detail="分析任务不存在")

    brief = _task_brief(item)
    refs = query_knowledge(question, top_k=2)
    knowledge_text = "\n".join(f"[{r['source_name']}·{r['section']}] {r['text'][:180]}" for r in refs.get("results", []))
    answer: str | None = None
    if llm_available():
        # agentkit.chat 为同步 requests 调用，线程池执行避免阻塞事件循环
        answer = await asyncio.to_thread(
            chat,
            [{"role": "system", "content": SAFETY_RULE},
             {"role": "user", "content": f"任务实时数据（规则引擎产出，不可修改）：\n{brief}\n\n知识库参考：\n{knowledge_text or '无相关片段'}\n\n指挥员提问：{question}"}],
            300,
        )
    if not answer:
        answer = f"（离线规则模式）当前任务阶段 {item.status}。{brief}"
    else:
        answer = audit_numbers(answer, brief)  # 未知数字内嵌 ⚠ 标注
    return {"answer": answer, "llm": llm_status()}


def _task_brief(item: Any) -> str:
    """黑板摘要：与前端面板同源的事实，供 GLM 接地 / 离线兜底文案复用。"""
    result = item.result or {}
    fire = result.get("fire_assessment") or {}
    plan = result.get("dispatch_plan") or {}
    env = result.get("environment") or {}
    rounds = item.rounds or []
    last = rounds[-1] if rounds else None
    if last is not None and hasattr(last, "model_dump"):
        last = last.model_dump()
    time_window = plan.get("estimated_control_time") or {}
    gap = plan.get("resource_gap") or []
    gap_text = "、".join(str(g.get("resource") or g.get("name") or g) for g in gap) if isinstance(gap, list) else str(gap)
    earliest, latest = time_window.get("earliest_minutes"), time_window.get("latest_minutes")
    window_text = f"{earliest}-{latest} 分钟" if earliest is not None and latest is not None else "—"
    try:
        # 任务尚无消耗快照（water_liters 缺失）时回落基础库存，避免答"未提供"
        inventory = analysis_store.inventory(item.analysis_id)
        if inventory.get("water_liters") is None:
            inventory = analysis_store.inventory()
    except Exception:  # noqa: BLE001 —— 库存快照缺失不阻断问答
        inventory = {}
    people = getattr(item.input, "people_status", None)
    people_text = getattr(people, "value", people) or "—"
    lines = [
        f"阶段: {item.status}; 监测轮次 {len(rounds)}; 方案版本 {len(item.plan_versions or [])}",
        f"火情: {fire.get('label', '—')}, FLP {fire.get('fire_load_flp', '—')}, "
        f"面积 {fire.get('fire_area_m2', '—')}m², 增长率 {fire.get('growth_rate', '—')}",
        f"环境: 风 {env.get('wind_speed', '—')}m/s {env.get('wind_direction', '—')}, 海拔 {env.get('altitude', '—')}m",
        f"人员状态: {people_text}",
        f"方案: {plan.get('plan_id', '—')} 可控={plan.get('can_control', '—')}, "
        f"出动 {plan.get('selected_uavs', [])}, 药剂 {plan.get('material_module', '—')}, "
        f"时间区间 {window_text}",
        f"资源缺口: {gap_text or '无'}",
        f"库存: 水 {inventory.get('water_liters', '—')}L / W20模块 {inventory.get('water_modules_w20', '—')} / "
        f"C6模块 {inventory.get('co2_modules_c6', '—')} / 电池 {inventory.get('battery_packs', '—')}",
    ]
    if last:
        lines.append(f"最新轮次: {json.dumps(last, ensure_ascii=False, default=str)[:400]}")
    return "\n".join(lines)
