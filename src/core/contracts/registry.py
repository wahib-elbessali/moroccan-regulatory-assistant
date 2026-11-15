"""Registre des services (00-shared §9).

Chaque `get_*()` lit `cfg.contracts.<nom>` ("fake" ou "real") dans config.yaml et garde UNE instance
par processus. `override(nom, instance)` et `reset()` servent aux tests.

Un service dont l'implémentation n'existe pas encore (module absent) lève `NotImplementedError`
avec un message clair, jamais un KeyError.
"""

import importlib
import threading
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

# nom -> ((module du fake, classe), (module du réel, fabrique))
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

_instances: dict[str, Any] = {}  # une instance par processus (cache ou override)
_lock = threading.RLock()  # RLock : un fake peut appeler le registre pendant sa construction


def override(name: str, instance: Any) -> None:
    """Remplace un service (tests). Reste actif jusqu'à `reset()`."""
    with _lock:
        _instances[name] = instance


def reset() -> None:
    """Oublie toutes les instances et tous les remplacements."""
    with _lock:
        _instances.clear()


def _fake_kwargs(name: str) -> dict[str, Any]:
    """Réglages de config.yaml transmis au constructeur d'un fake (seulement en mode fake)."""
    if name == "retrieval":
        return {
            "data_dir": cfg.fakes.data_dir,
            "top_k_final": cfg.retrieval.top_k_final,
            "rerank_top_n": cfg.retrieval.rerank_top_n,
        }
    return {}


def _load(module_path: str, attr_name: str) -> Callable[..., Any]:
    """Importe la fabrique. `NotImplementedError` seulement si le module visé n'existe pas encore."""
    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError as err:
        # Un module absent À L'INTÉRIEUR du code de l'autre partie (dépendance manquante) reste
        # une vraie erreur : on ne la déguise pas en "pas encore disponible".
        if err.name is None or not (
            module_path == err.name or module_path.startswith(err.name + ".")
        ):
            raise
        raise NotImplementedError(f"{module_path} n'existe pas encore") from err
    factory = getattr(module, attr_name, None)
    if not callable(factory):
        raise NotImplementedError(f"{module_path}:{attr_name} n'existe pas encore")
    return cast(Callable[..., Any], factory)


def _get_service(name: str) -> Any:
    with _lock:
        if name in _instances:
            return _instances[name]

        mode = cfg.contracts.get(name, "fake")  # contracts est un dict (config.py)
        fake_spec, real_spec = _FACTORIES[name]
        module_path, attr_name = real_spec if mode == "real" else fake_spec

        try:
            factory = _load(module_path, attr_name)
        except NotImplementedError as err:
            raise NotImplementedError(
                f"Service '{name}' (mode={mode}) indisponible : {err}"
            ) from err

        instance = factory(**_fake_kwargs(name)) if mode != "real" else factory()
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
