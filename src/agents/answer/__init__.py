"""P4 answer-generation agents."""

from src.core.contracts.protocols import Writer


def real_writer() -> Writer:
    """Build P4's real writer without loading it while the shared fake is imported."""
    from src.agents.answer.writer import RealWriter

    return RealWriter()


__all__ = ["real_writer"]
