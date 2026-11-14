"""Contract and architectural invariant tests for P5 (config, logging, errors, audit)."""

import json
import logging
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.core.config import AppConfig, load_config
from src.core.contracts.enums import AccountRequestStatus, AuditAction
from src.core.contracts.errors import (
    AppError,
    Conflict,
    Forbidden,
    InvalidInput,
    NotFound,
    TooManyRequests,
    Unauthenticated,
)
from src.core.logging import JSONFormatter
from src.core.security import request_id_var

# ---------------------------------------------------------------------------
# P5-04 : Configuration (.env secrets vs config.yaml)
# ---------------------------------------------------------------------------


def test_load_config_valid_yaml_and_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_PASSWORD", "test-postgres-pw")
    monkeypatch.setenv("JWT_SECRET", "s" * 32)
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-admin-pw")
    monkeypatch.delenv("CI_POSTGRES_URL", raising=False)

    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "mode: light\n"
        "retrieval:\n"
        "  top_k_final: 5\n"
        "  rerank_top_n: 15\n"
        "custom_extra_section:\n"
        "  foo: bar\n",
        encoding="utf-8",
    )

    loaded = load_config(cfg_file)
    assert loaded.mode == "light"
    assert loaded.retrieval.top_k_final == 5
    assert loaded.retrieval.rerank_top_n == 15
    assert "postgresql+psycopg://postgres:test-postgres-pw@" in loaded.database_url


def test_load_config_forbids_secrets_in_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("POSTGRES_PASSWORD", "test-postgres-pw")
    monkeypatch.setenv("JWT_SECRET", "s" * 32)
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-admin-pw")

    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("JWT_SECRET: leaked-in-yaml\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Secrets interdits"):
        load_config(cfg_file)


def test_app_config_rejects_short_jwt_secret_outside_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CI_POSTGRES_URL", raising=False)
    with pytest.raises(ValidationError, match="32"):
        AppConfig(
            _env_file=None,  # type: ignore[call-arg]
            POSTGRES_PASSWORD="pw",  # type: ignore[arg-type]
            JWT_SECRET="short-secret",  # type: ignore[arg-type]
            ADMIN_USERNAME="admin",
            ADMIN_PASSWORD="admin-pw",  # type: ignore[arg-type]
        )


def test_app_config_rejects_invalid_retrieval_bounds() -> None:
    with pytest.raises(ValidationError, match="top_k_final"):
        AppConfig(
            _env_file=None,  # type: ignore[call-arg]
            POSTGRES_PASSWORD="pw",  # type: ignore[arg-type]
            JWT_SECRET="s" * 32,  # type: ignore[arg-type]
            ADMIN_USERNAME="admin",
            ADMIN_PASSWORD="admin-pw",  # type: ignore[arg-type]
            CI_POSTGRES_URL="postgresql://postgres:pw@localhost:5432/rag",
            retrieval={"top_k_final": 25, "rerank_top_n": 10},  # type: ignore[arg-type]
        )


def test_app_config_rejects_invalid_contract_mode() -> None:
    with pytest.raises(ValidationError, match="contracts"):
        AppConfig(
            _env_file=None,  # type: ignore[call-arg]
            POSTGRES_PASSWORD="pw",  # type: ignore[arg-type]
            JWT_SECRET="s" * 32,  # type: ignore[arg-type]
            ADMIN_USERNAME="admin",
            ADMIN_PASSWORD="admin-pw",  # type: ignore[arg-type]
            CI_POSTGRES_URL="postgresql://postgres:pw@localhost:5432/rag",
            contracts={"audit": "mock"},
        )


# ---------------------------------------------------------------------------
# P5-03 : Structured JSON Logging & single request_id_var
# ---------------------------------------------------------------------------


def test_json_formatter_outputs_event_request_id_and_extra(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("test.p5.contracts.logging")
    logger.setLevel(logging.INFO)
    logger.propagate = True
    caplog.handler.setFormatter(JSONFormatter())

    # Outside a request: request_id must be present and null
    assert request_id_var.get() is None
    logger.info("x", extra={"a": 1})

    line_outside = json.loads(caplog.text.strip().splitlines()[-1])
    assert line_outside["event"] == "x"
    assert "message" not in line_outside
    assert "request_id" in line_outside
    assert line_outside["request_id"] is None
    assert line_outside["a"] == 1
    assert line_outside["level"] == "INFO"
    assert "timestamp" in line_outside

    # Inside a request: request_id reflects request_id_var
    rid = uuid4()
    token = request_id_var.set(rid)
    try:
        logger.info("request_event", extra={"status_code": 200})
    finally:
        request_id_var.reset(token)

    line_inside = json.loads(caplog.text.strip().splitlines()[-1])
    assert line_inside["event"] == "request_event"
    assert line_inside["request_id"] == str(rid)
    assert line_inside["status_code"] == 200


# ---------------------------------------------------------------------------
# P5-05 & Enums : Domain Error HTTP statuses and Enum contracts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("exc", "expected_status", "expected_code"),
    [
        (InvalidInput("bad input"), 422, "invalid_input"),
        (Unauthenticated("not logged in"), 401, "unauthenticated"),
        (Forbidden("denied"), 403, "forbidden"),
        (NotFound("missing"), 404, "not_found"),
        (Conflict("duplicate"), 409, "conflict"),
        (TooManyRequests("slow down"), 429, "too_many_requests"),
    ],
)
def test_domain_errors_http_mapping(
    exc: AppError, expected_status: int, expected_code: str
) -> None:
    assert exc.http_status == expected_status
    assert exc.code == expected_code


def test_p5_enums_values() -> None:
    assert AccountRequestStatus.PENDING.value == "pending"
    assert AccountRequestStatus.APPROVED.value == "approved"
    assert AccountRequestStatus.REJECTED.value == "rejected"
    assert AuditAction.LOGIN.value == "login"
