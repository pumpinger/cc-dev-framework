"""Bash execution tool — runs shell commands with timeout and safety limits."""

from __future__ import annotations

import subprocess

from aifw.tools.registry import Tool


def _handle_run_bash(inp: dict, project_root: str) -> str:
    command = inp["command"]
    timeout = inp.get("timeout", 120)

    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output_parts = []
        if result.stdout:
            output_parts.append(result.stdout)
        if result.stderr:
            output_parts.append(f"[stderr]\n{result.stderr}")
        output_parts.append(f"[exit code: {result.returncode}]")
        output = "\n".join(output_parts)

        # Truncate if too long
        if len(output) > 30000:
            output = output[:30000] + "\n... truncated"
        return output

    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {timeout}s"
    except Exception as e:
        return f"Error: {e}"


run_bash = Tool(
    name="run_bash",
    description="Execute a shell command in the project directory. Returns stdout, stderr, and exit code.",
    input_schema={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to execute"},
            "timeout": {"type": "integer", "description": "Timeout in seconds (default 120)"},
        },
        "required": ["command"],
    },
    handler=_handle_run_bash,
)

ALL_BASH_TOOLS = [run_bash]
