"""启动 feature — 创建分支 + 设置状态为 in_progress。

Usage: python .cc-dev-framework/core/start.py -f <feature-id>
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


def main():
    parser = argparse.ArgumentParser(description="启动 feature")
    parser.add_argument("-f", "--feature", required=True, help="Feature ID")
    args = parser.parse_args()

    feature = get_feature(args.feature)
    if feature is None:
        print(f"Feature 未找到: {args.feature}")
        sys.exit(1)

    if feature.status not in ("pending", "failed"):
        print(f"Feature {args.feature} 状态为 {feature.status}，期望 pending 或 failed")
        sys.exit(1)

    # Create branch
    branch = f"feature/{args.feature}"
    proc = subprocess.run(
        ["git", "checkout", "-b", branch],
        cwd=str(PROJECT_DIR), capture_output=True,
        encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        # Branch might already exist, try checkout
        proc = subprocess.run(
            ["git", "checkout", branch],
            cwd=str(PROJECT_DIR), capture_output=True,
            encoding="utf-8", errors="replace",
        )
        if proc.returncode != 0:
            print(f"无法创建或切换到分支 {branch}")
            print(proc.stderr)
            sys.exit(1)

    # Set status
    update_feature_field(args.feature, status="in_progress")

    print(f"已启动: {args.feature} ({feature.title})")
    print(f"分支: {branch}")
    print(f"步骤数: {len(feature.steps)}")
    for i, s in enumerate(feature.steps):
        tag = "x" if s.done else " "
        print(f"  [{tag}] {i}: {s.description}")


if __name__ == "__main__":
    main()
