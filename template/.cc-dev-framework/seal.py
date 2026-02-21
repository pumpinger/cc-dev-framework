"""Seal verify_commands — compute and store hashes after planning.

Usage: python .cc-dev-framework/seal.py

Called by the planner after writing features.json.
Computes SHA-256 hash of each feature's verify_commands and stores it
in the verify_commands_hash field. The verifier (verify.py) checks
this hash to ensure the executor didn't tamper with verify_commands.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

# Fix Windows GBK encoding
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent))
from store import compute_verify_hash, load_features, save_features


def main():
    raw = load_features()
    sealed = 0
    for fd in raw.get("features", []):
        commands = fd.get("verify_commands", [])
        if not commands:
            print(f"  SKIP {fd['id']}: no verify_commands")
            continue
        h = compute_verify_hash(commands)
        fd["verify_commands_hash"] = h
        sealed += 1
        print(f"  SEAL {fd['id']}: {h}  ({len(commands)} commands)")

    save_features(raw)
    print(f"\nSealed {sealed} feature(s).")


if __name__ == "__main__":
    main()
