"""标记步骤完成 — 记录完成证据。

Usage: python .cc-dev-framework/core/step.py -f <feature-id> -s <step-index> -e "evidence text"
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent))
from store import get_feature, update_step


def main():
    parser = argparse.ArgumentParser(description="标记步骤完成")
    parser.add_argument("-f", "--feature", required=True, help="Feature ID")
    parser.add_argument("-s", "--step", required=True, type=int, help="步骤索引 (0-based)")
    parser.add_argument("-e", "--evidence", required=True, help="完成证据")
    args = parser.parse_args()

    feature = get_feature(args.feature)
    if feature is None:
        print(f"Feature 未找到: {args.feature}")
        sys.exit(1)

    if args.step < 0 or args.step >= len(feature.steps):
        print(f"步骤索引 {args.step} 超出范围 (0-{len(feature.steps) - 1})")
        sys.exit(1)

    step = feature.steps[args.step]
    if step.done:
        print(f"步骤 {args.step} 已完成: {step.description}")
        sys.exit(0)

    update_step(args.feature, args.step, done=True, evidence=args.evidence)

    print(f"完成: [{args.step}] {step.description}")
    print(f"证据: {args.evidence}")


if __name__ == "__main__":
    main()
