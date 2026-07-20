from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quant_lab import __version__

_AUDIT_FIELDS = (
    "request_id",
    "batch_id",
    "provider",
    "source_hash",
    "row_count",
    "accepted_count",
    "rejected_count",
    "warning_count",
    "error_category",
    "duration_ms",
)


class JsonFormatter(logging.Formatter):
    """Format an allow-listed subset of a log record as one JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": getattr(record, "event", record.name),
            "message": record.getMessage(),
            "application_version": __version__,
        }
        correlation_id = getattr(record, "correlation_id", None)
        if correlation_id is not None:
            payload["correlation_id"] = str(correlation_id)
        for field_name in _AUDIT_FIELDS:
            value = getattr(record, field_name, None)
            if value is not None:
                payload[field_name] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(level: str, log_file: Path | None = None) -> None:
    """Configure repeatable JSON logging for console and an optional local file."""

    root_logger = logging.getLogger()
    for logger_name, configured_logger in logging.root.manager.loggerDict.items():
        if (
            logger_name == "quant_lab" or logger_name.startswith("quant_lab.")
        ) and isinstance(configured_logger, logging.Logger):
            configured_logger.disabled = False
    for handler in list(root_logger.handlers):
        if getattr(handler, "_quant_lab_handler", False):
            root_logger.removeHandler(handler)
            handler.close()

    formatter = JsonFormatter()
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    stream_handler._quant_lab_handler = True  # type: ignore[attr-defined]
    root_logger.addHandler(stream_handler)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler._quant_lab_handler = True  # type: ignore[attr-defined]
        root_logger.addHandler(file_handler)

    root_logger.setLevel(level.upper())
