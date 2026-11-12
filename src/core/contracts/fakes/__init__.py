"""Fake implementations of shared contracts."""

from src.core.contracts.fakes.llm import (
    FakeLLMClient,
    FakeModelsClient,
    FakeOCRClient,
)
from src.core.contracts.fakes.web import FakeWebAgent, FakeWebSearch

__all__ = [
    "FakeLLMClient",
    "FakeModelsClient",
    "FakeOCRClient",
    "FakeWebAgent",
    "FakeWebSearch",
]
