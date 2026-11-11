
"""Fake implementations of shared contracts."""

from src.core.contracts.fakes.llm import (
    FakeLLMClient,
    FakeModelsClient,
    FakeOCRClient,
)

__all__ = [
    "FakeLLMClient",
    "FakeModelsClient",
    "FakeOCRClient",
]
