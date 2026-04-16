from __future__ import annotations

import logging
from pathlib import Path


def build_logger(name: str, level: str, log_path: str) -> logging.Logger:
    """Create a console + file logger for the strategy.

    Why this exists:
    Trading code is much easier to debug when every cycle writes to a file.
    That way, if something odd happens overnight, you can inspect the exact
    decision trail the next morning.
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper()))
    logger.handlers.clear()

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    log_file = Path(log_path)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger
