"""Progress report generator — produces human-readable progress.md."""

from __future__ import annotations

from pathlib import Path

from aifw.state.feature_store import FeatureStore
from aifw.state.session import Session


def generate_progress(
    feature_store: FeatureStore, session: Session, output_path: Path
) -> None:
    """Generate a human-readable progress.md file."""
    data = feature_store.data
    summary = feature_store.summary()

    lines: list[str] = []
    lines.append(f"# Project: {data.project}")
    lines.append(f"**Goal:** {data.goal}")
    lines.append("")
    lines.append(
        f"**Progress:** {summary['completed']}/{summary['total']} features completed"
    )
    lines.append(
        f"**Session:** {session.session_id} | "
        f"Turns: {session.turns_used} | "
        f"Cost: ${session.estimated_cost_usd:.2f}"
    )
    lines.append("")
    lines.append("## Features")
    lines.append("")

    for f in data.features:
        if f.status == "completed":
            icon = "[x]"
        elif f.status == "in_progress":
            icon = "[>]"
        elif f.status == "failed":
            icon = "[!]"
        else:
            icon = "[ ]"

        lines.append(f"- {icon} **{f.title}** (`{f.id}`) — {f.status}")

        if f.status in ("in_progress", "failed"):
            for i, step in enumerate(f.steps):
                step_icon = "x" if step.done else " "
                lines.append(f"  - [{step_icon}] Step {i + 1}: {step.description}")
            if f.error:
                lines.append(f"  - Error: {f.error}")

    lines.append("")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
