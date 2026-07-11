"""Central logging configuration."""
from __future__ import annotations

import logging
import sys

_CONFIGURED = False


def setup_logging(level: str = "INFO") -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s  %(levelname)-7s  %(name)s: %(message)s",
                          datefmt="%H:%M:%S")
    )
    root = logging.getLogger()
    root.setLevel(level.upper())
    root.addHandler(handler)
    # Quiet noisy third-party loggers.
    for noisy in ("apscheduler", "urllib3", "praw", "prawcore", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
