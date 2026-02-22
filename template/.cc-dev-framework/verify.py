"""Gate check — script-driven verification for feature completion.

Usage: python .cc-dev-framework/roles/verify.py -f <feature-id>

Checks 4 gate points (all mechanical, no AI judgment):
  1. steps_done        — all steps marked done?
  2. steps_evidence    — every done step has evidence?
  3. verify_commands    — all commands exit 0?
  4. git_branch        — on correct feature branch?

After GATE PASSED, commit (includes evidence) then merge.
"""

from __future__ import annotations

import argparse
import io
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Fix Windows GBK encoding for Chinese output
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Import from same directory
sys.path.insert(0, str(Path(__file__).parent))
from store import (
    DoneEvidence,
    GateCheck,
    VerifyResult,
    get_feature,
    update_evidence,
)

PROJECT_DIR = Path(__file__).parent.parent


def main():
    parser = argparse.ArgumentParser(description="Run gate check for a feature")
    parser.add_argument("-f", "--feature", required=True, help="Feature ID")
    args = parser.parse_args()

    feature = get_feature(args.feature)
    if feature is None:
        print(f"Feature not found: {args.feature}")
        sys.exit(1)

    print(f"Gate check: {feature.id} ({feature.title})")
    print()

    gates: list[GateCheck] = []
    verify_results: list[VerifyResult] = []

    # --- Gate 1: all steps done? ---
    if not feature.steps:
        gates.append(GateCheck("steps_done", False, "No steps defined"))
    else:
        undone = [s.description for s in feature.steps if not s.done]
        if undone:
            gates.append(GateCheck(
                "steps_done", False,
                f"{len(undone)} step(s) not done: {undone[0]}"
            ))
        else:
            gates.append(GateCheck(
                "steps_done", True,
                f"All {len(feature.steps)} steps done"
            ))

    # --- Gate 2: evidence for every done step? ---
    done_steps = [s for s in feature.steps if s.done]
    no_evidence = [s.description for s in done_steps if not s.evidence]
    if no_evidence:
        gates.append(GateCheck(
            "steps_evidence", False,
            f"{len(no_evidence)} done step(s) missing evidence: {no_evidence[0]}"
        ))
    elif done_steps:
        gates.append(GateCheck(
            "steps_evidence", True,
            f"All {len(done_steps)} done steps have evidence"
        ))
    else:
        gates.append(GateCheck("steps_evidence", False, "No done steps"))

    # --- Gate 3: verify_commands execution ---
    if not feature.verify_commands:
        gates.append(GateCheck("verify_commands", False, "No verify_commands defined"))
    else:
        verify_results = _run_commands(feature.verify_commands)
        all_pass = all(r.passed for r in verify_results)
        failed = sum(1 for r in verify_results if not r.passed)
        if all_pass:
            gates.append(GateCheck(
                "verify_commands", True,
                f"All {len(verify_results)} commands passed"
            ))
        else:
            gates.append(GateCheck(
                "verify_commands", False,
                f"{failed}/{len(verify_results)} commands failed"
            ))

    # --- Gate 4: correct git branch? ---
    expected = f"feature/{feature.id}"
    current = _git_current_branch()
    if current == expected:
        gates.append(GateCheck("git_branch", True, f"On branch {current}"))
    else:
        gates.append(GateCheck(
            "git_branch", False,
            f"Expected {expected}, on {current or '(unknown)'}"
        ))

    # --- Save evidence ---
    all_passed = all(g.passed for g in gates)
    evidence = DoneEvidence(
        verify_results=verify_results,
        gate_checks=gates,
        all_passed=all_passed,
        verified_at=datetime.now(timezone.utc).isoformat(),
    )
    update_evidence(feature.id, evidence)

    # --- Output ---
    print("Gate checks:")
    for g in gates:
        tag = "PASS" if g.passed else "FAIL"
        print(f"  [{tag}] {g.name}: {g.detail}")

    failed_cmds = [r for r in verify_results if not r.passed]
    if failed_cmds:
        print()
        print("Failed commands:")
        for r in failed_cmds:
            print(f"  $ {r.command}")
            print(f"    exit={r.exit_code}")
            if r.stdout:
                for line in r.stdout.split("\n")[:5]:
                    print(f"    {line}")

    print()
    if all_passed:
        print("GATE PASSED")
    else:
        count = sum(1 for g in gates if not g.passed)
        print(f"GATE FAILED ({count} check(s) not passed)")
        sys.exit(1)



def _run_commands(commands: list[str]) -> list[VerifyResult]:
    results: list[VerifyResult] = []
    for cmd in commands:
        try:
            proc = subprocess.run(
                cmd, shell=True, cwd=str(PROJECT_DIR),
                capture_output=True, timeout=120,
                encoding="utf-8", errors="replace",
            )
            stdout = proc.stdout + proc.stderr
            if len(stdout) > 5000:
                stdout = stdout[:5000] + "\n... (truncated)"
            results.append(VerifyResult(
                command=cmd, exit_code=proc.returncode,
                stdout=stdout.strip(), passed=proc.returncode == 0,
            ))
        except subprocess.TimeoutExpired:
            results.append(VerifyResult(
                command=cmd, exit_code=-1,
                stdout="TIMEOUT: exceeded 120s", passed=False,
            ))
        except Exception as e:
            results.append(VerifyResult(
                command=cmd, exit_code=-1,
                stdout=f"ERROR: {e}", passed=False,
            ))
    return results


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
