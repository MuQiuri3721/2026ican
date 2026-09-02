from typing import Any, Callable, Dict, Iterable


class ToolRegistry:
    """按名称注册和解析原子 Tool，Agent 不直接依赖具体实现。"""

    def __init__(self, tools: Iterable[Any] = ()):
        self._tools = {tool.name: tool for tool in tools}

    def register(self, tool: Any) -> None:
        if not getattr(tool, "name", None):
            raise ValueError("Tool 必须提供 name")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Any:
        try:
            return self._tools[name]
        except KeyError as error:
            raise KeyError(f"未知 Tool: {name}") from error

    def list(self) -> list:
        return sorted(self._tools)

    def execute(self, name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.get(name).run(**payload)


def build_registry() -> ToolRegistry:
    from .environment import EnvironmentTool, FleetStatusTool, InventoryTool

    return ToolRegistry([EnvironmentTool(), FleetStatusTool(), InventoryTool()])
