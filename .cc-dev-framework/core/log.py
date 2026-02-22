"""日志模块 — 结构化日志输出到 main.log。

Usage:
    from log import setup_logging, get_logger
    setup_logging()
    logger = get_logger("main")
    logger.info("消息")
"""

from __future__ import annotations

import logging
from pathlib import Path

FRAMEWORK_DIR = Path(__file__).parent.parent  # .cc-dev-framework/
LOG_PATH = FRAMEWORK_DIR / "main.log"

_initialized = False


def setup_logging() -> None:
    """初始化日志。在 main.py 启动时调用一次。

    写入 .cc-dev-framework/main.log，mode='w'（每次运行清空）。
    格式: [2026-02-22 14:30:05] [INFO] main: 消息
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
