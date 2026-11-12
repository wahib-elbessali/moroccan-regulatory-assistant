"""Structured JSON logging configuration with request_id contextualization."""

import json
import logging
import sys
from contextvars import ContextVar
from typing import Any
from uuid import UUID

request_id_ctx_var: ContextVar[UUID | None] = ContextVar("request_id", default=None)


class JSONFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        log_obj: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        req_id = request_id_ctx_var.get()
        if req_id is not None:
            log_obj["request_id"] = str(req_id)
        elif hasattr(record, "request_id"):
            log_obj["request_id"] = str(record.request_id)

        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_obj, ensure_ascii=False)


def setup_logging(level: str = "INFO") -> None:
    """Configure the root logger with the JSONFormatter."""
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers to avoid duplicates
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root_logger.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Retrieve a configured logger by name."""
    return logging.getLogger(name)
