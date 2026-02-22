"""Feature store — data model + atomic JSON read/write for features.json.

Self-contained module, no external dependencies.
Used by verify.py and status.py in the same directory.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

FRAMEWORK_DIR = Path(__file__).parent.parent   # .cc-dev-framework/
PROJECT_DIR = FRAMEWORK_DIR.parent              # project root
FEATURES_PATH = FRAMEWORK_DIR / "features.json"
ARCHIVE_DIR = FRAMEWORK_DIR / "archive"


# --- Data Model ---

@dataclass
class Step:
    description: str
    done: bool = False
    evidence: str | None = None


@dataclass
class VerifyResult:
    command: str
    exit_code: int
    stdout: str
    passed: bool


@dataclass
class GateCheck:
    name: str
    passed: bool
    detail: str


@dataclass
class DoneEvidence:
    verify_results: list[VerifyResult] = field(default_factory=list)
    gate_checks: list[GateCheck] = field(default_factory=list)
    all_passed: bool = False
    verified_at: str | None = None

    @staticmethod
    def from_dict(d: dict) -> DoneEvidence:
        results = [VerifyResult(**r) for r in d.get("verify_results", [])]
        gates = [GateCheck(**g) for g in d.get("gate_checks", [])]
        return DoneEvidence(
            verify_results=results,
            gate_checks=gates,
            all_passed=d.get("all_passed", False),
            verified_at=d.get("verified_at"),
        )


@dataclass
class Feature:
    id: str
    title: str
    priority: int
    status: str = "pending"
    type: str = "feature"  # feature | bugfix | improvement
    steps: list[Step] = field(default_factory=list)
    verify_commands: list[str] = field(default_factory=list)
    verify_commands_hash: str | None = None
    done_evidence: DoneEvidence = field(default_factory=DoneEvidence)
    commit_hash: str | None = None
    error: str | None = None

    @staticmethod
    def from_dict(d: dict) -> Feature:
        steps = [
            Step(
                description=s["description"],
                done=s.get("done", False),
                evidence=s.get("evidence"),
            )
            for s in d.get("steps", [])
        ]
        evidence = DoneEvidence.from_dict(d.get("done_evidence", {}))
        return Feature(
            id=d["id"],
            title=d["title"],
            priority=d["priority"],
            status=d.get("status", "pending"),
            type=d.get("type", "feature"),
            steps=steps,
            verify_commands=d.get("verify_commands", []),
            verify_commands_hash=d.get("verify_commands_hash"),
            done_evidence=evidence,
            commit_hash=d.get("commit_hash"),
            error=d.get("error"),
        )


# --- Read/Write ---

def load_features(path: Path = FEATURES_PATH) -> dict:
    """Load features.json, return raw dict with project/goal/features."""
    if not path.exists():
        return {"project": "", "goal": "", "features": []}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_feature_objects(path: Path = FEATURES_PATH) -> list[Feature]:
    """Load features.json, return list of Feature objects."""
    raw = load_features(path)
    return [Feature.from_dict(fd) for fd in raw.get("features", [])]


def save_features(data: dict, path: Path = FEATURES_PATH) -> None:
    """Atomic write: temp file + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), suffix=".tmp", prefix="features_"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        if path.exists():
            path.unlink()
        Path(tmp_path).rename(path)
    except Exception:
        try:
            Path(tmp_path).unlink()
        except OSError:
            pass
        raise


def get_feature(feature_id: str, path: Path = FEATURES_PATH) -> Feature | None:
    """Get a single feature by ID."""
    for f in load_feature_objects(path):
        if f.id == feature_id:
            return f
    return None


def update_evidence(feature_id: str, evidence: DoneEvidence, path: Path = FEATURES_PATH) -> None:
    """Update done_evidence for a feature and save."""
    raw = load_features(path)
    for fd in raw.get("features", []):
        if fd["id"] == feature_id:
            fd["done_evidence"] = asdict(evidence)
            break
    save_features(raw, path)


def update_feature_field(feature_id: str, path: Path = FEATURES_PATH, **kwargs) -> bool:
    """Update arbitrary fields on a feature dict and save. Returns True if found."""
    raw = load_features(path)
    for fd in raw.get("features", []):
        if fd["id"] == feature_id:
            fd.update(kwargs)
            save_features(raw, path)
            return True
    return False


def update_step(feature_id: str, step_index: int, done: bool, evidence: str | None,
                path: Path = FEATURES_PATH) -> bool:
    """Mark a step done/undone with evidence. Returns True if found."""
    raw = load_features(path)
    for fd in raw.get("features", []):
        if fd["id"] == feature_id:
            steps = fd.get("steps", [])
            if 0 <= step_index < len(steps):
                steps[step_index]["done"] = done
                if evidence is not None:
                    steps[step_index]["evidence"] = evidence
                save_features(raw, path)
                return True
    return False


def feature_to_dict(f: Feature) -> dict:
    d = {
        "id": f.id,
        "title": f.title,
        "priority": f.priority,
        "status": f.status,
        "type": f.type,
        "steps": [asdict(s) for s in f.steps],
        "verify_commands": f.verify_commands,
        "verify_commands_hash": f.verify_commands_hash,
        "done_evidence": asdict(f.done_evidence),
        "commit_hash": f.commit_hash,
        "error": f.error,
    }
    return d


# --- Archive ---

def list_archives(archive_dir: Path = ARCHIVE_DIR) -> list[str]:
    """List archived version files like ['v1.json', 'v2.json']."""
    if not archive_dir.exists():
        return []
    return sorted(f.name for f in archive_dir.glob("v*.json"))


def next_version(archive_dir: Path = ARCHIVE_DIR) -> str:
    """Determine next version number based on existing archives."""
    archives = list_archives(archive_dir)
    if not archives:
        return "v1"
    last = archives[-1].replace(".json", "")  # "v3"
    num = int(last[1:])
    return f"v{num + 1}"


def load_archive(version: str, archive_dir: Path = ARCHIVE_DIR) -> dict:
    """Load an archived version file."""
    path = archive_dir / f"{version}.json"
    if not path.exists():
        return {"version": version, "features": []}
    with open(path, encoding="utf-8") as f:
        return json.load(f)



