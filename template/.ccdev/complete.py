"""Complete a feature — verify + commit + merge + mark completed.

Usage: python .aifw/complete.py -f <feature-id> -m "commit message"
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
from store import get_feature, update_feature_field

PROJECT_DIR = Path(__file__).parent.parent
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
    parser = argparse.ArgumentParser(description="Complete a feature")
    parser.add_argument("-f", "--feature", required=True, help="Feature ID")
    parser.add_argument("-m", "--message", required=True, help="Commit message")
    args = parser.parse_args()

    feature = get_feature(args.feature)
    if feature is None:
        print(f"Feature not found: {args.feature}")
        sys.exit(1)

    branch = f"feature/{args.feature}"

    # 1. Run verify
    print(f"=== Verify: {args.feature} ===")
    rc, out = _run([sys.executable, str(VERIFY_SCRIPT), "-f", args.feature])
    print(out)
    if rc != 0:
        print("\nVerify failed. Fix issues and retry.")
        sys.exit(1)

    # Re-read feature after verify (verify writes done_evidence)
    feature = get_feature(args.feature)

    # 2. Git add + commit
    print(f"\n=== Commit ===")
    rc, out = _git("add", "-A")
    if rc != 0:
        print(f"git add failed: {out}")
        sys.exit(1)

    rc, out = _git("commit", "-m", args.message)
    if rc != 0:
        print(f"git commit failed: {out}")
        sys.exit(1)

    # Get commit hash
    rc, hash_out = _git("rev-parse", "--short", "HEAD")
    commit_hash = hash_out.strip() if rc == 0 else None
    print(f"Committed: {commit_hash}")

    # 3. Detect main branch name
    main_branch = _detect_main_branch()

    # 4. Merge
    print(f"\n=== Merge {branch} -> {main_branch} ===")
    rc, out = _git("checkout", main_branch)
    if rc != 0:
        print(f"git checkout {main_branch} failed: {out}")
        sys.exit(1)

    rc, out = _git("merge", branch, "--no-edit")
    if rc != 0:
        print(f"git merge failed: {out}")
        sys.exit(1)

    # 5. Delete branch
    _git("branch", "-d", branch)

    # 6. Update features.json
    update_feature_field(args.feature, status="completed", commit_hash=commit_hash)

    print(f"\nCompleted: {args.feature} ({feature.title})")
    print(f"Commit: {commit_hash}")
    print(f"Merged to: {main_branch}")


def _detect_main_branch():
    """Detect whether main branch is 'main' or 'master'."""
    for name in ("main", "master"):
        rc, _ = _git("rev-parse", "--verify", name)
        if rc == 0:
            return name
    return "main"


if __name__ == "__main__":
    main()
