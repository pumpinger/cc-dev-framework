"""Initializer Agent — analyzes a project and generates the feature list."""

from __future__ import annotations

from pathlib import Path

import anthropic

from aifw.agents.base import BaseAgent, AgentResult
from aifw.agents.callbacks import AgentCallbacks
from aifw.tools.registry import ToolRegistry


INITIALIZER_TOOLS = [
    "read_file", "list_files", "search_content", "run_bash", "write_file",
]


class InitializerAgent:
    """Wraps BaseAgent with initializer-specific config."""

    def __init__(
        self,
        client: anthropic.Anthropic,
        model: str,
        tool_registry: ToolRegistry,
        callbacks: AgentCallbacks | None = None,
        max_turns: int = 30,
    ):
        prompt_path = Path(__file__).parent.parent / "prompts" / "initializer.md"
        system_prompt = prompt_path.read_text(encoding="utf-8")

        self.agent = BaseAgent(
            client=client,
            model=model,
            system_prompt=system_prompt,
            tool_registry=tool_registry,
            tool_names=INITIALIZER_TOOLS,
            callbacks=callbacks,
            max_turns=max_turns,
            thinking_budget=6000,
        )

    def run(self, project_path: str, goal: str) -> AgentResult:
        task = (
            f"Project directory: {project_path}\n"
            f"Goal: {goal}\n\n"
            f"Analyze this project and create a feature list in .aifw/features.json."
        )
        return self.agent.run(task)
