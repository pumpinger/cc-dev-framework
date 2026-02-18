"""Session state management — tracks current session across potential restarts."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class Session:
    session_id: str
    started_at: str
    current_feature_id: str | None = None
    turns_used: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    last_checkpoint: str = ""

    @staticmethod
    def new() -> Session:
        now = datetime.now(timezone.utc).isoformat()
        return Session(
            session_id=uuid.uuid4().hex[:8],
            started_at=now,
            last_checkpoint=now,
        )

    @staticmethod
    def from_dict(d: dict) -> Session:
        return Session(
            session_id=d["session_id"],
            started_at=d["started_at"],
            current_feature_id=d.get("current_feature_id"),
            turns_used=d.get("turns_used", 0),
            total_input_tokens=d.get("total_input_tokens", 0),
            total_output_tokens=d.get("total_output_tokens", 0),
            estimated_cost_usd=d.get("estimated_cost_usd", 0.0),
            last_checkpoint=d.get("last_checkpoint", ""),
        )

    def add_usage(self, input_tokens: int, output_tokens: int, cost: float) -> None:
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.estimated_cost_usd += cost
        self.turns_used += 1
        self.last_checkpoint = datetime.now(timezone.utc).isoformat()


class SessionManager:
    """Load/save session state from .aifw/session.json."""

    def __init__(self, state_dir: Path):
        self.path = state_dir / "session.json"

    def load_or_create(self) -> Session:
        if self.path.exists():
            with open(self.path, encoding="utf-8") as f:
                return Session.from_dict(json.load(f))
        return Session.new()

    def save(self, session: Session) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(asdict(session), f, indent=2, ensure_ascii=False)
            f.write("\n")

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()
