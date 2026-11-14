"""Tests for structured JSON logging (P5-03) and JWT secret resolution."""

import json
import logging

from src.core.logging import JSONFormatter
from src.core.security import create_access_token, decode_access_token, request_id_var


def test_json_formatter_includes_event_request_id_and_extra(caplog) -> None:
    logger = logging.getLogger("test.p5.json_formatter")
    logger.setLevel(logging.INFO)
    logger.propagate = True

    caplog.handler.setFormatter(JSONFormatter())

    # 1. Outside a request: request_id must be present and null (None)
    assert request_id_var.get() is None
    logger.info("x", extra={"a": 1})

    record_outside = json.loads(caplog.text.strip().splitlines()[-1])
    assert record_outside["event"] == "x"
    assert "message" not in record_outside
    assert "request_id" in record_outside
    assert record_outside["request_id"] is None
    assert record_outside["a"] == 1
    assert "timestamp" in record_outside
    assert record_outside["level"] == "INFO"

    # 2. Inside a request context: request_id reflects request_id_var
    token = request_id_var.set("req-123")
    try:
        logger.info("y", extra={"user": "alice"})
    finally:
        request_id_var.reset(token)

    record_inside = json.loads(caplog.text.strip().splitlines()[-1])
    assert record_inside["event"] == "y"
    assert record_inside["request_id"] == "req-123"
    assert record_inside["user"] == "alice"


def test_jwt_create_and_decode_use_same_secret() -> None:
    token = create_access_token({"sub": "00000000-0000-0000-0000-000000000001"})
    payload = decode_access_token(token)
    assert payload["sub"] == "00000000-0000-0000-0000-000000000001"
