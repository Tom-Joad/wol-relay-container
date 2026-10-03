"""Structured (JSON lines) logging to stdout.

Every record carries a timestamp (local time per TZ, with offset), a level
and a short event name. Secrets are never passed to the logger: the auth token is compared but never logged,
and request bodies are not echoed.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime

_RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__)


class JsonFormatter(logging.Formatter):
    """Render a log record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            # Local time with UTC offset; TZ selects the zone, UTC prints as Z.
            "ts": datetime.fromtimestamp(record.created)
            .astimezone()
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "event": record.getMessage(),
        }

        # Anything passed via logger.info(..., extra={...}) becomes a field.
        for key, value in record.__dict__.items():
            if key not in _RESERVED and key not in payload and not key.startswith("_"):
                payload[key] = value

        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info).splitlines()[-1]

        return json.dumps(payload, separators=(",", ":"), default=str)


def configure(level: str = "INFO") -> None:
    """Install the JSON formatter as the only stdout handler."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
