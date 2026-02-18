"""Orchestrator — the main engine that drives the init → code → verify → commit loop."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import anthropic

from aifw.agents.callbacks import AgentCallbacks
from aifw.agents.coder import CoderAgent
from aifw.agents.initializer import InitializerAgent
from aifw.agents.terminal_ui import TerminalCallbacks
from aifw.agents.verifier import VerifierAgent
from aifw.config import Config
from aifw.state.feature_store import FeatureStore
from aifw.state.progress import generate_progress
from aifw.state.session import Session, SessionManager
from aifw.tools import state_tools
from aifw.tools.bash import ALL_BASH_TOOLS
from aifw.tools.file_ops import ALL_FILE_TOOLS
from aifw.tools.git import ALL_GIT_TOOLS
from aifw.tools.registry import ToolRegistry
from aifw.tools.state_tools import ALL_STATE_TOOLS


class Orchestrator:
    """Drives the full project development lifecycle."""

    def __init__(self, project_path: str, config: Config):
        self.project_path = Path(project_path).resolve()
        self.config = config
        self.state_dir = self.project_path / ".aifw"
        self.feature_store = FeatureStore(self.state_dir / "features.json")
        self.session_mgr = SessionManager(self.state_dir)
        client_kwargs = {"api_key": config.api_key}
        if config.base_url:
            client_kwargs["base_url"] = config.base_url
        self.client = anthropic.Anthropic(**client_kwargs)
        self.tool_registry = self._build_tools()
        self.callbacks = self._build_callbacks()

        # Wire state tools to our feature store
        state_tools.set_store(self.feature_store)

    def init(self, goal: str) -> None:
        """Phase 1: Run Initializer Agent to generate features.json."""
        self._ensure_git()

        _log_header(f"Initializing project: {self.project_path}")
        _log(f"Goal: {goal}")

        agent = InitializerAgent(
            client=self.client,
            model=self.config.model.initializer,
            tool_registry=self.tool_registry,
            callbacks=self.callbacks,
            max_turns=30,
        )

        result = agent.run(str(self.project_path), goal)

        if result.success:
            # Reload features from what the agent wrote
            self.feature_store.reload()
            summary = self.feature_store.summary()
            _log(f"\nPlan created: {summary['total']} features")
            for f in self.feature_store.data.features:
                _log(f"  [{f.priority}] {f.id}: {f.title} ({len(f.steps)} steps)")
            _log(f"\nCost: ${result.total_cost_usd:.3f}")
        else:
            _log_error(f"Initialization failed: {result.final_text}")
            sys.exit(1)

    def run(self, feature_id: str | None = None) -> None:
        """Phase 2: Execute features one by one."""
        if not self.feature_store.exists():
            _log_error("No features.json found. Run 'aifw init' first.")
            sys.exit(1)

        self._ensure_git()
        session = self.session_mgr.load_or_create()
        _log_header("aifw run")
        _log(f"Session: {session.session_id}")

        if feature_id:
            # Run a specific feature
            feature = self.feature_store.get_feature(feature_id)
            if feature is None:
                _log_error(f"Feature not found: {feature_id}")
                sys.exit(1)
            self._run_feature(session, feature_id)
        else:
            # Run all incomplete features
            while True:
                # Check for in-progress first (resume)
                current = self.feature_store.current_in_progress()
                if current:
                    _log(f"\nResuming in-progress feature: {current.id}")
                    self._run_feature(session, current.id)
                    continue

                nxt = self.feature_store.next_incomplete()
                if nxt is None:
                    break
                self._run_feature(session, nxt.id)

        # Summary
        summary = self.feature_store.summary()
        _log_header("Done")
        _log(
            f"Completed: {summary['completed']}/{summary['total']} | "
            f"Failed: {summary['failed']} | "
            f"Total cost: ${session.estimated_cost_usd:.3f}"
        )
        generate_progress(
            self.feature_store,
            session,
            self.state_dir / "progress.md",
        )

    def status(self) -> None:
        """Show current project status."""
        if not self.feature_store.exists():
            _log("No features.json found. Run 'aifw init' first.")
            return

        data = self.feature_store.data
        summary = self.feature_store.summary()

        _log_header(f"Project: {data.project}")
        _log(f"Goal: {data.goal}")
        _log(
            f"Progress: {summary['completed']}/{summary['total']} "
            f"(in_progress: {summary['in_progress']}, "
            f"failed: {summary['failed']}, "
            f"pending: {summary['pending']})"
        )
        _log("")

        for f in data.features:
            icons = {
                "completed": "[x]",
                "in_progress": "[>]",
                "failed": "[!]",
                "pending": "[ ]",
            }
            icon = icons.get(f.status, "[ ]")
            _log(f"  {icon} [{f.priority}] {f.id}: {f.title}")
            if f.status in ("in_progress", "failed"):
                for i, s in enumerate(f.steps):
                    si = "x" if s.done else " "
                    _log(f"      [{si}] {i}: {s.description}")
                if f.error:
                    _log(f"      Error: {f.error}")

    def _run_feature(self, session: Session, feature_id: str) -> None:
        """Run the code → verify → commit cycle for a single feature."""
        feature = self.feature_store.get_feature(feature_id)
        if feature is None:
            return

        _log_header(f"Feature: {feature.title} ({feature.id})")

        # Update status
        self.feature_store.update_status(feature_id, "in_progress")
        session.current_feature_id = feature_id

        # Create feature branch
        branch_name = f"feature/{feature_id}"
        self._git_run(["checkout", "-b", branch_name])

        # Run Coder Agent
        _log("\n--- Coder Agent ---")
        coder = CoderAgent(
            client=self.client,
            model=self.config.model.coder,
            tool_registry=self.tool_registry,
            callbacks=self.callbacks,
            max_turns=self.config.limits.max_turns_per_feature,
        )
        coder_result = coder.run(str(self.project_path), feature)

        # Track cost
        session.add_usage(
            coder_result.total_input_tokens,
            coder_result.total_output_tokens,
            coder_result.total_cost_usd,
        )
        self.session_mgr.save(session)

        if not coder_result.success:
            _log_error(f"Coder failed: {coder_result.stop_reason}")
            self._abort_feature(feature_id, branch_name, coder_result.final_text)
            return

        # Run Verifier Agent
        _log("\n--- Verifier Agent ---")
        # Reload feature to get updated step states
        feature = self.feature_store.get_feature(feature_id)
        verifier = VerifierAgent(
            client=self.client,
            model=self.config.model.verifier,
            tool_registry=self.tool_registry,
            callbacks=self.callbacks,
            max_turns=20,
        )
        verify_result = verifier.run(str(self.project_path), feature)

        session.add_usage(
            verify_result.total_input_tokens,
            verify_result.total_output_tokens,
            verify_result.total_cost_usd,
        )
        self.session_mgr.save(session)

        if verifier.result_passed(verify_result):
            # Commit and merge
            _log("\nVerification PASSED")
            commit_hash = self._commit_feature(feature, branch_name)
            self.feature_store.mark_complete(feature_id, commit_hash)
            _log(f"Feature completed: {feature.title} [{commit_hash[:7]}]")
        else:
            _log_error(f"Verification FAILED: {verify_result.final_text[:200]}")
            self._abort_feature(feature_id, branch_name, verify_result.final_text)

    def _commit_feature(self, feature, branch_name: str) -> str:
        """Commit changes and merge back to main branch."""
        self._git_run(["add", "-A"])
        self._git_run(["commit", "-m", f"feat: {feature.id} — {feature.title}"])

        # Get commit hash
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(self.project_path),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        commit_hash = result.stdout.strip()

        # Merge to main
        main_branch = self._get_main_branch()
        self._git_run(["checkout", main_branch])
        self._git_run(["merge", branch_name])
        self._git_run(["branch", "-d", branch_name])

        return commit_hash

    def _abort_feature(
        self, feature_id: str, branch_name: str, error: str
    ) -> None:
        """Abandon a failed feature: go back to main, delete branch."""
        self.feature_store.mark_failed(feature_id, error[:500])
        main_branch = self._get_main_branch()
        self._git_run(["checkout", main_branch])
        self._git_run(["branch", "-D", branch_name])

    def _build_tools(self) -> ToolRegistry:
        registry = ToolRegistry(str(self.project_path))
        for tool in ALL_FILE_TOOLS + ALL_BASH_TOOLS + ALL_GIT_TOOLS + ALL_STATE_TOOLS:
            registry.register(tool)
        return registry

    def _build_callbacks(self) -> AgentCallbacks:
        return TerminalCallbacks(self.config.display)

    def _ensure_git(self) -> None:
        """Make sure the project directory is a git repo."""
        git_dir = self.project_path / ".git"
        if not git_dir.exists():
            self._git_run(["init"])
            self._git_run(["add", "-A"])
            self._git_run(["commit", "-m", "initial commit", "--allow-empty"])

    def _get_main_branch(self) -> str:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=str(self.project_path),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        current = result.stdout.strip()
        if current and not current.startswith("feature/"):
            return current
        # Fallback: find main or master
        result = subprocess.run(
            ["git", "branch"],
            cwd=str(self.project_path),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        branches = [b.strip().lstrip("* ") for b in result.stdout.splitlines()]
        for name in ("main", "master"):
            if name in branches:
                return name
        return "master"

    def _git_run(self, args: list[str]) -> str:
        result = subprocess.run(
            ["git"] + args,
            cwd=str(self.project_path),
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0 and result.stderr:
            # Non-fatal: log but don't crash
            _log(f"  git {' '.join(args)}: {result.stderr.strip()}")
        return result.stdout.strip()


def _log(msg: str) -> None:
    print(msg)


def _log_header(msg: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {msg}")
    print(f"{'='*60}")


def _log_error(msg: str) -> None:
    print(f"\033[31m  ERROR: {msg}\033[0m")
