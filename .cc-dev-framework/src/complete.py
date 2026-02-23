"""完成 feature — 验证 + 提交 + 合并 + 标记完成。

Usage: python .cc-dev-framework/src/complete.py -f <feature-id> -m "commit message"
"""

from __future__ import annotations

import argparse
import io
import subprocess
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent))
from store import get_feature, update_feature_field, PROJECT_DIR

VERIFY_SCRIPT = Path(__file__).parent / "verify.py"


def _run(cmd, **kwargs):
    """Run a command, return (returncode, stdout+stderr)."""
    proc = subprocess.run(
        cmd, cwd=str(PROJECT_DIR), capture_output=True,
        encoding="utf-8", errors="replace", **kwargs,
    )
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def _git(*args):
    return _run(["git"] + list(args))


def main():
    parser = argparse.ArgumentParser(description="完成 feature")
    parser.add_argument("-f", "--feature", required=True, help="Feature ID")
    parser.add_argument("-m", "--message", required=True, help="提交信息")
    parser.add_argument("--skip-verify", action="store_true",
                        help="跳过验证（编排器已验证）")
    args = parser.parse_args()

    feature = get_feature(args.feature)
    if feature is None:
        print(f"Feature 未找到: {args.feature}")
        sys.exit(1)

    branch = f"feature/{args.feature}"

    # 1. Run verify (unless skipped by orchestrator)
    if not args.skip_verify:
        print(f"=== 验证: {args.feature} ===")
        rc, out = _run([sys.executable, str(VERIFY_SCRIPT), "-f", args.feature])
        print(out)
        if rc != 0:
            print("\n验证失败。请修复问题后重试。")
            sys.exit(1)

        # Re-read feature after verify (verify writes done_evidence)
        feature = get_feature(args.feature)

    # 2. Git add + commit
    print(f"\n=== 提交 ===")
    rc, out = _git("add", "-A")
    if rc != 0:
        print(f"git add 失败: {out}")
        sys.exit(1)

    # Unstage framework log files — they should never be committed
    _git("reset", "--", ".cc-dev-framework/*.log")

    rc, out = _git("commit", "-m", args.message)
    if rc != 0:
        if "nothing to commit" in out:
            print("没有新的变更需要提交，使用最新 commit。")
        else:
            print(f"git commit 失败: {out}")
            sys.exit(1)

    # Get commit hash
    rc, hash_out = _git("rev-parse", "--short", "HEAD")
    commit_hash = hash_out.strip() if rc == 0 else None
    print(f"已提交: {commit_hash}")

    # 3. Detect main branch name
    main_branch = _detect_main_branch()

    # 4. Merge
    print(f"\n=== 合并 {branch} -> {main_branch} ===")

    # Stash any dirty files (e.g. session.log, crm.db written during execution).
    # These are runtime artifacts — drop them after merge, don't restore.
    # Restoring (pop) would leave dirty files on master that block the NEXT merge.
    _git("stash", "--include-untracked")

    rc, out = _git("checkout", main_branch)
    if rc != 0:
        print(f"git checkout {main_branch} 失败: {out}")
        _git("stash", "drop")
        sys.exit(1)

    # Remove untracked runtime artifacts (e.g. e2e_test.db) that would block merge
    _git("clean", "-fd")
    # Reset tracked files to HEAD (e.g. todolist.db dirtied by lingering background processes)
    _git("checkout", "--", ".")

    rc, out = _git("merge", branch, "--no-edit")
    if rc != 0:
        print(f"git merge 失败: {out}")
        _git("stash", "drop")
        sys.exit(1)

    # 5. Delete branch
    _git("branch", "-d", branch)

    # Drop stashed runtime artifacts (don't pop — avoids dirty files blocking next merge)
    _git("stash", "drop")

    # 6. Update features.json
    update_feature_field(args.feature, status="completed", commit_hash=commit_hash)

    print(f"\n已完成: {args.feature} ({feature.title})")
    print(f"提交: {commit_hash}")
    print(f"已合并到: {main_branch}")


def _detect_main_branch():
    """Detect whether main branch is 'main' or 'master'."""
    for name in ("main", "master"):
        rc, _ = _git("rev-parse", "--verify", name)
        if rc == 0:
            return name
    return "main"


if __name__ == "__main__":
    main()
