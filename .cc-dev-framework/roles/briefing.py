"""Context compression — generate focused briefings for Claude Code calls.

Replaces multi-turn exploration with a single context injection (~3000 tokens).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
from store import (
    ARCHIVE_DIR,
    Feature,
    load_archive,
    load_feature_objects,
    load_features,
    list_archives,
)

# Maximum characters per briefing section
_MAX_TREE_CHARS = 3000
_MAX_CONFIG_CHARS = 2000
_MAX_ARCHIVE_CHARS = 2000
_MAX_TOTAL_CHARS = 12000


# ---------------------------------------------------------------------------
# Directory tree
# ---------------------------------------------------------------------------

def _dir_tree(project_dir: Path, max_depth: int = 3) -> str:
    """Generate a compact directory tree string, excluding common noise."""
    ignore = {
        ".git", "node_modules", "__pycache__", ".venv", "venv",
        ".tox", ".mypy_cache", ".pytest_cache", "dist", "build",
        ".next", ".nuxt", "target", ".gradle", ".idea", ".vscode",
        ".cc-dev-framework", "archive",
    }
    lines: list[str] = []

    def _walk(path: Path, prefix: str, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name))
        except PermissionError:
            return
        dirs = [e for e in entries if e.is_dir() and e.name not in ignore]
        files = [e for e in entries if e.is_file()]

        for f in files:
            lines.append(f"{prefix}{f.name}")
        for d in dirs:
            lines.append(f"{prefix}{d.name}/")
            _walk(d, prefix + "  ", depth + 1)

    _walk(project_dir, "", 0)
    tree = "\n".join(lines)
    if len(tree) > _MAX_TREE_CHARS:
        tree = tree[:_MAX_TREE_CHARS] + "\n... (truncated)"
    return tree


# ---------------------------------------------------------------------------
# Config file snippets
# ---------------------------------------------------------------------------

_CONFIG_FILES = [
    "package.json", "tsconfig.json", "pyproject.toml", "setup.py", "setup.cfg",
    "Cargo.toml", "build.gradle", "build.gradle.kts", "pom.xml",
    "requirements.txt", "Makefile", "CMakeLists.txt", "go.mod",
]


def _read_configs(project_dir: Path) -> str:
    """Read key config files, truncated."""
    parts: list[str] = []
    total = 0
    for name in _CONFIG_FILES:
        path = project_dir / name
        if path.exists() and path.is_file():
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
                if len(content) > 800:
                    content = content[:800] + "\n... (truncated)"
                parts.append(f"--- {name} ---\n{content}")
                total += len(parts[-1])
                if total > _MAX_CONFIG_CHARS:
                    break
            except Exception:
                continue
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Archive summary
# ---------------------------------------------------------------------------

def _archive_summary() -> str:
    """Summarize archived features to avoid re-planning them."""
    archives = list_archives()
    if not archives:
        return "No previous iterations archived."

    lines: list[str] = []
    for a in archives:
        ver = a.replace(".json", "")
        data = load_archive(ver)
        feats = data.get("features", [])
        lines.append(f"{ver}: {len(feats)} features")
        for f in feats:
            fid = f.get("id", "?")
            title = f.get("title", "?")
            lines.append(f"  - {fid}: {title}")

    text = "\n".join(lines)
    if len(text) > _MAX_ARCHIVE_CHARS:
        text = text[:_MAX_ARCHIVE_CHARS] + "\n... (truncated)"
    return text


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_planner_briefing(project_dir: Path, goal: str) -> str:
    """Generate planner context: directory tree, configs, archive summary, rules.

    Target: ~3000 tokens (~12000 chars).
    """
    tree = _dir_tree(project_dir)
    configs = _read_configs(project_dir)
    archive = _archive_summary()

    briefing = f"""\
## Project directory structure
```
{tree}
```

## Config files
{configs if configs else "(no standard config files found)"}

## Previous iterations (archived features — do NOT re-implement)
{archive}

## Planning rules reminder
- 2-8 features, 2-6 steps each
- verify_commands: 2 layers (compile + test), specify exact test files
- IDs: kebab-case, unique priorities
- First iteration priority-1 = project-setup (init.sh)
- Do NOT set verify_commands_hash
"""

    if len(briefing) > _MAX_TOTAL_CHARS:
        briefing = briefing[:_MAX_TOTAL_CHARS] + "\n... (truncated)"
    return briefing


def generate_executor_briefing(
    project_dir: Path,
    feature: Feature,
    start_step: int = 0,
) -> str:
    """Generate executor context: feature details, step status, directory tree.

    Target: ~3000 tokens (~12000 chars).
    """
    # Feature details
    steps_text = ""
    for i, s in enumerate(feature.steps):
        marker = "x" if s.done else " "
        current = " <-- START HERE" if i == start_step and not s.done else ""
        evidence = f" | {s.evidence}" if s.evidence else ""
        steps_text += f"  [{marker}] {i}: {s.description}{evidence}{current}\n"

    vc_text = "\n".join(f"  {cmd}" for cmd in feature.verify_commands)

    tree = _dir_tree(project_dir, max_depth=2)

    briefing = f"""\
## Feature: {feature.id}
Title: {feature.title}
Type: {feature.type}
Priority: {feature.priority}

## Steps
{steps_text}
## verify_commands (DO NOT modify)
{vc_text}

## Project structure
```
{tree}
```

## Reminders
- Run `python .cc-dev-framework/core/step.py -f {feature.id} -s <N> -e "evidence"` \
after each step.
- Do NOT run verify.py / complete.py / archive.py.
- Write test files referenced in verify_commands.
- Output EXECUTOR_DONE when all steps are finished.
"""

    if len(briefing) > _MAX_TOTAL_CHARS:
        briefing = briefing[:_MAX_TOTAL_CHARS] + "\n... (truncated)"
    return briefing
