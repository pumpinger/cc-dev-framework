"""Orchestrator — Python-driven workflow for cc-dev-framework.

Replaces Claude-self-driven CLAUDE.md workflow with deterministic control:
  Python orchestrator controls flow, Claude Code -p does AI work,
  scripts handle verification.

Usage:
  python .cc-dev-framework/orchestrator.py [options]

Options:
  --auto-approve     Skip plan approval (default: ask user)
  --max-retries N    Max verify-fix retries per feature (default: 3)
  --goal "text"      Override goal (otherwise from features.json or interactive)
  --feature ID       Only process a specific feature
  --dry-run          Show execution plan without calling Claude
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import signal
import subprocess
import sys
import textwrap
from datetime import date, datetime, timezone
from pathlib import Path

# Windows encoding fix
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Imports from same directory
sys.path.insert(0, str(Path(__file__).parent))
from briefing import generate_executor_briefing, generate_planner_briefing
from prompts import EXECUTOR_PROMPT, FIX_PROMPT, PLANNER_PROMPT
from store import (
    Feature,
    load_feature_objects,
    load_features,
    save_features,
    seal_all_features,
    update_feature_field,
)
from validate_plan import validate_plan

AIFW_DIR = Path(__file__).parent
PROJECT_DIR = AIFW_DIR.parent
PROGRESS_PATH = AIFW_DIR / "progress.json"

# Claude command timeout (seconds)
CLAUDE_TIMEOUT = 600  # 10 minutes


# ===================================================================
# Signal handling — save state on SIGINT
# ===================================================================

_interrupted = False


def _handle_sigint(signum, frame):
    global _interrupted
    _interrupted = True
    print("\n[orchestrator] Interrupted. Saving state...")
    _save_progress("Interrupted by user", [])
    sys.exit(130)


signal.signal(signal.SIGINT, _handle_sigint)


# ===================================================================
# Core: call Claude Code -p
# ===================================================================

def call_claude(
    prompt: str,
    max_turns: int = 10,
    allowed_tools: str | None = None,
    system_append: str | None = None,
) -> dict:
    """Call Claude Code in print mode and return parsed JSON output.

    Returns dict with keys: result, cost, duration, is_error
    """
    cmd = [
        "claude",
        "-p", prompt,
        "--output-format", "json",
        "--max-turns", str(max_turns),
    ]

    if allowed_tools:
        cmd.extend(["--allowedTools", allowed_tools])

    if system_append:
        cmd.extend(["--append-system-prompt", system_append])

    cmd.append("--dangerously-skip-permissions")

    # Remove CLAUDE_CODE environment variable to prevent nested-call blocking
    env = os.environ.copy()
    env.pop("CLAUDE_CODE", None)
    env.pop("CLAUDECODE", None)

    print(f"[orchestrator] Calling Claude (max_turns={max_turns})...")

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(PROJECT_DIR),
            capture_output=True,
            timeout=CLAUDE_TIMEOUT,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {
            "result": "",
            "cost": None,
            "duration": CLAUDE_TIMEOUT,
            "is_error": True,
            "error": f"Claude timed out after {CLAUDE_TIMEOUT}s",
        }
    except FileNotFoundError:
        return {
            "result": "",
            "cost": None,
            "duration": 0,
            "is_error": True,
            "error": "claude command not found. Is Claude Code CLI installed?",
        }

    # Parse JSON output
    raw = proc.stdout
    if proc.returncode != 0:
        return {
            "result": raw or proc.stderr,
            "cost": None,
            "duration": 0,
            "is_error": True,
            "error": f"Claude exited with code {proc.returncode}: {proc.stderr[:500]}",
        }

    try:
        data = json.loads(raw)
        return {
            "result": data.get("result", ""),
            "cost": data.get("cost_usd"),
            "duration": data.get("duration_ms", 0),
            "is_error": data.get("is_error", False),
        }
    except json.JSONDecodeError:
        # Non-JSON output — return raw text
        return {
            "result": raw,
            "cost": None,
            "duration": 0,
            "is_error": False,
        }


# ===================================================================
# Script runners
# ===================================================================

def run_script(name: str, *args: str) -> int:
    """Run a framework script. Returns exit code."""
    script = AIFW_DIR / name
    cmd = [sys.executable, str(script)] + list(args)
    print(f"[orchestrator] Running: {name} {' '.join(args)}")
    proc = subprocess.run(
        cmd, cwd=str(PROJECT_DIR),
        encoding="utf-8", errors="replace",
    )
    return proc.returncode


def run_script_capture(name: str, *args: str) -> tuple[int, str]:
    """Run a framework script, capture output. Returns (exit_code, output)."""
    script = AIFW_DIR / name
    cmd = [sys.executable, str(script)] + list(args)
    print(f"[orchestrator] Running: {name} {' '.join(args)}")
    proc = subprocess.run(
        cmd, cwd=str(PROJECT_DIR),
        capture_output=True,
        encoding="utf-8", errors="replace",
    )
    output = (proc.stdout + proc.stderr).strip()
    return proc.returncode, output


def run_init() -> bool:
    """Run init.sh. Returns True on success."""
    init_script = AIFW_DIR / "init.sh"
    if not init_script.exists():
        print("[orchestrator] WARNING: init.sh not found, skipping")
        return True

    print("[orchestrator] Running init.sh...")
    proc = subprocess.run(
        ["bash", str(init_script)],
        cwd=str(PROJECT_DIR),
        encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        print("[orchestrator] ERROR: init.sh failed")
        return False
    print("[orchestrator] init.sh OK")
    return True


# ===================================================================
# Verify error extraction
# ===================================================================

def extract_verify_errors(output: str) -> dict:
    """Parse verify.py output into structured error info.

    Returns:
        {
            "summary": "GATE FAILED (N check(s) not passed)",
            "failed_gates": ["gate_name: detail", ...],
            "failed_commands": [{"command": "...", "exit_code": N, "output": "..."}, ...],
        }
    """
    result: dict = {
        "summary": "",
        "failed_gates": [],
        "failed_commands": [],
    }

    # Extract summary line
    for line in output.split("\n"):
        if "GATE FAILED" in line:
            result["summary"] = line.strip()
            break

    # Extract [FAIL] gates
    for line in output.split("\n"):
        m = re.match(r"\s*\[FAIL\]\s+(.*)", line)
        if m:
            result["failed_gates"].append(m.group(1))

    # Extract failed commands block
    in_failed = False
    current_cmd: dict | None = None
    for line in output.split("\n"):
        if line.strip() == "Failed commands:":
            in_failed = True
            continue
        if in_failed:
            m_cmd = re.match(r"\s+\$ (.+)", line)
            m_exit = re.match(r"\s+exit=(\d+|-?\d+)", line)
            if m_cmd:
                if current_cmd:
                    result["failed_commands"].append(current_cmd)
                current_cmd = {"command": m_cmd.group(1), "exit_code": 0, "output": ""}
            elif m_exit and current_cmd:
                current_cmd["exit_code"] = int(m_exit.group(1))
            elif current_cmd and line.startswith("    "):
                current_cmd["output"] += line.strip() + "\n"
        if current_cmd and not line.startswith(" ") and line.strip() and in_failed:
            result["failed_commands"].append(current_cmd)
            current_cmd = None
            in_failed = False

    if current_cmd:
        result["failed_commands"].append(current_cmd)

    return result


# ===================================================================
# User interaction
# ===================================================================

def prompt_user_goal() -> str:
    """Ask user for the project goal interactively."""
    print()
    print("=" * 60)
    print("  What is the goal for this iteration?")
    print("=" * 60)
    try:
        goal = input("> ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(130)
    if not goal:
        print("[orchestrator] No goal provided. Exiting.")
        sys.exit(1)
    return goal


def prompt_user_approval(plan_data: dict) -> bool:
    """Show plan summary and ask for approval. Returns True if approved."""
    features = plan_data.get("features", [])
    print()
    print("=" * 60)
    print("  PLAN REVIEW")
    print("=" * 60)
    print(f"  Project: {plan_data.get('project', '?')}")
    print(f"  Goal: {plan_data.get('goal', '?')}")
    print(f"  Features: {len(features)}")
    print()

    for f in features:
        fid = f.get("id", "?")
        title = f.get("title", "?")
        pri = f.get("priority", "?")
        steps = f.get("steps", [])
        vc = f.get("verify_commands", [])
        ftype = f.get("type", "feature")
        type_tag = f" [{ftype}]" if ftype != "feature" else ""

        print(f"  #{pri} {fid}: {title}{type_tag}")
        for i, s in enumerate(steps):
            print(f"      {i}: {s.get('description', '?')}")
        print(f"      verify: {', '.join(vc)}")
        print()

    print("=" * 60)
    try:
        answer = input("  Approve this plan? [Y/n] > ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False

    return answer in ("", "y", "yes")


# ===================================================================
# Progress persistence
# ===================================================================

def _save_progress(summary: str, completed: list[str], in_progress: str | None = None,
                   current_step: int | None = None, blockers: list[str] | None = None) -> None:
    """Append a session entry to progress.json."""
    if PROGRESS_PATH.exists():
        try:
            with open(PROGRESS_PATH, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {"sessions": []}
    else:
        data = {"sessions": []}

    entry = {
        "date": date.today().isoformat(),
        "completed": completed,
        "in_progress": in_progress,
        "current_step": current_step,
        "summary": summary,
        "next": "",
        "blockers": blockers or [],
    }
    data.setdefault("sessions", []).append(entry)

    with open(PROGRESS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


# ===================================================================
# Plan extraction from Claude output
# ===================================================================

def _extract_json_from_output(text: str) -> dict | None:
    """Extract JSON from Claude's output (looks for ```json blocks)."""
    # Try to find ```json ... ``` block
    pattern = r"```json\s*\n(.*?)\n\s*```"
    matches = re.findall(pattern, text, re.DOTALL)
    if matches:
        # Use the last match (Claude might output explanations before the JSON)
        for m in reversed(matches):
            try:
                return json.loads(m)
            except json.JSONDecodeError:
                continue

    # Fallback: try parsing the entire text as JSON
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Fallback: find anything that looks like a JSON object
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start >= 0 and brace_end > brace_start:
        try:
            return json.loads(text[brace_start : brace_end + 1])
        except json.JSONDecodeError:
            pass

    return None


# ===================================================================
# Main orchestrator flow
# ===================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="cc-dev-framework orchestrator — drives Claude Code for planning + execution"
    )
    parser.add_argument("--auto-approve", action="store_true",
                        help="Skip plan approval prompt")
    parser.add_argument("--max-retries", type=int, default=3,
                        help="Max verify-fix retries per feature (default: 3)")
    parser.add_argument("--goal", type=str, default=None,
                        help="Override project goal")
    parser.add_argument("--feature", type=str, default=None,
                        help="Only process a specific feature ID")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show execution plan without calling Claude")
    args = parser.parse_args()

    print()
    print("=" * 60)
    print("  cc-dev-framework orchestrator")
    print("=" * 60)
    print()

    # ---------------------------------------------------------------
    # PHASE 1: INIT
    # ---------------------------------------------------------------
    print("[PHASE 1] Initializing...")
    if not run_init():
        # init.sh failed — check if we even have features yet.
        # If no features planned, init.sh is expected to fail (template state).
        raw = load_features()
        features = raw.get("features", [])
        has_real_features = any(
            f.get("id") != "example-feature" for f in features
        )
        if has_real_features:
            print("[orchestrator] ERROR: init.sh failed and features exist. Fix init.sh first.")
            sys.exit(1)
        else:
            print("[orchestrator] init.sh failed but no real features yet — continuing to planning.")

    # ---------------------------------------------------------------
    # PHASE 2: RESUME check
    # ---------------------------------------------------------------
    print()
    print("[PHASE 2] Checking for in-progress work...")
    raw = load_features()
    all_features = [Feature.from_dict(fd) for fd in raw.get("features", [])]

    resume_feature: Feature | None = None
    for f in all_features:
        if f.status == "in_progress":
            resume_feature = f
            break

    if resume_feature:
        print(f"[orchestrator] Resuming: {resume_feature.id} ({resume_feature.title})")
        # Skip to execution phase for this feature
        if args.dry_run:
            done = sum(1 for s in resume_feature.steps if s.done)
            print(f"  [dry-run] Would resume {resume_feature.id} from step {done}")
            return
        _execute_feature(resume_feature, args.max_retries)
        # After resuming, fall through to process remaining features
        raw = load_features()
        all_features = [Feature.from_dict(fd) for fd in raw.get("features", [])]

    # ---------------------------------------------------------------
    # PHASE 3: PLAN (if needed)
    # ---------------------------------------------------------------
    pending = [f for f in all_features if f.status == "pending"]
    need_planning = len(all_features) == 0 or (
        len(all_features) == 1
        and all_features[0].id == "example-feature"
    )

    if need_planning:
        print()
        print("[PHASE 3] Planning...")

        # Get goal
        goal = args.goal
        if not goal:
            goal = raw.get("goal", "")
        if not goal:
            if args.dry_run:
                print("  [dry-run] Would ask user for goal")
                return
            goal = prompt_user_goal()

        if args.dry_run:
            print(f"  [dry-run] Would call Claude planner with goal: {goal}")
            return

        # Generate briefing
        briefing = generate_planner_briefing(PROJECT_DIR, goal)

        # Call Claude for planning
        prompt = PLANNER_PROMPT.format(briefing=briefing, goal=goal)
        system_note = (
            "You are called by an orchestrator. Output ONLY a JSON code block. "
            "Do not run any scripts. Do not create files. Just output the plan JSON."
        )
        result = call_claude(
            prompt,
            max_turns=10,
            allowed_tools="Read,Glob,Grep",
            system_append=system_note,
        )

        if result.get("is_error"):
            print(f"[orchestrator] ERROR: Claude planning failed: {result.get('error', result.get('result', ''))}")
            sys.exit(1)

        # Extract JSON from output
        plan_data = _extract_json_from_output(result["result"])
        if plan_data is None:
            print("[orchestrator] ERROR: Could not extract plan JSON from Claude output.")
            print("[orchestrator] Raw output (first 2000 chars):")
            print(result["result"][:2000])
            sys.exit(1)

        # Validate plan
        from store import list_archives
        is_first = len(list_archives()) == 0
        errors = validate_plan(plan_data, is_first_iteration=is_first)

        if errors:
            print(f"[orchestrator] Plan validation failed ({len(errors)} errors):")
            for e in errors:
                print(f"  [FAIL] {e}")

            # Give Claude one retry
            print("[orchestrator] Asking Claude to fix the plan...")
            fix_note = (
                "The plan you produced has validation errors:\n"
                + "\n".join(f"- {e}" for e in errors)
                + "\n\nPlease fix these errors and output a corrected JSON code block."
            )
            result = call_claude(
                prompt + "\n\n## Validation Errors\n" + fix_note,
                max_turns=10,
                allowed_tools="Read,Glob,Grep",
                system_append=system_note,
            )

            if result.get("is_error"):
                print(f"[orchestrator] ERROR: Claude retry failed.")
                sys.exit(1)

            plan_data = _extract_json_from_output(result["result"])
            if plan_data is None:
                print("[orchestrator] ERROR: Could not extract plan JSON on retry.")
                sys.exit(1)

            errors = validate_plan(plan_data, is_first_iteration=is_first)
            if errors:
                print(f"[orchestrator] Plan still invalid after retry:")
                for e in errors:
                    print(f"  [FAIL] {e}")
                sys.exit(1)

        print(f"[orchestrator] Plan validated: {len(plan_data.get('features', []))} features")

        # User approval
        if not args.auto_approve:
            if not prompt_user_approval(plan_data):
                print("[orchestrator] Plan rejected by user.")
                sys.exit(0)

        # Save plan + seal
        save_features(plan_data)
        seal_all_features()
        print("[orchestrator] Plan saved and sealed.")

        # Reload
        raw = load_features()
        all_features = [Feature.from_dict(fd) for fd in raw.get("features", [])]
        pending = [f for f in all_features if f.status == "pending"]

    # ---------------------------------------------------------------
    # PHASE 4: EXECUTE
    # ---------------------------------------------------------------
    if not pending and not resume_feature:
        completed_count = sum(1 for f in all_features if f.status == "completed")
        if completed_count == len(all_features) and all_features:
            print()
            print("[PHASE 5] All features completed!")
        else:
            print("[orchestrator] No pending features to execute.")
        # Jump to archive
    else:
        print()
        print(f"[PHASE 4] Executing {len(pending)} pending feature(s)...")

        # Sort by priority
        pending.sort(key=lambda f: f.priority)

        if args.feature:
            pending = [f for f in pending if f.id == args.feature]
            if not pending:
                print(f"[orchestrator] Feature '{args.feature}' not found or not pending.")
                sys.exit(1)

        if args.dry_run:
            for f in pending:
                print(f"  [dry-run] Would execute: #{f.priority} {f.id} ({f.title})")
                for i, s in enumerate(f.steps):
                    print(f"    {i}: {s.description}")
                print(f"    verify: {', '.join(f.verify_commands)}")
            return

        for feature in pending:
            success = _execute_feature(feature, args.max_retries)
            if not success:
                print(f"[orchestrator] Feature {feature.id} failed after {args.max_retries} retries. Stopping.")
                _save_progress(
                    f"Failed: {feature.id}",
                    [f.id for f in all_features if f.status == "completed"],
                    in_progress=feature.id,
                )
                sys.exit(1)

    # ---------------------------------------------------------------
    # PHASE 5: ARCHIVE
    # ---------------------------------------------------------------
    raw = load_features()
    all_features = [Feature.from_dict(fd) for fd in raw.get("features", [])]
    completed = [f for f in all_features if f.status == "completed"]

    if completed and len(completed) == len(all_features):
        print()
        print("[PHASE 5] Archiving completed features...")
        run_script("archive.py")

    # ---------------------------------------------------------------
    # DONE
    # ---------------------------------------------------------------
    print()
    completed_ids = [f.id for f in all_features if f.status == "completed"]
    _save_progress(
        f"Orchestrator run complete. {len(completed_ids)} feature(s) completed.",
        completed_ids,
    )
    print("[orchestrator] Done.")


# ===================================================================
# Feature execution
# ===================================================================

def _execute_feature(feature: Feature, max_retries: int) -> bool:
    """Execute a single feature: start → code → verify loop.

    Returns True on success, False if retries exhausted.
    """
    print()
    print(f"{'=' * 60}")
    print(f"  Executing: {feature.id} ({feature.title})")
    print(f"{'=' * 60}")

    # Start feature (create branch + set in_progress) if still pending
    if feature.status == "pending":
        rc = run_script("start.py", "-f", feature.id)
        if rc != 0:
            print(f"[orchestrator] ERROR: start.py failed for {feature.id}")
            update_feature_field(feature.id, status="failed", error="start.py failed")
            return False

    # Determine start step (first undone)
    start_step = 0
    for i, s in enumerate(feature.steps):
        if not s.done:
            start_step = i
            break
    else:
        # All steps already done — skip to verify
        start_step = len(feature.steps)

    # Call Claude executor (if steps remain)
    if start_step < len(feature.steps):
        briefing = generate_executor_briefing(PROJECT_DIR, feature, start_step)
        prompt = EXECUTOR_PROMPT.format(
            briefing=briefing,
            feature_id=feature.id,
            start_step=start_step,
        )
        system_note = (
            "You are called by an orchestrator in executor mode. "
            "Implement the feature steps. Use step.py to record progress. "
            "Do NOT run verify.py / complete.py / archive.py."
        )

        result = call_claude(
            prompt,
            max_turns=30,
            system_append=system_note,
        )

        if result.get("is_error"):
            err = result.get("error", "unknown error")
            print(f"[orchestrator] Claude executor error: {err}")
            update_feature_field(feature.id, error=f"Executor error: {err}")
            # Don't mark failed — might be recoverable

    # Verify + fix loop
    for attempt in range(1, max_retries + 1):
        print(f"\n[orchestrator] Verify attempt {attempt}/{max_retries} for {feature.id}")

        rc, verify_output = run_script_capture("verify.py", "-f", feature.id)
        print(verify_output)

        if rc == 0:
            # GATE PASSED — complete the feature
            print(f"\n[orchestrator] GATE PASSED for {feature.id}")
            commit_msg = f"feat({feature.id}): {feature.title}"
            rc = run_script("complete.py", "-f", feature.id, "-m", commit_msg)
            if rc != 0:
                print(f"[orchestrator] WARNING: complete.py failed for {feature.id}")
                update_feature_field(feature.id, error="complete.py failed")
                return False
            return True

        # GATE FAILED — extract errors and fix
        errors = extract_verify_errors(verify_output)
        print(f"[orchestrator] GATE FAILED: {errors['summary']}")
        for g in errors["failed_gates"]:
            print(f"  [FAIL] {g}")

        if attempt >= max_retries:
            break

        # Call Claude to fix
        vc_text = "\n".join(f"  {cmd}" for cmd in feature.verify_commands)
        error_text = verify_output  # Pass full output for context

        prompt = FIX_PROMPT.format(
            feature_id=feature.id,
            feature_title=feature.title,
            verify_errors=error_text,
            verify_commands=vc_text,
        )
        system_note = (
            "You are called by an orchestrator in fix mode. "
            "Fix the code so verify_commands pass. "
            "Do NOT run verify.py / complete.py. Do NOT modify verify_commands."
        )

        result = call_claude(
            prompt,
            max_turns=20,
            system_append=system_note,
        )

        if result.get("is_error"):
            print(f"[orchestrator] Claude fixer error: {result.get('error', '')}")

    # Retries exhausted
    update_feature_field(feature.id, status="failed",
                         error=f"Verify failed after {max_retries} attempts")
    return False


# ===================================================================
# Entry point
# ===================================================================

if __name__ == "__main__":
    main()
