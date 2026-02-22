"""Archive — move completed features to archive/vN.json.

Usage: python .cc-dev-framework/core/archive.py

Moves all completed features from features.json into archive/vN.json,
keeping features.json clean for the next iteration.
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
        print("No completed features to archive.")
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

    print(f"Archived {len(completed)} features to {version}.json")
    for feat in completed:
        print(f"  {feat['id']}: {feat['title']}")
    print(f"\nfeatures.json now has {len(remaining)} feature(s)")


if __name__ == "__main__":
    main()
