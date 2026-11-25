"""``CONTRACT_<NAME>`` environment variables override ``contracts`` from config.yaml."""

import logging
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api import main
from src.core.config import contract_overrides, load_config, log_contract_overrides


@pytest.fixture
def config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("POSTGRES_PASSWORD", "test-postgres-pw")
    monkeypatch.setenv("JWT_SECRET", "s" * 32)
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-admin-pw")
    for key in list(os.environ):
        if key.upper().startswith("CONTRACT_"):
            monkeypatch.delenv(key)
    path = tmp_path / "config.yaml"
    path.write_text("contracts:\n  llm: fake\n  models: fake\n  ocr: fake\n", encoding="utf-8")
    return path


def test_without_env_the_yaml_values_are_kept(config_file: Path) -> None:
    assert load_config(config_file).contracts == {"llm": "fake", "models": "fake", "ocr": "fake"}


def test_env_sets_one_contract_to_real(config_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTRACT_LLM", "real")
    contracts = load_config(config_file).contracts
    assert contracts == {"llm": "real", "models": "fake", "ocr": "fake"}


def test_env_can_add_a_contract_missing_from_yaml(
    config_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CONTRACT_LEAK_INDEX", "Real")
    assert load_config(config_file).contracts["leak_index"] == "real"


def test_env_with_a_bad_value_is_refused(
    config_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CONTRACT_LLM", "maybe")
    with pytest.raises(ValueError, match="fake' ou 'real"):
        load_config(config_file)


def test_unrelated_and_bare_prefix_variables_are_ignored() -> None:
    env = {"CONTRACT_": "real", "CONTRACTS": "real", "PATH": "/bin", "CONTRACT_OCR": "real"}
    assert contract_overrides(env) == {"ocr": "real"}


def test_overrides_are_logged_in_one_warning(
    config_file: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("CONTRACT_OCR", "real")
    monkeypatch.setenv("CONTRACT_LLM", "fake")
    with caplog.at_level(logging.WARNING, logger="test_overrides"):
        log_contract_overrides(logging.getLogger("test_overrides"))
    assert [(r.levelname, r.getMessage()) for r in caplog.records] == [
        ("WARNING", "contracts overridden from the environment: llm=fake, ocr=real")
    ]


def test_nothing_is_logged_without_overrides(
    config_file: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="test_overrides"):
        log_contract_overrides(logging.getLogger("test_overrides"))
    assert caplog.records == []


def test_the_api_logs_the_overrides_once_when_it_starts(
    config_file: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("CONTRACT_LLM", "fake")
    monkeypatch.setattr(main, "init_db", lambda: None)
    with caplog.at_level(logging.WARNING, logger="rag_api"), TestClient(main.app) as client:
        client.get("/health")
        client.get("/health")
    logged = [r.getMessage() for r in caplog.records if "overridden" in r.getMessage()]
    assert logged == ["contracts overridden from the environment: llm=fake"]
