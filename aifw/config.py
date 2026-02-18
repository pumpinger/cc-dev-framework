"""Configuration loading and validation."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class ModelConfig:
    initializer: str = "claude-sonnet-4-6-20250514"
    coder: str = "claude-sonnet-4-6-20250514"
    verifier: str = "claude-haiku-4-5-20251001"


@dataclass
class LimitsConfig:
    max_turns_per_feature: int = 50
    max_total_cost_usd: float = 10.0
    bash_timeout_seconds: int = 120


@dataclass
class DisplayConfig:
    show_thinking: bool = True
    show_tool_calls: bool = True
    show_tool_results: bool = True
    streaming: bool = True
    verbosity: str = "normal"  # quiet | normal | verbose


@dataclass
class Config:
    api_key: str = ""
    model: ModelConfig = field(default_factory=ModelConfig)
    limits: LimitsConfig = field(default_factory=LimitsConfig)
    display: DisplayConfig = field(default_factory=DisplayConfig)

    @staticmethod
    def load(config_path: Path | None = None) -> Config:
        """Load config from YAML file, with environment variable overrides."""
        raw: dict = {}

        # Try loading from file
        if config_path and config_path.exists():
            with open(config_path) as f:
                raw = yaml.safe_load(f) or {}

        # Resolve API key: env var takes precedence
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        raw_key = raw.get("api_key", "")
        if raw_key and not raw_key.startswith("${"):
            api_key = raw_key
        if not api_key:
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")

        # Build sub-configs
        model_raw = raw.get("model", {})
        model = ModelConfig(
            initializer=model_raw.get("initializer", ModelConfig.initializer),
            coder=model_raw.get("coder", ModelConfig.coder),
            verifier=model_raw.get("verifier", ModelConfig.verifier),
        )

        limits_raw = raw.get("limits", {})
        limits = LimitsConfig(
            max_turns_per_feature=limits_raw.get(
                "max_turns_per_feature", LimitsConfig.max_turns_per_feature
            ),
            max_total_cost_usd=limits_raw.get(
                "max_total_cost_usd", LimitsConfig.max_total_cost_usd
            ),
            bash_timeout_seconds=limits_raw.get(
                "bash_timeout_seconds", LimitsConfig.bash_timeout_seconds
            ),
        )

        display_raw = raw.get("display", {})
        display = DisplayConfig(
            show_thinking=display_raw.get(
                "show_thinking", DisplayConfig.show_thinking
            ),
            show_tool_calls=display_raw.get(
                "show_tool_calls", DisplayConfig.show_tool_calls
            ),
            show_tool_results=display_raw.get(
                "show_tool_results", DisplayConfig.show_tool_results
            ),
            streaming=display_raw.get("streaming", DisplayConfig.streaming),
            verbosity=display_raw.get("verbosity", DisplayConfig.verbosity),
        )

        return Config(api_key=api_key, model=model, limits=limits, display=display)

    def validate(self) -> list[str]:
        """Return list of validation errors, empty if config is valid."""
        errors = []
        if not self.api_key:
            errors.append(
                "API key not set. Set ANTHROPIC_API_KEY env var or api_key in config.yaml"
            )
        if self.limits.max_turns_per_feature < 1:
            errors.append("max_turns_per_feature must be >= 1")
        if self.limits.max_total_cost_usd <= 0:
            errors.append("max_total_cost_usd must be > 0")
        if self.display.verbosity not in ("quiet", "normal", "verbose"):
            errors.append(
                f"Invalid verbosity: {self.display.verbosity}. Must be quiet|normal|verbose"
            )
        return errors
