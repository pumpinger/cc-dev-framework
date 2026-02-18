"""File operation tools — read, write, edit, list, search."""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

from aifw.tools.registry import Tool


def _resolve_safe(path_str: str, project_root: str) -> Path:
    """Resolve a path and ensure it stays within project_root."""
    root = Path(project_root).resolve()
    target = (root / path_str).resolve()
    if not str(target).startswith(str(root)):
        raise PermissionError(f"Path escapes project root: {path_str}")
    return target


def _handle_read_file(inp: dict, project_root: str) -> str:
    path = _resolve_safe(inp["path"], project_root)
    if not path.exists():
        return f"Error: file not found: {inp['path']}"
    if not path.is_file():
        return f"Error: not a file: {inp['path']}"
    content = path.read_text(encoding="utf-8", errors="replace")
    max_lines = inp.get("max_lines", 2000)
    lines = content.splitlines()
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines.append(f"\n... truncated ({len(content.splitlines())} total lines)")
    numbered = [f"{i + 1:4d}\t{line}" for i, line in enumerate(lines)]
    return "\n".join(numbered)


def _handle_write_file(inp: dict, project_root: str) -> str:
    path = _resolve_safe(inp["path"], project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(inp["content"], encoding="utf-8")
    return f"Written {len(inp['content'])} bytes to {inp['path']}"


def _handle_edit_file(inp: dict, project_root: str) -> str:
    path = _resolve_safe(inp["path"], project_root)
    if not path.exists():
        return f"Error: file not found: {inp['path']}"
    content = path.read_text(encoding="utf-8")
    old = inp["old_string"]
    new = inp["new_string"]
    count = content.count(old)
    if count == 0:
        return f"Error: old_string not found in {inp['path']}"
    if count > 1 and not inp.get("replace_all", False):
        return f"Error: old_string found {count} times. Use replace_all=true or provide more context."
    if inp.get("replace_all", False):
        content = content.replace(old, new)
    else:
        content = content.replace(old, new, 1)
    path.write_text(content, encoding="utf-8")
    return f"Edited {inp['path']} ({count} replacement{'s' if count > 1 else ''})"


def _handle_list_files(inp: dict, project_root: str) -> str:
    root = Path(project_root).resolve()
    pattern = inp.get("pattern", "**/*")
    matches = []
    for path in root.rglob("*"):
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            if fnmatch.fnmatch(rel, pattern):
                matches.append(rel)
    matches.sort()
    if not matches:
        return "No files found matching pattern."
    limit = inp.get("max_results", 200)
    if len(matches) > limit:
        return "\n".join(matches[:limit]) + f"\n... and {len(matches) - limit} more"
    return "\n".join(matches)


def _handle_search_content(inp: dict, project_root: str) -> str:
    root = Path(project_root).resolve()
    pattern_str = inp["pattern"]
    glob = inp.get("glob", "**/*")
    try:
        regex = re.compile(pattern_str, re.IGNORECASE if inp.get("ignore_case") else 0)
    except re.error as e:
        return f"Error: invalid regex: {e}"

    results = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if not fnmatch.fnmatch(rel, glob):
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(content.splitlines(), 1):
            if regex.search(line):
                results.append(f"{rel}:{i}: {line.rstrip()}")
                if len(results) >= 100:
                    results.append("... truncated at 100 matches")
                    return "\n".join(results)
    if not results:
        return "No matches found."
    return "\n".join(results)


# --- Tool definitions ---

read_file = Tool(
    name="read_file",
    description="Read the contents of a file. Returns numbered lines.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path from project root"},
            "max_lines": {"type": "integer", "description": "Max lines to read (default 2000)"},
        },
        "required": ["path"],
    },
    handler=_handle_read_file,
)

write_file = Tool(
    name="write_file",
    description="Create or overwrite a file with the given content.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path from project root"},
            "content": {"type": "string", "description": "File content to write"},
        },
        "required": ["path", "content"],
    },
    handler=_handle_write_file,
)

edit_file = Tool(
    name="edit_file",
    description="Replace a specific string in a file. old_string must be unique unless replace_all is true.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path from project root"},
            "old_string": {"type": "string", "description": "Exact text to find"},
            "new_string": {"type": "string", "description": "Replacement text"},
            "replace_all": {"type": "boolean", "description": "Replace all occurrences (default false)"},
        },
        "required": ["path", "old_string", "new_string"],
    },
    handler=_handle_edit_file,
)

list_files = Tool(
    name="list_files",
    description="List files matching a glob pattern relative to project root.",
    input_schema={
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Glob pattern (default **/*)"},
            "max_results": {"type": "integer", "description": "Max files to return (default 200)"},
        },
    },
    handler=_handle_list_files,
)

search_content = Tool(
    name="search_content",
    description="Search file contents with a regex pattern. Returns matching lines with file paths and line numbers.",
    input_schema={
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regex pattern to search for"},
            "glob": {"type": "string", "description": "Glob to filter files (default **/*)"},
            "ignore_case": {"type": "boolean", "description": "Case insensitive search"},
        },
        "required": ["pattern"],
    },
    handler=_handle_search_content,
)

ALL_FILE_TOOLS = [read_file, write_file, edit_file, list_files, search_content]
