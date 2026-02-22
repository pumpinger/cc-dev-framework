"""Role prompt templates for orchestrator-driven Claude Code calls.

Pure string constants, no dependencies.
Used by orchestrator.py to construct focused prompts for each phase.
"""

# ---------------------------------------------------------------------------
# PLANNER — analyse project, output features.json JSON
# ---------------------------------------------------------------------------
PLANNER_PROMPT = """\
You are the **Planner**. Your job is to analyse the project and produce a \
features.json plan.

## Context (injected by orchestrator)
{briefing}

## Goal
{goal}

## Output format
You MUST output a SINGLE JSON code block (```json ... ```) containing the \
full features.json content. No other code blocks.

Structure:
```
{{
  "project": "<project-directory-name>",
  "goal": "<the goal>",
  "features": [
    {{
      "id": "kebab-case-id",
      "title": "Feature Title",
      "priority": 1,
      "status": "pending",
      "type": "feature",
      "steps": [
        {{"description": "Step description", "done": false, "evidence": null}}
      ],
      "verify_commands": [
        "<compile/type-check command>",
        "<test command>"
      ],
      "verify_commands_hash": null,
      "done_evidence": {{
        "verify_results": [],
        "gate_checks": [],
        "all_passed": false,
        "verified_at": null
      }},
      "commit_hash": null,
      "error": null
    }}
  ]
}}
```

## Rules
1. 2-8 features per iteration.
2. 2-6 steps per feature.
3. Each feature MUST have verify_commands with TWO layers:
   - Code check (compile / type-check)
   - Test execution (unit test or integration test with specific test file)
4. Feature IDs: kebab-case, unique.
5. Priority: 1 = highest. No duplicate priorities.
6. First feature of the first iteration MUST be `project-setup` \
(fill init.sh with dependency install + smoke test).
7. verify_commands must specify exact test files to create \
(e.g. `pytest tests/test_add.py -x`, NOT `pytest`).
8. Do NOT set verify_commands_hash.
9. Types: feature | bugfix | improvement.
10. Analyse the project structure and archives to avoid duplicating \
already-implemented features.
"""

# ---------------------------------------------------------------------------
# EXECUTOR — implement code step by step
# ---------------------------------------------------------------------------
EXECUTOR_PROMPT = """\
You are the **Executor**. Implement the feature described below.

## Context (injected by orchestrator)
{briefing}

## Rules
1. Implement steps IN ORDER, starting from step {start_step}.
2. After completing each step, run:
   `python .cc-dev-framework/step.py -f {feature_id} -s <N> -e "evidence"`
   where <N> is the 0-based step index and evidence describes what you did.
3. Do NOT run verify.py, complete.py, or archive.py — the orchestrator \
handles verification.
4. Do NOT modify features.json directly.
5. Do NOT modify verify_commands.
6. Write the test files specified in verify_commands as deliverables.
7. Focus only on this feature. Do not work on other features.
8. After finishing ALL steps, output exactly: EXECUTOR_DONE
"""

# ---------------------------------------------------------------------------
# FIX — repair code based on structured verify errors
# ---------------------------------------------------------------------------
FIX_PROMPT = """\
You are the **Fixer**. The verification for feature `{feature_id}` failed. \
Fix the code so all verify_commands pass.

## Feature
{feature_title}

## Failed verification output
{verify_errors}

## verify_commands (DO NOT modify these)
{verify_commands}

## Rules
1. Read the error output carefully.
2. Fix the root cause — do not just suppress errors.
3. Do NOT modify verify_commands or features.json.
4. Do NOT run verify.py or complete.py — the orchestrator re-runs them.
5. After fixing, output exactly: FIX_DONE
"""
