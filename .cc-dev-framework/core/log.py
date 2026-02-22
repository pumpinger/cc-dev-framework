"""Logging module — structured log output to orchestrator.log.

Usage:
    from log import setup_logging, get_logger
    setup_logging()
    logger = get_logger("orchestrator")
    logger.info("消息")
"""

from __future__ import annotations

import logging
from pathlib import Path

FRAMEWORK_DIR = Path(__file__).parent.parent  # .cc-dev-framework/
LOG_PATH = FRAMEWORK_DIR / "orchestrator.log"

_initialized = False


def setup_logging() -> None:
    """Initialize logging. Call once at orchestrator startup.

    Writes to .cc-dev-framework/orchestrator.log, mode='w' (cleared each run).
    Format: [2026-02-22 14:30:05] [INFO] name: message
    """
    global _initialized
    if _initialized:
        return
    _initialized = True

    handler = logging.FileHandler(str(LOG_PATH), mode="w", encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Get a named logger."""
    return logging.getLogger(name)
