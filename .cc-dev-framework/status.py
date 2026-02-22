"""Status display — show progress and recovery info.

Usage: python .cc-dev-framework/status.py
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

# Fix Windows GBK encoding for Chinese output
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

FRAMEWORK_DIR = Path(__file__).parent
sys.path.insert(0, str(FRAMEWORK_DIR / "core"))
from store import load_features, Feature, list_archives, load_archive, ARCHIVE_DIR, PROJECT_DIR


def main():
    raw = load_features()
    features = [Feature.from_dict(fd) for fd in raw.get("features", [])]

    project = raw.get("project", "")
    goal = raw.get("goal", "")
    total = len(features)
    completed = sum(1 for f in features if f.status == "completed")

    print(f"Project: {project}")
    print(f"Goal: {goal}")
    print(f"Progress: {completed}/{total} features completed")

    # --- Archive summary ---
    archives = list_archives()
    if archives:
        total_archived = 0
        for a in archives:
            ver = a.replace(".json", "")
            adata = load_archive(ver)
            count = len(adata.get("features", []))
            total_archived += count
        print(f"Archive: {len(archives)} version(s), {total_archived} features archived")

    # --- Last session from progress.json ---
    last = _last_session()
    if last:
        print()
        print(f"Last session ({last.get('date', '?')}):")
        if last.get("summary"):
            print(f"  {last['summary']}")
        if last.get("next"):
            print(f"  Next: {last['next']}")
        if last.get("blockers"):
            for b in last["blockers"]:
                print(f"  Blocker: {b}")

    # --- Recovery info from features.json ---
    in_progress = next((f for f in features if f.status == "in_progress"), None)
    if in_progress:
        branch = _git_current_branch()
        expected = f"feature/{in_progress.id}"
        done_count = sum(1 for s in in_progress.steps if s.done)
        total_steps = len(in_progress.steps)
        next_step = next(
            (i for i, s in enumerate(in_progress.steps) if not s.done), None
        )

        print()
        print(f"RESUME: {in_progress.id} ({in_progress.title})")
        print(f"  Steps: {done_count}/{total_steps} done")
        if next_step is not None:
            print(f"  Next step [{next_step}]: {in_progress.steps[next_step].description}")
        if branch == expected:
            print(f"  Branch: {branch} (correct)")
        else:
            print(f"  Branch: {branch or '(unknown)'} (expected: {expected})")
        if in_progress.error:
            print(f"  Last error: {in_progress.error}")

    print()

    if not features:
        print("No features planned yet.")
        return

    for f in features:
        icons = {"completed": "[x]", "in_progress": "[>]", "failed": "[!]"}
        icon = icons.get(f.status, "[ ]")
        type_tag = f" [{f.type}]" if f.type != "feature" else ""

        print(f"  {icon} #{f.priority} {f.id}: {f.title} ({f.status}){type_tag}")

        if f.status in ("in_progress", "failed", "completed"):
            for step in f.steps:
                si = "x" if step.done else " "
                ev = f" | {step.evidence}" if step.evidence else ""
                print(f"      [{si}] {step.description}{ev}")

        if f.done_evidence.gate_checks:
            for g in f.done_evidence.gate_checks:
                tag = "PASS" if g.passed else "FAIL"
                print(f"      [{tag}] {g.name}: {g.detail}")

        if f.error:
            print(f"      Error: {f.error}")


def _last_session() -> dict | None:
    path = FRAMEWORK_DIR / "progress.json"
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        sessions = data.get("sessions", [])
        return sessions[-1] if sessions else None
    except Exception:
        return None


def _git_current_branch() -> str | None:
    try:
        proc = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=str(PROJECT_DIR), capture_output=True,
            encoding="utf-8", errors="replace",
        )
        if proc.returncode == 0:
            return proc.stdout.strip() or None
    except Exception:
        pass
    return None


if __name__ == "__main__":
    main()
