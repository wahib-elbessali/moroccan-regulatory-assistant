"""Service registry providing dependency access for all components (P5-04, P5-09b)."""

from typing import cast

from src.core.contracts.fakes.audit import FakeAudit
from src.core.contracts.fakes.rights import FakeDocumentRights
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

# Registry store for configured implementations or fakes
_registry: dict[str, object] = {
    "audit": FakeAudit(),
    "document_rights": FakeDocumentRights(),
}


def register_service(name: str, instance: object) -> None:
    """Register or override a service instance."""
    _registry[name] = instance


def get_audit() -> Audit:
    """Retrieve the configured Audit service."""
    if "audit" not in _registry:
        _registry["audit"] = FakeAudit()
    return cast(Audit, _registry["audit"])


def get_document_rights() -> DocumentRights:
    """Retrieve the configured DocumentRights service."""
    if "document_rights" not in _registry:
        _registry["document_rights"] = FakeDocumentRights()
    return cast(DocumentRights, _registry["document_rights"])


def get_ingestion() -> Ingestion:
    """Retrieve the configured Ingestion service."""
    return cast(Ingestion, _registry["ingestion"])


def get_retrieval() -> Retrieval:
    """Retrieve the configured Retrieval service."""
    return cast(Retrieval, _registry["retrieval"])


def get_orchestrator() -> Orchestrator:
    """Retrieve the configured Orchestrator service."""
    return cast(Orchestrator, _registry["orchestrator"])


def get_narrator() -> Narrator:
    """Retrieve the configured Narrator service."""
    return cast(Narrator, _registry["narrator"])


def get_writer() -> Writer:
    """Retrieve the configured Writer service."""
    return cast(Writer, _registry["writer"])


def get_web_agent() -> WebAgent:
    """Retrieve the configured WebAgent service."""
    return cast(WebAgent, _registry["web_agent"])


def get_web_search() -> WebSearch:
    """Retrieve the configured WebSearch service."""
    return cast(WebSearch, _registry["web_search"])


def get_leak_index() -> LeakIndex:
    """Retrieve the configured LeakIndex service."""
    return cast(LeakIndex, _registry["leak_index"])


def get_llm_client() -> LLMClient:
    """Retrieve the configured LLMClient service."""
    return cast(LLMClient, _registry["llm_client"])


def get_models_client() -> ModelsClient:
    """Retrieve the configured ModelsClient service."""
    return cast(ModelsClient, _registry["models_client"])


def get_ocr_client() -> OCRClient:
    """Retrieve the configured OCRClient service."""
    return cast(OCRClient, _registry["ocr_client"])
