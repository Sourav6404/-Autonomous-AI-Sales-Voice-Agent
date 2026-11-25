"""Structured logging configuration for FortiSales AI."""

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Dict


SENSITIVE_KEY_SUBSTRINGS = (
    "password",
    "token",
    "secret",
    "authorization",
    "api_key",
    "credit_card",
)


def sanitize_payload(obj: Any) -> Any:
    """Recursively redacts sensitive keys from log payloads."""
    if isinstance(obj, dict):
        sanitized = {}
        for k, v in obj.items():
            if any(sub in str(k).lower() for sub in SENSITIVE_KEY_SUBSTRINGS):
                sanitized[k] = "***REDACTED***"
            else:
                sanitized[k] = sanitize_payload(v)
        return sanitized
    elif isinstance(obj, (list, tuple)):
        return [sanitize_payload(item) for item in obj]
    return obj


class JSONFormatter(logging.Formatter):
    """Custom JSON log formatter for production observability."""

    def format(self, record: logging.LogRecord) -> str:
        log_payload: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "line": record.lineno,
        }
        if record.exc_info:
            log_payload["exception"] = self.formatException(record.exc_info)
        if hasattr(record, "extra") and isinstance(record.extra, dict):
            log_payload.update(sanitize_payload(record.extra))
        return json.dumps(log_payload)


def setup_logging(log_level: str = "INFO", log_format: str = "json") -> None:
    """Configures root and application loggers."""
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level.upper())

    # Remove existing handlers to avoid duplicates
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    if log_format.lower() == "json":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "[%(asctime)s] [%(levelname)s] [%(name)s:%(lineno)d]: %(message)s"
            )
        )

    root_logger.addHandler(handler)

    # Quiet overly chatty loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


logger = logging.getLogger("fortisales")


def get_logger(name: str = "fortisales") -> logging.Logger:
    """Convenience helper to obtain a named logger."""
    return logging.getLogger(name)
