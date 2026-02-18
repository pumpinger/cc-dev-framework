"""Terminal UI callbacks — rich real-time output for agent execution."""

from __future__ import annotations

import json
import sys

from aifw.agents.callbacks import AgentCallbacks, TurnStats
from aifw.config import DisplayConfig

# ANSI colors
DIM = "\033[2m"
RESET = "\033[0m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
RED = "\033[31m"
MAGENTA = "\033[35m"
BOLD = "\033[1m"


class TerminalCallbacks(AgentCallbacks):
    """Renders agent events to the terminal with colors and streaming."""

    def __init__(self, config: DisplayConfig):
        self.config = config
        self._in_thinking = False
        self._in_text = False

    def on_thinking_start(self) -> None:
        if not self.config.show_thinking:
            return
        self._in_thinking = True
        sys.stdout.write(f"\n{DIM}{YELLOW}  thinking: ")
        sys.stdout.flush()

    def on_thinking_delta(self, text: str) -> None:
        if not self.config.show_thinking:
            return
        if self.config.streaming:
            sys.stdout.write(text)
            sys.stdout.flush()

    def on_thinking_end(self) -> None:
        if not self.config.show_thinking:
            return
        self._in_thinking = False
        sys.stdout.write(f"{RESET}\n")
        sys.stdout.flush()

    def on_text_start(self) -> None:
        self._in_text = True
        sys.stdout.write(f"\n{CYAN}  agent: {RESET}")
        sys.stdout.flush()

    def on_text_delta(self, text: str) -> None:
        if self.config.streaming:
            sys.stdout.write(text)
            sys.stdout.flush()

    def on_text_end(self) -> None:
        self._in_text = False
        sys.stdout.write("\n")
        sys.stdout.flush()

    def on_tool_start(self, name: str, tool_input: dict) -> None:
        if not self.config.show_tool_calls:
            return
        sys.stdout.write(f"\n{MAGENTA}  tool: {name}{RESET}")
        if self.config.verbosity == "verbose":
            formatted = json.dumps(tool_input, indent=2, ensure_ascii=False)
            for line in formatted.splitlines():
                sys.stdout.write(f"\n{DIM}    {line}{RESET}")
        elif tool_input:
            # Show key params briefly
            brief = _brief_params(name, tool_input)
            if brief:
                sys.stdout.write(f" {DIM}({brief}){RESET}")
        sys.stdout.write("\n")
        sys.stdout.flush()

    def on_tool_result(self, name: str, result: str) -> None:
        if not self.config.show_tool_results:
            return
        if self.config.verbosity == "verbose":
            lines = result.splitlines()
            preview = lines[:20]
            sys.stdout.write(f"{DIM}")
            for line in preview:
                sys.stdout.write(f"    | {line}\n")
            if len(lines) > 20:
                sys.stdout.write(f"    ... ({len(lines)} lines total)\n")
            sys.stdout.write(f"{RESET}")
        elif self.config.verbosity == "normal":
            lines = result.splitlines()
            n = len(lines)
            preview = result[:120].replace("\n", " ")
            sys.stdout.write(f"{DIM}    -> {preview}")
            if n > 1 or len(result) > 120:
                sys.stdout.write(f" ... ({n} lines)")
            sys.stdout.write(f"{RESET}\n")
        sys.stdout.flush()

    def on_turn_end(self, stats: TurnStats) -> None:
        if self.config.verbosity == "quiet":
            return
        bar_width = 20
        filled = int(bar_width * (stats.turn + 1) / stats.max_turns)
        bar = "=" * filled + "-" * (bar_width - filled)
        sys.stdout.write(
            f"{DIM}  [{bar}] turn {stats.turn + 1}/{stats.max_turns}"
            f" | tokens: {stats.input_tokens}in/{stats.output_tokens}out"
            f" | ${stats.cost_usd:.3f} (total: ${stats.total_cost_usd:.3f})"
            f"{RESET}\n"
        )
        sys.stdout.flush()

    def on_error(self, error: str) -> None:
        sys.stdout.write(f"\n{RED}{BOLD}  error: {error}{RESET}\n")
        sys.stdout.flush()

    def on_complete(self, final_text: str) -> None:
        sys.stdout.write(f"\n{GREEN}{BOLD}  done.{RESET}\n")
        sys.stdout.flush()


def _brief_params(tool_name: str, inp: dict) -> str:
    """Extract the most relevant parameter for brief display."""
    if "path" in inp:
        return inp["path"]
    if "command" in inp:
        cmd = inp["command"]
        return cmd[:60] + "..." if len(cmd) > 60 else cmd
    if "pattern" in inp:
        return inp["pattern"]
    if "message" in inp:
        msg = inp["message"]
        return msg[:60] + "..." if len(msg) > 60 else msg
    if "branch" in inp:
        return inp["branch"]
    if "feature_id" in inp:
        return f"{inp['feature_id']}:{inp.get('action', '')}"
    return ""
