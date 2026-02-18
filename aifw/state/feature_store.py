"""Feature store — CRUD operations on features.json with atomic writes."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Step:
    description: str
    done: bool = False


@dataclass
class Feature:
    id: str
    title: str
    priority: int
    status: str = "pending"  # pending | in_progress | completed | failed
    steps: list[Step] = field(default_factory=list)
    passes: bool = False
    commit_hash: str | None = None
    error: str | None = None

    @staticmethod
    def from_dict(d: dict) -> Feature:
        steps = [Step(**s) for s in d.get("steps", [])]
        return Feature(
            id=d["id"],
            title=d["title"],
            priority=d["priority"],
            status=d.get("status", "pending"),
            steps=steps,
            passes=d.get("passes", False),
            commit_hash=d.get("commit_hash"),
            error=d.get("error"),
        )


@dataclass
class FeatureStoreData:
    project: str = ""
    goal: str = ""
    features: list[Feature] = field(default_factory=list)


class FeatureStore:
    """Manages features.json with atomic writes and schema enforcement."""

    def __init__(self, path: Path):
        self.path = path
        self._data: FeatureStoreData | None = None

    def exists(self) -> bool:
        return self.path.exists()

    @property
    def data(self) -> FeatureStoreData:
        if self._data is None:
            self._data = self._load()
        return self._data

    def reload(self) -> FeatureStoreData:
        self._data = self._load()
        return self._data

    def init(self, project: str, goal: str) -> FeatureStoreData:
        """Create a new empty features.json."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data = FeatureStoreData(project=project, goal=goal, features=[])
        self._save()
        return self._data

    def get_feature(self, feature_id: str) -> Feature | None:
        for f in self.data.features:
            if f.id == feature_id:
                return f
        return None

    def next_incomplete(self) -> Feature | None:
        """Return the next pending or failed feature by priority."""
        candidates = [
            f for f in self.data.features if f.status in ("pending", "failed")
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda f: f.priority)

    def current_in_progress(self) -> Feature | None:
        """Return the currently in-progress feature, if any."""
        for f in self.data.features:
            if f.status == "in_progress":
                return f
        return None

    def update_status(self, feature_id: str, status: str) -> Feature:
        feature = self._get_or_raise(feature_id)
        feature.status = status
        self._save()
        return feature

    def mark_step_done(self, feature_id: str, step_index: int) -> Feature:
        feature = self._get_or_raise(feature_id)
        if step_index < 0 or step_index >= len(feature.steps):
            raise ValueError(
                f"Step index {step_index} out of range (0-{len(feature.steps) - 1})"
            )
        feature.steps[step_index].done = True
        self._save()
        return feature

    def mark_complete(self, feature_id: str, commit_hash: str) -> Feature:
        feature = self._get_or_raise(feature_id)
        feature.status = "completed"
        feature.passes = True
        feature.commit_hash = commit_hash
        feature.error = None
        self._save()
        return feature

    def mark_failed(self, feature_id: str, error: str) -> Feature:
        feature = self._get_or_raise(feature_id)
        feature.status = "failed"
        feature.passes = False
        feature.error = error
        self._save()
        return feature

    def set_features(self, features: list[Feature]) -> None:
        """Replace entire feature list (used by initializer agent)."""
        self.data.features = features
        self._save()

    def summary(self) -> dict:
        """Return a summary of feature statuses."""
        total = len(self.data.features)
        completed = sum(1 for f in self.data.features if f.status == "completed")
        in_progress = sum(1 for f in self.data.features if f.status == "in_progress")
        failed = sum(1 for f in self.data.features if f.status == "failed")
        pending = sum(1 for f in self.data.features if f.status == "pending")
        return {
            "total": total,
            "completed": completed,
            "in_progress": in_progress,
            "failed": failed,
            "pending": pending,
        }

    def _get_or_raise(self, feature_id: str) -> Feature:
        feature = self.get_feature(feature_id)
        if feature is None:
            raise KeyError(f"Feature not found: {feature_id}")
        return feature

    def _load(self) -> FeatureStoreData:
        if not self.path.exists():
            return FeatureStoreData()
        with open(self.path, encoding="utf-8") as f:
            raw = json.load(f)
        features = [Feature.from_dict(fd) for fd in raw.get("features", [])]
        return FeatureStoreData(
            project=raw.get("project", ""),
            goal=raw.get("goal", ""),
            features=features,
        )

    def _save(self) -> None:
        """Atomic write: write to temp file, then rename."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        raw = {
            "project": self.data.project,
            "goal": self.data.goal,
            "features": [self._feature_to_dict(f) for f in self.data.features],
        }
        # Write to temp file in same directory, then rename for atomicity
        fd, tmp_path = tempfile.mkstemp(
            dir=str(self.path.parent), suffix=".tmp", prefix="features_"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(raw, f, indent=2, ensure_ascii=False)
                f.write("\n")
            # On Windows, target must not exist for rename
            if self.path.exists():
                self.path.unlink()
            Path(tmp_path).rename(self.path)
        except Exception:
            # Clean up temp file on failure
            try:
                Path(tmp_path).unlink()
            except OSError:
                pass
            raise

    @staticmethod
    def _feature_to_dict(f: Feature) -> dict:
        return {
            "id": f.id,
            "title": f.title,
            "priority": f.priority,
            "status": f.status,
            "steps": [asdict(s) for s in f.steps],
            "passes": f.passes,
            "commit_hash": f.commit_hash,
            "error": f.error,
        }
