from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger


def setup_logging(level: str = "INFO") -> None:
    """Настройка loguru с выводом в stdout и файл логов."""
    logs_dir = Path.cwd() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    logger.remove()
    logger.add(
        sys.stdout,
        level=level.upper(),
        colorize=True,
        backtrace=False,
        diagnose=False,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | {file}:{line} | {function} | {message}",
    )
    logger.add(
        logs_dir / "bot.log",
        level=level.upper(),
        rotation="10 MB",
        retention="7 days",
        enqueue=True,
        compression="zip",
        backtrace=True,
        diagnose=False,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
    )

