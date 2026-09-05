"""BaseAgent：无状态角色 Agent 基类。

Agent 自身不持有任务状态，全部状态经 analysis_id 读写 store；角色间不直接对话，
通过黑板消息（store.add_message）协作。think 同步返回；think_bg 后台线程叙述——
「数字先行，叙述随后」，LLM 慢/挂完全不影响任务关键路径。
"""
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import llm
from .brain import AgentBrain
from .prompts import SAFETY_RULE


class BaseAgent:
    agent_id: str = ""
    name: str = ""
    role: str = "agent"
    subgroup: str = "system"
    prompt: str = ""
    tools: Dict[str, Callable] = {}

    def __init__(self):
        self._brain = AgentBrain(f"{SAFETY_RULE}\n\n{self.prompt}", self.tools)

    def think(self, task: str, brief: str, max_tokens: int = 800) -> Tuple[Optional[str], List[str]]:
        """同步思考：LLM 可用时返回 (文本, 轨迹)，否则 (None, trace)。永不抛异常。"""
        try:
            return self._brain.run(task, brief, max_tokens=max_tokens)
        except Exception:
            return None, ["agent-think-error"]

    def think_bg(self, analysis_id: str, task: str, brief: str, on_done: Callable[[str, str], None], max_tokens: int = 600) -> None:
        """后台叙述：完成后以 (analysis_id, text) 回调 on_done（由回调方决定如何落库）。"""

        def _worker() -> None:
            text, _ = self.think(task, brief, max_tokens=max_tokens)
            if text:
                try:
                    on_done(analysis_id, llm.audit_numbers(text, brief))
                except Exception:
                    pass

        threading.Thread(target=_worker, daemon=True, name=f"agent-{self.agent_id}").start()
