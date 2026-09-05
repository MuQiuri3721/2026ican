"""AgentBrain：有界 ReAct 循环。

约束：白名单只读工具；最多 2 轮工具调用；单轮最多 4 个调用；工具结果截断 ≤800 字；
末轮不带 tools 逼模型直答（智谱端点会无视 tool_choice=none）。工具只做规则计算/检索，
不改任务状态——状态变更只由 Agent 节点显式写 store。
"""
import inspect
import json
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import llm

_MAX_ROUNDS = 2
_MAX_CALLS_PER_ROUND = 4
_TOOL_RESULT_LIMIT = 800


def _schema(fn: Callable) -> Dict[str, Any]:
    """从函数签名 + docstring 首行自动生成 OpenAI tools schema，零手工维护。"""
    signature = inspect.signature(fn)
    properties, required = {}, []
    for name, param in signature.parameters.items():
        annotation = param.annotation
        pytype = "string"
        if annotation in (int, float):
            pytype = "number"
        elif annotation is bool:
            pytype = "boolean"
        properties[name] = {"type": pytype, "description": name}
        if param.default is inspect.Parameter.empty:
            required.append(name)
    doc = (fn.__doc__ or fn.__name__).strip().splitlines()[0]
    return {"type": "function", "function": {"name": fn.__name__, "description": doc, "parameters": {"type": "object", "properties": properties, "required": required}}}


def _truncate(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text[:_TOOL_RESULT_LIMIT]


class AgentBrain:
    def __init__(self, system_prompt: str, tools: Optional[Dict[str, Callable]] = None):
        self.system_prompt = system_prompt
        self.tools = dict(tools or {})

    def run(self, task: str, brief: str, max_tokens: int = 800) -> Tuple[Optional[str], List[str]]:
        """返回 (最终文本|None, 执行轨迹)。LLM 不可用/失败返回 (None, trace)。"""
        if not llm.llm_available():
            return None, ["llm-unavailable"]
        trace: List[str] = []
        messages = [{"role": "system", "content": self.system_prompt}, {"role": "user", "content": f"{task}\n\n{brief}"}]
        tool_schemas = [_schema(fn) for fn in self.tools.values()]
        for round_index in range(_MAX_ROUNDS):
            last_round = round_index == _MAX_ROUNDS - 1
            kwargs = {"messages": messages, "max_tokens": max_tokens}
            if tool_schemas and not last_round:
                kwargs["tools"] = tool_schemas
            text = llm.chat(**kwargs)
            if text is None:
                trace.append("llm-error")
                return None, trace
            tool_calls = self._tool_calls(text)
            if not tool_calls or last_round:
                trace.append("answer")
                return text, trace
            messages.append({"role": "assistant", "content": text})
            for name, arguments in tool_calls[:_MAX_CALLS_PER_ROUND]:
                fn = self.tools.get(name)
                if fn is None:
                    result = f"未知工具 {name}"
                else:
                    try:
                        result = _truncate(fn(**arguments))
                    except Exception as error:  # 工具失败不终止，回报给模型
                        result = f"工具执行失败: {error}"
                trace.append(f"{name} → {result[:80]}")
                messages.append({"role": "user", "content": f"工具 {name} 结果：{result}"})
        return None, trace

    @staticmethod
    def _tool_calls(text: str) -> List[Tuple[str, Dict[str, Any]]]:
        """从文本中解析 [<tool]>{"json":...}</tool> 形式的工具调用（自研薄层协议）。"""
        calls: List[Tuple[str, Dict[str, Any]]] = []
        for match in re.finditer(r"<tool>(\w+)\s*(\{.*?\})\s*</tool>", text, re.S):
            try:
                arguments = json.loads(match.group(2))
                calls.append((match.group(1), arguments if isinstance(arguments, dict) else {}))
            except json.JSONDecodeError:
                continue
        return calls

