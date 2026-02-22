"""规划质量检查 — features.json 结构的机械验证。

支持 CLI 和模块导入两种方式：
  CLI:    python validate_plan.py
  Import: from validate_plan import validate_plan
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
from store import load_features

KEBAB_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")


def validate_plan(data: dict | None = None, is_first_iteration: bool = True) -> list[str]:
    """Validate features.json structure. Returns list of error strings (empty = valid).

    Args:
        data: Raw features.json dict. If None, loads from disk.
        is_first_iteration: If True, enforces project-setup as first feature.
    """
    if data is None:
        data = load_features()

    errors: list[str] = []

    # --- Check 1: Top-level structure ---
    if not isinstance(data, dict):
        errors.append("features.json must be a JSON object")
        return errors

    if "features" not in data:
        errors.append("Missing 'features' key")
        return errors

    features = data["features"]
    if not isinstance(features, list):
        errors.append("'features' must be a list")
        return errors

    # --- Check 2: Feature count (2-8) ---
    if len(features) < 2:
        errors.append(f"Too few features: {len(features)} (minimum 2)")
    elif len(features) > 8:
        errors.append(f"Too many features: {len(features)} (maximum 8)")

    # --- Check 3-8: Per-feature checks ---
    seen_ids: set[str] = set()
    seen_priorities: set[int] = set()

    for i, f in enumerate(features):
        prefix = f"features[{i}]"

        if not isinstance(f, dict):
            errors.append(f"{prefix}: must be an object")
            continue

        fid = f.get("id", "")
        if fid:
            prefix = f"feature '{fid}'"

        # Check 4: Required fields
        for key in ("id", "title", "priority", "steps", "verify_commands"):
            if key not in f:
                errors.append(f"{prefix}: missing required field '{key}'")

        # Check 5: ID kebab-case
        if fid and not KEBAB_RE.match(fid):
            errors.append(f"{prefix}: id '{fid}' is not valid kebab-case")

        # Check 6: No duplicate IDs
        if fid:
            if fid in seen_ids:
                errors.append(f"{prefix}: duplicate id '{fid}'")
            seen_ids.add(fid)

        # Check 7: No duplicate priorities
        priority = f.get("priority")
        if isinstance(priority, int):
            if priority in seen_priorities:
                errors.append(f"{prefix}: duplicate priority {priority}")
            seen_priorities.add(priority)

        # Check 3: Step count (2-6)
        steps = f.get("steps", [])
        if isinstance(steps, list):
            if len(steps) < 2:
                errors.append(f"{prefix}: too few steps: {len(steps)} (minimum 2)")
            elif len(steps) > 6:
                errors.append(f"{prefix}: too many steps: {len(steps)} (maximum 6)")

        # Check 8: verify_commands two layers (compile + test)
        vc = f.get("verify_commands", [])
        if isinstance(vc, list):
            if len(vc) < 2:
                errors.append(
                    f"{prefix}: verify_commands needs at least 2 commands "
                    f"(compile/type-check + test), got {len(vc)}"
                )

    # --- Check: First iteration must start with project-setup ---
    if is_first_iteration and features:
        # Find the feature with priority 1 (or first feature if no priority 1)
        first_feature = None
        for f in features:
            if isinstance(f, dict) and f.get("priority") == 1:
                first_feature = f
                break
        if first_feature is None and features:
            first_feature = features[0]

        if first_feature and first_feature.get("id") != "project-setup":
            errors.append(
                f"First iteration's priority-1 feature must be 'project-setup', "
                f"got '{first_feature.get('id', '?')}'"
            )

    return errors


def main() -> None:
    data = load_features()
    # Detect first iteration: no archives exist
    from store import list_archives
    is_first = len(list_archives()) == 0

    errors = validate_plan(data, is_first_iteration=is_first)

    if errors:
        print(f"验证失败（{len(errors)} 个错误）:")
        for e in errors:
            print(f"  [FAIL] {e}")
        sys.exit(1)
    else:
        count = len(data.get("features", []))
        print(f"验证通过（{count} 个 feature）")
        sys.exit(0)


if __name__ == "__main__":
    main()
