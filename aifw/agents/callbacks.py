"""Callback interfaces for agent observability."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TurnStats:
    turn: int
    max_turns: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    total_cost_usd: float


class AgentCallbacks:
    """Base callback interface. Override methods to handle agent events."""

    def on_thinking_start(self) -> None:
        pass

    def on_thinking_delta(self, text: str) -> None:
        pass

    def on_thinking_end(self) -> None:
        pass

    def on_text_start(self) -> None:
        pass

    def on_text_delta(self, text: str) -> None:
        pass

    def on_text_end(self) -> None:
        pass

    def on_tool_start(self, name: str, tool_input: dict) -> None:
        pass

    def on_tool_result(self, name: str, result: str) -> None:
        pass

    def on_turn_end(self, stats: TurnStats) -> None:
        pass

    def on_error(self, error: str) -> None:
        pass

    def on_complete(self, final_text: str) -> None:
        pass
