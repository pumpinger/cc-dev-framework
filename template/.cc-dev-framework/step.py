"""Mark a step as done with evidence.

Usage: python .aifw/step.py -f <feature-id> -s <step-index> -e "evidence text"
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
    parser = argparse.ArgumentParser(description="Mark a step as done")
    parser.add_argument("-f", "--feature", required=True, help="Feature ID")
    parser.add_argument("-s", "--step", required=True, type=int, help="Step index (0-based)")
    parser.add_argument("-e", "--evidence", required=True, help="Evidence text")
    args = parser.parse_args()

    feature = get_feature(args.feature)
    if feature is None:
        print(f"Feature not found: {args.feature}")
        sys.exit(1)

    if args.step < 0 or args.step >= len(feature.steps):
        print(f"Step index {args.step} out of range (0-{len(feature.steps) - 1})")
        sys.exit(1)

    step = feature.steps[args.step]
    if step.done:
        print(f"Step {args.step} already done: {step.description}")
        sys.exit(0)

    update_step(args.feature, args.step, done=True, evidence=args.evidence)

    print(f"Done: [{args.step}] {step.description}")
    print(f"Evidence: {args.evidence}")


if __name__ == "__main__":
    main()
