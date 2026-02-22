"""归档 — 将已完成的 feature 移动到 archive/vN.json。

Usage: python .cc-dev-framework/core/archive.py

将 features.json 中所有 completed 的 feature 归档到 archive/vN.json，
保持 features.json 干净以便下一轮迭代。
"""

from __future__ import annotations

import io
import json
import sys
from datetime import date
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent))
from store import (
    ARCHIVE_DIR,
    load_features,
    save_features,
    next_version,
    list_archives,
    Feature,
)


def main():
    raw = load_features()
    features = raw.get("features", [])

    completed = [f for f in features if f.get("status") == "completed"]
    remaining = [f for f in features if f.get("status") != "completed"]

    if not completed:
        print("没有已完成的 feature 需要归档。")
        return

    # Determine version
    version = next_version()

    # Build archive
    archive_data = {
        "version": version,
        "project": raw.get("project", ""),
        "archived_at": date.today().isoformat(),
        "features": completed,
    }

    # Write archive file
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = ARCHIVE_DIR / f"{version}.json"
    with open(archive_path, "w", encoding="utf-8") as f:
        json.dump(archive_data, f, indent=2, ensure_ascii=False)
        f.write("\n")

    # Update features.json — keep only non-completed
    raw["features"] = remaining
    save_features(raw)

    print(f"已归档 {len(completed)} 个 feature 到 {version}.json")
    for feat in completed:
        print(f"  {feat['id']}: {feat['title']}")
    print(f"\nfeatures.json 现有 {len(remaining)} 个 feature")


if __name__ == "__main__":
    main()
