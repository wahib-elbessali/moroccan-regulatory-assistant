"""Service registry providing singleton dependency access for all contracts (00-shared §9)."""

import importlib
from collections.abc import Callable
from typing import Any, cast

from src.core.config import cfg
from src.core.contracts.protocols import (
    Audit,
    DocumentRights,
    Ingestion,
    LeakIndex,
    LLMClient,
    ModelsClient,
    Narrator,
    OCRClient,
    Orchestrator,
    Retrieval,
    WebAgent,
    WebSearch,
    Writer,
)

_instances: dict[str, Any] = {}
_overrides: dict[str, Any] = {}

_FACTORIES: dict[str, tuple[tuple[str, str], tuple[str, str]]] = {
    "retrieval": (
        ("src.core.contracts.fakes.retrieval", "FakeRetrieval"),
        ("src.retrieval", "real_retrieval"),
    ),
    "ingestion": (
        ("src.core.contracts.fakes.ingestion", "FakeIngestion"),
        ("src.ingestion", "real_ingestion"),
    ),
    "document_rights": (
        ("src.core.contracts.fakes.rights", "FakeDocumentRights"),
        ("src.core.db.rights", "real_document_rights"),
    ),
    "audit": (
        ("src.core.contracts.fakes.audit", "FakeAudit"),
        ("src.core.audit", "real_audit"),
    ),
    "llm": (
        ("src.core.contracts.fakes.llm", "FakeLLMClient"),
        ("src.core.llm", "real_llm"),
    ),
    "ocr": (
        ("src.core.contracts.fakes.llm", "FakeOCRClient"),
        ("src.core.llm", "real_ocr"),
    ),
    "models": (
        ("src.core.contracts.fakes.llm", "FakeModelsClient"),
        ("src.core.llm", "real_models"),
    ),
    "leak_index": (
        ("src.core.contracts.fakes.leak", "FakeLeakIndex"),
        ("src.core.leak", "real_leak_index"),
    ),
    "web_search": (
        ("src.core.contracts.fakes.web", "FakeWebSearch"),
        ("src.agents.web", "real_web_search"),
    ),
    "web_agent": (
        ("src.core.contracts.fakes.web", "FakeWebAgent"),
        ("src.agents.web", "real_web_agent"),
    ),
    "orchestrator": (
        ("src.core.contracts.fakes.orchestrator", "FakeOrchestrator"),
        ("src.agents.orchestrator", "real_orchestrator"),
    ),
    "writer": (
        ("src.core.contracts.fakes.answer", "FakeWriter"),
        ("src.agents.answer", "real_writer"),
    ),
    "narrator": (
        ("src.core.contracts.fakes.answer", "FakeNarrator"),
        ("src.agents.answer", "real_narrator"),
    ),
}


def override(name: str, instance: Any) -> None:
    """Replace a service instance for testing (00-shared §9)."""
    _overrides[name] = instance
    _instances[name] = instance


def reset() -> None:
    """Clear all cached and overridden service instances (00-shared §9)."""
    _overrides.clear()
    _instances.clear()


def _load_target(module_path: str, attr_name: str) -> Callable[[], Any]:
    module = importlib.import_module(module_path)
    factory = getattr(module, attr_name, None)
    if factory is None or not callable(factory):
        raise NotImplementedError(f"Factory '{module_path}:{attr_name}' is not implemented yet.")
    return cast(Callable[[], Any], factory)


def _get_service(name: str) -> Any:
    if name in _overrides:
        return _overrides[name]
    if name in _instances:
        return _instances[name]

    mode = getattr(cfg.contracts, name, "fake")
    fake_spec, real_spec = _FACTORIES[name]
    module_path, attr_name = real_spec if mode == "real" else fake_spec

    try:
        factory = _load_target(module_path, attr_name)
        instance = factory()
    except (ModuleNotFoundError, AttributeError) as err:
        raise NotImplementedError(
            f"Service '{name}' (mode={mode}) is not available yet ({module_path}:{attr_name})."
        ) from err

    _instances[name] = instance
    return instance


def get_retrieval() -> Retrieval:
    return cast(Retrieval, _get_service("retrieval"))


def get_ingestion() -> Ingestion:
    return cast(Ingestion, _get_service("ingestion"))


def get_document_rights() -> DocumentRights:
    return cast(DocumentRights, _get_service("document_rights"))


def get_audit() -> Audit:
    return cast(Audit, _get_service("audit"))


def get_llm() -> LLMClient:
    return cast(LLMClient, _get_service("llm"))


def get_ocr() -> OCRClient:
    return cast(OCRClient, _get_service("ocr"))


def get_models() -> ModelsClient:
    return cast(ModelsClient, _get_service("models"))


def get_leak_index() -> LeakIndex:
    return cast(LeakIndex, _get_service("leak_index"))


def get_web_search() -> WebSearch:
    return cast(WebSearch, _get_service("web_search"))


def get_web_agent() -> WebAgent:
    return cast(WebAgent, _get_service("web_agent"))


def get_orchestrator() -> Orchestrator:
    return cast(Orchestrator, _get_service("orchestrator"))


def get_writer() -> Writer:
    return cast(Writer, _get_service("writer"))


def get_narrator() -> Narrator:
    return cast(Narrator, _get_service("narrator"))
