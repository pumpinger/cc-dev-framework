"""Verifier Agent — validates that a feature was correctly implemented."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import anthropic

from aifw.agents.base import BaseAgent, AgentResult
from aifw.agents.callbacks import AgentCallbacks
from aifw.state.feature_store import Feature
from aifw.tools.registry import ToolRegistry


VERIFIER_TOOLS = [
    "read_file", "list_files", "search_content", "run_bash",
    "git_status", "git_diff",
]


class VerifierAgent:
    """Wraps BaseAgent with verifier-specific config."""

    def __init__(
        self,
        client: anthropic.Anthropic,
        model: str,
        tool_registry: ToolRegistry,
        callbacks: AgentCallbacks | None = None,
        max_turns: int = 20,
    ):
        self.client = client
        self.model = model
        self.tool_registry = tool_registry
        self.callbacks = callbacks
        self.max_turns = max_turns

        prompt_path = Path(__file__).parent.parent / "prompts" / "verifier.md"
        self.prompt_template = prompt_path.read_text(encoding="utf-8")

    def run(self, project_path: str, feature: Feature) -> AgentResult:
        git_diff = self._get_diff(project_path)
        feature_json = json.dumps(
            {
                "id": feature.id,
                "title": feature.title,
                "steps": [
                    {"description": s.description, "done": s.done}
                    for s in feature.steps
                ],
            },
            indent=2,
            ensure_ascii=False,
        )

        system_prompt = self.prompt_template.format(
            project_path=project_path,
            feature_json=feature_json,
            git_diff=git_diff[:10000],  # Truncate for context limits
        )

        agent = BaseAgent(
            client=self.client,
            model=self.model,
            system_prompt=system_prompt,
            tool_registry=self.tool_registry,
            tool_names=VERIFIER_TOOLS,
            callbacks=self.callbacks,
            max_turns=self.max_turns,
            thinking_budget=2000,
        )

        return agent.run(f"Verify feature: {feature.title} ({feature.id})")

    def result_passed(self, result: AgentResult) -> bool:
        """Check if verifier output indicates PASS."""
        return result.success and result.final_text.strip().upper().startswith("PASS")

    @staticmethod
    def _get_diff(project_path: str) -> str:
        try:
            result = subprocess.run(
                ["git", "diff", "HEAD~1"],
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=10,
                encoding="utf-8",
                errors="replace",
            )
            return result.stdout or "(no diff)"
        except Exception:
            return "(git not available)"
