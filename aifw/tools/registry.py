"""Tool registry — maps tool definitions to local handlers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    handler: Callable[[dict, str], str]  # (input, project_root) -> result


class ToolRegistry:
    """Central registry of tools available to agents."""

    def __init__(self, project_root: str):
        self.project_root = project_root
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def get_definitions(self, names: list[str] | None = None) -> list[dict]:
        """Return Anthropic API tool definitions for the specified tool names."""
        tools = self._tools.values() if names is None else [
            self._tools[n] for n in names if n in self._tools
        ]
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
            }
            for t in tools
        ]

    def execute(self, name: str, tool_input: dict) -> str:
        """Execute a tool by name. Returns result string."""
        tool = self._tools.get(name)
        if tool is None:
            return f"Error: unknown tool '{name}'"
        try:
            return tool.handler(tool_input, self.project_root)
        except Exception as e:
            return f"Error executing {name}: {e}"

    def list_names(self) -> list[str]:
        return list(self._tools.keys())
