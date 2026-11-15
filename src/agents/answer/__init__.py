"""P4 answer-generation agents."""

from src.core.contracts.protocols import Narrator, Writer


def real_writer() -> Writer:
    """Build P4's real writer without loading it while the shared fake is imported."""
    from src.agents.answer.writer import RealWriter

    return RealWriter()


def real_narrator() -> Narrator:
    """Build P4's real narrator without loading it while the shared fake is imported."""
    from src.agents.answer.narrator import real_narrator as create_real_narrator

    return create_real_narrator()


__all__ = ["real_narrator", "real_writer"]
