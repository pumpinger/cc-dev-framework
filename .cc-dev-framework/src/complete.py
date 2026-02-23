"""完成 feature — 验证 + 提交 + 合并 + 标记完成。

Usage: python .cc-dev-framework/src/complete.py -f <feature-id> -m "commit message"
"""

from __future__ import annotations

import argparse
import io
import os
import subprocess
import sys
import time
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

    # Clean working tree before merge
    _clean_worktree()

    rc, out = _git("merge", branch, "--no-edit")

    # If merge fails due to untracked files (git clean may miss locked files on Windows),
    # parse the blocking paths, force-remove them with retries, and retry merge once.
    if rc != 0 and "untracked working tree files would be overwritten" in out:
        print("git clean 未能清除所有文件，尝试强制删除后重试...")
        _force_remove_blocking_files(out)
        _clean_worktree()
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


def _clean_worktree():
    """Remove all untracked/ignored files and reset tracked files to HEAD."""
    _git("clean", "-fdx")
    _git("checkout", "--", ".")


def _force_remove_blocking_files(merge_output: str):
    """Parse 'untracked working tree files' from merge error and force-delete them.

    On Windows, files may be locked by lingering processes (e.g. uvicorn holding
    a SQLite .db). Retries with a short sleep to wait for handle release.
    """
    in_file_list = False
    for line in merge_output.splitlines():
        stripped = line.strip()
        if stripped.startswith("error:") and "untracked working tree files" in stripped:
            in_file_list = True
            continue
        if in_file_list:
            if stripped.startswith(("Please ", "Aborting")):
                break
            if stripped:
                filepath = PROJECT_DIR / stripped
                _force_delete(filepath)


def _force_delete(filepath: Path):
    """Delete a file with retries for Windows file locking."""
    for attempt in range(5):
        try:
            if filepath.is_dir():
                import shutil
                shutil.rmtree(filepath, ignore_errors=True)
            elif filepath.exists():
                os.remove(filepath)
            return
        except (PermissionError, OSError):
            time.sleep(0.5 * (attempt + 1))
    # Last resort: ignore failure — merge will report the real error
    print(f"警告: 无法删除 {filepath}")


def _detect_main_branch():
    """Detect whether main branch is 'main' or 'master'."""
    for name in ("main", "master"):
        rc, _ = _git("rev-parse", "--verify", name)
        if rc == 0:
            return name
    return "main"


if __name__ == "__main__":
    main()
