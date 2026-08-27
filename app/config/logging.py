"""Logging configuration.

Security rule: never log document contents, API keys, tokens, or raw file
paths that could leak into shared log aggregators. A redaction filter blocks
common secret-looking substrings before they reach any handler.
"""

from __future__ import annotations

import logging
import re
import sys

_SECRET_PATTERNS = [
    re.compile(r"(?i)(bot_token|api[_-]?key|authorization)\s*[:=]\s*\S+"),
    re.compile(r"\d{6,}:[A-Za-z0-9_-]{30,}"),  # Telegram bot token shape
]

_REDACTED = "[REDACTED]"


class RedactingFilter(logging.Filter):
    """Scrubs likely secrets out of log records before they are emitted."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        redacted = message
        for pattern in _SECRET_PATTERNS:
            redacted = pattern.sub(_REDACTED, redacted)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    handler.addFilter(RedactingFilter())
    root.addHandler(handler)

    # Silence noisy third-party loggers at DEBUG level.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
