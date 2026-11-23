"""Contract, structured JSON logging (P5-03), and JWT secret resolution tests for P5."""

import json
import logging
from pathlib import Path
from uuid import uuid4

import jwt
import pytest
from pydantic import ValidationError

import src.core.config as config_mod
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
from src.core.security import create_access_token, decode_access_token, request_id_var

# ---------------------------------------------------------------------------
# P5-03 : Structured JSON Logging & single request_id_var
# ---------------------------------------------------------------------------


def test_json_formatter_outputs_event_request_id_and_extra(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verify JSONFormatter emits event, request_id (null outside requests), and extra fields."""
    logger = logging.getLogger("test.p5.contracts.logging")
    logger.setLevel(logging.INFO)
    logger.propagate = True
    caplog.handler.setFormatter(JSONFormatter())

    # 1. Outside a request: request_id must be present and null (None)
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

    # 2. Inside a request: request_id reflects request_id_var from security.py
    rid = uuid4()
    token = request_id_var.set(rid)
    try:
        logger.info("http_request", extra={"method": "GET", "status_code": 200})
    finally:
        request_id_var.reset(token)

    line_inside = json.loads(caplog.text.strip().splitlines()[-1])
    assert line_inside["event"] == "http_request"
    assert line_inside["request_id"] == str(rid)
    assert line_inside["method"] == "GET"
    assert line_inside["status_code"] == 200


# ---------------------------------------------------------------------------
# P5-15 & P5-16 : JWT Secret Resolution (.env fallback when os.getenv is None)
# ---------------------------------------------------------------------------


def test_jwt_create_and_decode_from_dotenv_when_env_var_unset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure JWT create/decode works when JWT_SECRET comes solely from .env."""
    dotenv_file = tmp_path / ".env"
    dotenv_file.write_text(
        "POSTGRES_PASSWORD=dotenv-pg-pass\n"
        "JWT_SECRET=dotenv-only-secret-key-at-least-32-chars\n"
        "ADMIN_USERNAME=admin\n"
        "ADMIN_PASSWORD=dotenv-admin-pass\n",
        encoding="utf-8",
    )

    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config_mod.cfg, "_instance", None)

    uid = str(uuid4())
    token = create_access_token({"sub": uid})
    payload = decode_access_token(token)
    assert payload["sub"] == uid


def test_jwt_decode_rejects_tampered_token() -> None:
    token = create_access_token({"sub": str(uuid4())})
    tampered = f"{token}corrupted"
    with pytest.raises(jwt.PyJWTError):
        decode_access_token(tampered)


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
        "mode: light\n" "retrieval:\n" "  top_k_final: 5\n" "  rerank_top_n: 15\n",
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
