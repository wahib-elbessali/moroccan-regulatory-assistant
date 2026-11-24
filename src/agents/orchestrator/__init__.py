from src.agents.orchestration_support.orchestration_limits import audit_configured_limits
from src.agents.orchestrator.real import RealOrchestrator


def real_orchestrator() -> RealOrchestrator:
    audit_configured_limits()
    return RealOrchestrator()
