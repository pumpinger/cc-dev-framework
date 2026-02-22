"""门禁检查 — 脚本驱动的 feature 完成验证。

Usage: python .cc-dev-framework/roles/verify.py -f <feature-id>

检查 4 个门禁（全部机械检查，无 AI 判断）：
  1. steps_done        — 所有步骤都标记完成？
  2. steps_evidence    — 每个已完成步骤都有证据？
  3. verify_commands    — 所有命令 exit 0？
  4. git_branch        — 在正确的 feature 分支上？

验证通过后，提交（包含证据）然后合并。
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

# Import from core/
sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
from store import (
    DoneEvidence,
    GateCheck,
    PROJECT_DIR,
    VerifyResult,
    get_feature,
    update_evidence,
)


def main():
    parser = argparse.ArgumentParser(description="对 feature 执行门禁检查")
    parser.add_argument("-f", "--feature", required=True, help="Feature ID")
    args = parser.parse_args()

    feature = get_feature(args.feature)
    if feature is None:
        print(f"Feature 未找到: {args.feature}")
        sys.exit(1)

    print(f"门禁检查: {feature.id} ({feature.title})")
    print()

    gates: list[GateCheck] = []
    verify_results: list[VerifyResult] = []

    # --- Gate 1: all steps done? ---
    if not feature.steps:
        gates.append(GateCheck("steps_done", False, "未定义步骤"))
    else:
        undone = [s.description for s in feature.steps if not s.done]
        if undone:
            gates.append(GateCheck(
                "steps_done", False,
                f"{len(undone)} 个步骤未完成: {undone[0]}"
            ))
        else:
            gates.append(GateCheck(
                "steps_done", True,
                f"全部 {len(feature.steps)} 个步骤已完成"
            ))

    # --- Gate 2: evidence for every done step? ---
    done_steps = [s for s in feature.steps if s.done]
    no_evidence = [s.description for s in done_steps if not s.evidence]
    if no_evidence:
        gates.append(GateCheck(
            "steps_evidence", False,
            f"{len(no_evidence)} 个已完成步骤缺少证据: {no_evidence[0]}"
        ))
    elif done_steps:
        gates.append(GateCheck(
            "steps_evidence", True,
            f"全部 {len(done_steps)} 个已完成步骤都有证据"
        ))
    else:
        gates.append(GateCheck("steps_evidence", False, "没有已完成的步骤"))

    # --- Gate 3: verify_commands execution ---
    if not feature.verify_commands:
        gates.append(GateCheck("verify_commands", False, "未定义 verify_commands"))
    else:
        verify_results = _run_commands(feature.verify_commands)
        all_pass = all(r.passed for r in verify_results)
        failed = sum(1 for r in verify_results if not r.passed)
        if all_pass:
            gates.append(GateCheck(
                "verify_commands", True,
                f"全部 {len(verify_results)} 条命令通过"
            ))
        else:
            gates.append(GateCheck(
                "verify_commands", False,
                f"{failed}/{len(verify_results)} 条命令失败"
            ))

    # --- Gate 4: correct git branch? ---
    expected = f"feature/{feature.id}"
    current = _git_current_branch()
    if current == expected:
        gates.append(GateCheck("git_branch", True, f"在分支 {current} 上"))
    else:
        gates.append(GateCheck(
            "git_branch", False,
            f"预期 {expected}，当前 {current or '(未知)'}"
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
    print("门禁检查结果:")
    for g in gates:
        tag = "PASS" if g.passed else "FAIL"
        print(f"  [{tag}] {g.name}: {g.detail}")

    failed_cmds = [r for r in verify_results if not r.passed]
    if failed_cmds:
        print()
        print("失败的命令:")
        for r in failed_cmds:
            print(f"  $ {r.command}")
            print(f"    exit={r.exit_code}")
            if r.stdout:
                for line in r.stdout.split("\n")[:5]:
                    print(f"    {line}")

    print()
    if all_passed:
        print("验证通过")
    else:
        count = sum(1 for g in gates if not g.passed)
        print(f"验证失败（{count} 项检查未通过）")
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
                stdout="超时: 超过 120 秒", passed=False,
            ))
        except Exception as e:
            results.append(VerifyResult(
                command=cmd, exit_code=-1,
                stdout=f"错误: {e}", passed=False,
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
