"""Git operation tools — commit, diff, log, branch management."""

from __future__ import annotations

import subprocess

from aifw.tools.registry import Tool


def _run_git(args: list[str], project_root: str) -> str:
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8",
            errors="replace",
        )
        output = result.stdout
        if result.stderr:
            output += f"\n[stderr] {result.stderr}"
        if result.returncode != 0:
            output += f"\n[exit code: {result.returncode}]"
        return output.strip()
    except subprocess.TimeoutExpired:
        return "Error: git command timed out"
    except FileNotFoundError:
        return "Error: git not found"


def _handle_git_status(inp: dict, project_root: str) -> str:
    return _run_git(["status", "--short"], project_root)


def _handle_git_diff(inp: dict, project_root: str) -> str:
    args = ["diff"]
    if inp.get("staged"):
        args.append("--staged")
    ref = inp.get("ref")
    if ref:
        args.append(ref)
    output = _run_git(args, project_root)
    if len(output) > 20000:
        output = output[:20000] + "\n... truncated"
    return output or "(no changes)"


def _handle_git_log(inp: dict, project_root: str) -> str:
    n = inp.get("count", 10)
    return _run_git(["log", f"--oneline", f"-{n}"], project_root)


def _handle_git_commit(inp: dict, project_root: str) -> str:
    message = inp["message"]
    files = inp.get("files")
    if files:
        add_result = _run_git(["add"] + files, project_root)
        if "error" in add_result.lower() or "fatal" in add_result.lower():
            return f"Error staging files: {add_result}"
    else:
        add_result = _run_git(["add", "-A"], project_root)
        if "fatal" in add_result.lower():
            return f"Error staging: {add_result}"
    return _run_git(["commit", "-m", message], project_root)


def _handle_git_create_branch(inp: dict, project_root: str) -> str:
    branch = inp["branch"]
    return _run_git(["checkout", "-b", branch], project_root)


def _handle_git_checkout(inp: dict, project_root: str) -> str:
    branch = inp["branch"]
    return _run_git(["checkout", branch], project_root)


def _handle_git_merge(inp: dict, project_root: str) -> str:
    branch = inp["branch"]
    return _run_git(["merge", branch], project_root)


def _handle_git_delete_branch(inp: dict, project_root: str) -> str:
    branch = inp["branch"]
    return _run_git(["branch", "-D", branch], project_root)


git_status = Tool(
    name="git_status",
    description="Show working tree status (short format).",
    input_schema={"type": "object", "properties": {}},
    handler=_handle_git_status,
)

git_diff = Tool(
    name="git_diff",
    description="Show changes in the working directory or staged area.",
    input_schema={
        "type": "object",
        "properties": {
            "staged": {"type": "boolean", "description": "Show staged changes only"},
            "ref": {"type": "string", "description": "Compare against a ref (branch, commit)"},
        },
    },
    handler=_handle_git_diff,
)

git_log = Tool(
    name="git_log",
    description="Show recent commit history.",
    input_schema={
        "type": "object",
        "properties": {
            "count": {"type": "integer", "description": "Number of commits to show (default 10)"},
        },
    },
    handler=_handle_git_log,
)

git_commit = Tool(
    name="git_commit",
    description="Stage and commit changes.",
    input_schema={
        "type": "object",
        "properties": {
            "message": {"type": "string", "description": "Commit message"},
            "files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Specific files to stage (default: all changes)",
            },
        },
        "required": ["message"],
    },
    handler=_handle_git_commit,
)

git_create_branch = Tool(
    name="git_create_branch",
    description="Create and switch to a new branch.",
    input_schema={
        "type": "object",
        "properties": {
            "branch": {"type": "string", "description": "Branch name"},
        },
        "required": ["branch"],
    },
    handler=_handle_git_create_branch,
)

git_checkout = Tool(
    name="git_checkout",
    description="Switch to an existing branch.",
    input_schema={
        "type": "object",
        "properties": {
            "branch": {"type": "string", "description": "Branch name"},
        },
        "required": ["branch"],
    },
    handler=_handle_git_checkout,
)

git_merge = Tool(
    name="git_merge",
    description="Merge a branch into the current branch.",
    input_schema={
        "type": "object",
        "properties": {
            "branch": {"type": "string", "description": "Branch to merge"},
        },
        "required": ["branch"],
    },
    handler=_handle_git_merge,
)

git_delete_branch = Tool(
    name="git_delete_branch",
    description="Delete a branch.",
    input_schema={
        "type": "object",
        "properties": {
            "branch": {"type": "string", "description": "Branch to delete"},
        },
        "required": ["branch"],
    },
    handler=_handle_git_delete_branch,
)

ALL_GIT_TOOLS = [
    git_status, git_diff, git_log, git_commit,
    git_create_branch, git_checkout, git_merge, git_delete_branch,
]
