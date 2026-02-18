"""BaseAgent — Claude API conversation loop with streaming, thinking, and tool execution."""

from __future__ import annotations

import json
from dataclasses import dataclass

import anthropic

from aifw.agents.callbacks import AgentCallbacks, TurnStats
from aifw.tools.registry import ToolRegistry

# Pricing per million tokens (as of 2025)
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # (input_per_M, output_per_M)
    "claude-sonnet-4-20250514": (3.0, 15.0),
    "claude-sonnet-4-6-20250514": (3.0, 15.0),
    "claude-haiku-4-5-20251001": (0.80, 4.0),
    "claude-opus-4-6-20250514": (15.0, 75.0),
}


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    pricing = MODEL_PRICING.get(model, (3.0, 15.0))
    return (input_tokens * pricing[0] + output_tokens * pricing[1]) / 1_000_000


@dataclass
class AgentResult:
    success: bool
    final_text: str
    turns_used: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float
    stop_reason: str = ""


class BaseAgent:
    """Core agent: manages a Claude API conversation loop with tool execution."""

    def __init__(
        self,
        client: anthropic.Anthropic,
        model: str,
        system_prompt: str,
        tool_registry: ToolRegistry,
        tool_names: list[str] | None = None,
        callbacks: AgentCallbacks | None = None,
        max_turns: int = 50,
        thinking_budget: int = 4000,
    ):
        self.client = client
        self.model = model
        self.system_prompt = system_prompt
        self.tool_registry = tool_registry
        self.tool_names = tool_names
        self.callbacks = callbacks or AgentCallbacks()
        self.max_turns = max_turns
        self.thinking_budget = thinking_budget
        self.messages: list[dict] = []
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost_usd = 0.0

    def run(self, task_message: str) -> AgentResult:
        """Run the agent loop until completion or max turns."""
        self.messages.append({"role": "user", "content": task_message})

        tools = self.tool_registry.get_definitions(self.tool_names)
        final_text = ""

        for turn in range(self.max_turns):
            try:
                result = self._run_turn(tools, turn)
            except anthropic.APIError as e:
                self.callbacks.on_error(f"API error: {e}")
                return AgentResult(
                    success=False,
                    final_text=f"API error: {e}",
                    turns_used=turn + 1,
                    total_input_tokens=self.total_input_tokens,
                    total_output_tokens=self.total_output_tokens,
                    total_cost_usd=self.total_cost_usd,
                    stop_reason="error",
                )

            if result is not None:
                # Agent finished (end_turn with no tool_use)
                final_text = result
                self.callbacks.on_complete(final_text)
                return AgentResult(
                    success=True,
                    final_text=final_text,
                    turns_used=turn + 1,
                    total_input_tokens=self.total_input_tokens,
                    total_output_tokens=self.total_output_tokens,
                    total_cost_usd=self.total_cost_usd,
                    stop_reason="end_turn",
                )

        # Max turns reached
        self.callbacks.on_error(f"Max turns ({self.max_turns}) reached")
        return AgentResult(
            success=False,
            final_text="Max turns reached",
            turns_used=self.max_turns,
            total_input_tokens=self.total_input_tokens,
            total_output_tokens=self.total_output_tokens,
            total_cost_usd=self.total_cost_usd,
            stop_reason="max_turns",
        )

    def _run_turn(self, tools: list[dict], turn: int) -> str | None:
        """Run a single API call + tool execution turn.

        Returns the final text if the agent is done (no more tool calls),
        or None if the loop should continue.
        """
        # Build API call kwargs
        kwargs: dict = {
            "model": self.model,
            "max_tokens": 8192,
            "system": self.system_prompt,
            "messages": self.messages,
        }
        if tools:
            kwargs["tools"] = tools
        if self.thinking_budget > 0:
            # API requires budget_tokens >= 1024 and < max_tokens
            budget = max(self.thinking_budget, 1024)
            kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": budget,
            }

        # Streaming call
        collected_content: list[dict] = []
        final_text_parts: list[str] = []
        tool_use_blocks: list[dict] = []
        input_tokens = 0
        output_tokens = 0

        with self.client.messages.stream(**kwargs) as stream:
            current_block_type: str | None = None

            for event in stream:
                etype = event.type

                if etype == "content_block_start":
                    block = event.content_block
                    current_block_type = block.type
                    if block.type == "thinking":
                        self.callbacks.on_thinking_start()
                    elif block.type == "text":
                        self.callbacks.on_text_start()
                    elif block.type == "tool_use":
                        tool_use_blocks.append({
                            "id": block.id,
                            "name": block.name,
                            "input": {},
                            "_input_json": "",
                        })

                elif etype == "content_block_delta":
                    delta = event.delta
                    if hasattr(delta, "thinking") and delta.thinking:
                        self.callbacks.on_thinking_delta(delta.thinking)
                    elif hasattr(delta, "text") and delta.text:
                        self.callbacks.on_text_delta(delta.text)
                        final_text_parts.append(delta.text)
                    elif hasattr(delta, "partial_json") and delta.partial_json:
                        if tool_use_blocks:
                            tool_use_blocks[-1]["_input_json"] += delta.partial_json

                elif etype == "content_block_stop":
                    if current_block_type == "thinking":
                        self.callbacks.on_thinking_end()
                    elif current_block_type == "text":
                        self.callbacks.on_text_end()
                    elif current_block_type == "tool_use" and tool_use_blocks:
                        block_data = tool_use_blocks[-1]
                        try:
                            block_data["input"] = json.loads(
                                block_data["_input_json"]
                            ) if block_data["_input_json"] else {}
                        except json.JSONDecodeError:
                            block_data["input"] = {}
                        self.callbacks.on_tool_start(
                            block_data["name"], block_data["input"]
                        )
                    current_block_type = None

            # Get final message for usage stats
            response = stream.get_final_message()

        # Track tokens
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        cost = _estimate_cost(self.model, input_tokens, output_tokens)
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_cost_usd += cost

        self.callbacks.on_turn_end(TurnStats(
            turn=turn,
            max_turns=self.max_turns,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            total_cost_usd=self.total_cost_usd,
        ))

        # Build assistant message from response content
        assistant_content = []
        for block in response.content:
            if block.type == "thinking":
                assistant_content.append({
                    "type": "thinking",
                    "thinking": block.thinking,
                })
            elif block.type == "text":
                assistant_content.append({
                    "type": "text",
                    "text": block.text,
                })
            elif block.type == "tool_use":
                assistant_content.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })

        self.messages.append({"role": "assistant", "content": assistant_content})

        # If no tool calls, agent is done
        if not tool_use_blocks:
            return "".join(final_text_parts)

        # Execute tools and send results back
        tool_results = []
        for block_data in tool_use_blocks:
            # Find matching block from response for correct ID
            tool_id = block_data["id"]
            tool_name = block_data["name"]
            tool_input = block_data["input"]

            result = self.tool_registry.execute(tool_name, tool_input)
            self.callbacks.on_tool_result(tool_name, result)

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": result,
            })

        self.messages.append({"role": "user", "content": tool_results})
        return None  # Continue the loop
