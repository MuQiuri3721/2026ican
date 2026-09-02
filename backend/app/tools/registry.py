from typing import Any, Dict, Iterable

from .base import BaseTool
from .core import build_core_tools, get_environment, get_fleet_status, get_inventory


class ToolRegistry:
    """统一注册、查找和执行原子 Tool。"""
    def __init__(self, tools: Iterable[BaseTool] = ()):
        self._tools = {}
        for tool in tools:
            self.register(tool)
    def register(self, tool: BaseTool) -> None:
        if not isinstance(tool, BaseTool) or not tool.name:
            raise ValueError("Tool 必须继承 BaseTool 并提供 name")
        if tool.name in self._tools:
            raise ValueError("Tool 已注册: " + tool.name)
        self._tools[tool.name] = tool
    def get(self, name: str) -> BaseTool:
        if name not in self._tools:
            raise KeyError("未知 Tool: " + name)
        return self._tools[name]
    def list(self) -> list:
        return sorted(self._tools)
    def execute(self, name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.get(name).execute(payload)


def build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for name, handler, description in [("get_environment", get_environment, "读取场景环境"), ("get_fleet_status", get_fleet_status, "读取无人机状态"), ("get_inventory", get_inventory, "读取物资库存")]:
        registry.register(CallableTool(name, handler, description, "demo-data"))
    for tool in build_core_tools():
        registry.register(tool)
    return registry


class CallableTool(BaseTool):
    def __init__(self, name, handler, description, source):
        self.name, self.handler, self.description, self.source = name, handler, description, source
    def run(self, **payload):
        return self.handler(**payload)
