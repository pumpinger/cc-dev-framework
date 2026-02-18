"""Coder Agent — implements a single feature step by step."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import anthropic

from aifw.agents.base import BaseAgent, AgentResult
from aifw.agents.callbacks import AgentCallbacks
from aifw.state.feature_store import Feature
from aifw.tools.registry import ToolRegistry


CODER_TOOLS = [
    "read_file", "write_file", "edit_file", "list_files", "search_content",
    "run_bash", "git_status", "git_diff", "update_feature", "get_features",
]


class CoderAgent:
    """Wraps BaseAgent with coder-specific config and context building."""

    def __init__(
        self,
        client: anthropic.Anthropic,
        model: str,
        tool_registry: ToolRegistry,
        callbacks: AgentCallbacks | None = None,
        max_turns: int = 50,
    ):
        self.client = client
        self.model = model
        self.tool_registry = tool_registry
        self.callbacks = callbacks
        self.max_turns = max_turns

        prompt_path = Path(__file__).parent.parent / "prompts" / "coder.md"
        self.prompt_template = prompt_path.read_text(encoding="utf-8")

    def run(self, project_path: str, feature: Feature) -> AgentResult:
        # Build context
        git_log = self._get_git_log(project_path)
        tech_info = self._detect_tech(project_path)
        feature_json = json.dumps(
            {
                "id": feature.id,
                "title": feature.title,
                "steps": [
                    {"index": i, "description": s.description, "done": s.done}
                    for i, s in enumerate(feature.steps)
                ],
            },
            indent=2,
            ensure_ascii=False,
        )

        system_prompt = self.prompt_template.format(
            project_path=project_path,
            feature_json=feature_json,
            git_log=git_log,
            tech_info=tech_info,
        )

        agent = BaseAgent(
            client=self.client,
            model=self.model,
            system_prompt=system_prompt,
            tool_registry=self.tool_registry,
            tool_names=CODER_TOOLS,
            callbacks=self.callbacks,
            max_turns=self.max_turns,
            thinking_budget=4000,
        )

        task = (
            f"Implement feature: {feature.title} ({feature.id})\n\n"
            f"Steps:\n"
            + "\n".join(
                f"  {'[x]' if s.done else '[ ]'} {i}. {s.description}"
                for i, s in enumerate(feature.steps)
            )
            + "\n\nStart with the first incomplete step."
        )
        return agent.run(task)

    @staticmethod
    def _get_git_log(project_path: str) -> str:
        try:
            result = subprocess.run(
                ["git", "log", "--oneline", "-10"],
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.stdout.strip() or "(no commits yet)"
        except Exception:
            return "(git not available)"

    @staticmethod
    def _detect_tech(project_path: str) -> str:
        """Detect tech stack from common project files."""
        root = Path(project_path)
        indicators = []
        checks = {
            "package.json": "Node.js",
            "requirements.txt": "Python (pip)",
            "pyproject.toml": "Python (modern)",
            "Cargo.toml": "Rust",
            "go.mod": "Go",
            "pom.xml": "Java (Maven)",
            "build.gradle": "Java (Gradle)",
            "Gemfile": "Ruby",
            "composer.json": "PHP",
        }
        for filename, tech in checks.items():
            if (root / filename).exists():
                indicators.append(tech)
        return ", ".join(indicators) if indicators else "Unknown"
