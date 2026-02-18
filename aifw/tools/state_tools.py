"""State tools — let agents update features.json through controlled interfaces."""

from __future__ import annotations

from pathlib import Path

from aifw.state.feature_store import FeatureStore
from aifw.tools.registry import Tool

# Module-level store reference, set by orchestrator before agent runs
_store: FeatureStore | None = None


def set_store(store: FeatureStore) -> None:
    global _store
    _store = store


def _handle_update_feature(inp: dict, project_root: str) -> str:
    if _store is None:
        return "Error: feature store not initialized"
    feature_id = inp["feature_id"]
    feature = _store.get_feature(feature_id)
    if feature is None:
        return f"Error: feature '{feature_id}' not found"

    action = inp.get("action", "")

    if action == "step_done":
        step_index = inp.get("step_index")
        if step_index is None:
            return "Error: step_index required for step_done"
        # Enforce sequential completion
        for i in range(step_index):
            if not feature.steps[i].done:
                return f"Error: step {i} must be completed before step {step_index}"
        _store.mark_step_done(feature_id, step_index)
        step = feature.steps[step_index]
        done_count = sum(1 for s in feature.steps if s.done)
        return f"Step {step_index} marked done ({done_count}/{len(feature.steps)}): {step.description}"

    elif action == "set_status":
        status = inp.get("status", "")
        if status not in ("pending", "in_progress", "completed", "failed"):
            return f"Error: invalid status '{status}'"
        _store.update_status(feature_id, status)
        return f"Feature '{feature_id}' status set to '{status}'"

    else:
        return f"Error: unknown action '{action}'. Use 'step_done' or 'set_status'"


def _handle_get_features(inp: dict, project_root: str) -> str:
    if _store is None:
        return "Error: feature store not initialized"
    import json
    from dataclasses import asdict
    features = _store.data.features
    result = []
    for f in features:
        result.append({
            "id": f.id,
            "title": f.title,
            "priority": f.priority,
            "status": f.status,
            "steps": [{"description": s.description, "done": s.done} for s in f.steps],
            "passes": f.passes,
        })
    return json.dumps(result, indent=2, ensure_ascii=False)


update_feature = Tool(
    name="update_feature",
    description="Update a feature's status or mark a step as done. Actions: 'step_done' (requires step_index), 'set_status' (requires status).",
    input_schema={
        "type": "object",
        "properties": {
            "feature_id": {"type": "string", "description": "Feature ID"},
            "action": {
                "type": "string",
                "enum": ["step_done", "set_status"],
                "description": "Action to perform",
            },
            "step_index": {"type": "integer", "description": "Step index (for step_done)"},
            "status": {"type": "string", "description": "New status (for set_status)"},
        },
        "required": ["feature_id", "action"],
    },
    handler=_handle_update_feature,
)

get_features = Tool(
    name="get_features",
    description="Get the current feature list with statuses and steps.",
    input_schema={"type": "object", "properties": {}},
    handler=_handle_get_features,
)

ALL_STATE_TOOLS = [update_feature, get_features]
