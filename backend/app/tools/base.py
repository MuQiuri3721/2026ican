from typing import Any, Callable, Dict, Iterable, Optional


class ToolError(Exception):
    def __init__(self, code: str, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details or {}


class BaseTool:
    name = "base"
    description = ""
    source = "demo"

    def run(self, **payload):
        raise NotImplementedError

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            result = self.run(**payload)
            return {"ok": True, "tool": self.name, "source": self.source, "data": result}
        except ToolError as error:
            return {"ok": False, "tool": self.name, "source": self.source, "error": {"code": error.code, "message": error.message, "details": error.details}}
        except Exception as error:
            return {"ok": False, "tool": self.name, "source": self.source, "error": {"code": "tool_execution_failed", "message": str(error), "details": {}}}


class FunctionTool(BaseTool):
    def __init__(self, name: str, handler: Callable[..., Dict[str, Any]], description: str = "", source: str = "demo"):
        self.name, self.handler, self.description, self.source = name, handler, description, source

    def run(self, **payload):
        return self.handler(**payload)
