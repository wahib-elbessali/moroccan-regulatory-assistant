"""Fake implementations for LLM, OCR and embedding/reranking contracts."""

from __future__ import annotations

import hashlib
import math
import re
from collections import deque
from collections.abc import AsyncIterator, Sequence

from src.core.contracts.protocols import (
    LLMClient,
    ModelsClient,
    OCRClient,
)


class FakeLLMClient(LLMClient):
    """Deterministic fake LLM client for contract tests."""

    def __init__(
        self,
        replies: Sequence[str] | None = None,
        default_reply: str = "Fake LLM response.",
    ) -> None:
        self._replies = deque(replies or [])
        self._default_reply = default_reply

    def _next_reply(self) -> str:
        if self._replies:
            return self._replies.popleft()
        return self._default_reply

    def chat(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.0,
    ) -> str:
        """Return the next configured response."""
        return self._next_reply()

    async def stream(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """Yield the next response word by word."""
        reply = self._next_reply()

        words = reply.split()
        for index, word in enumerate(words):
            suffix = " " if index < len(words) - 1 else ""
            yield word + suffix

    def count_tokens(self, text: str) -> int:
        """Use word count as a deterministic token-count approximation."""
        return len(text.split())


class FakeOCRClient(OCRClient):
    """Deterministic fake OCR client."""

    DEFAULT_TEXT = "هذا نص تجريبي مستخرج من وثيقة إدارية مغربية."

    def ocr_page(
        self,
        image: bytes,
        lang: str = "ar",
    ) -> tuple[str, float]:
        """Return a fixed Arabic text and confidence score."""
        return self.DEFAULT_TEXT, 0.9


class FakeModelsClient(ModelsClient):
    """Deterministic fake embeddings and reranking client."""

    EMBEDDING_DIMENSION = 1024

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        return set(re.findall(r"\w+", text.casefold()))

    @classmethod
    def _embedding(cls, text: str) -> list[float]:
        """Generate a stable, normalized vector from the input text."""
        raw = hashlib.shake_256(text.encode("utf-8")).digest(
            cls.EMBEDDING_DIMENSION * 4
        )

        vector: list[float] = []

        for index in range(cls.EMBEDDING_DIMENSION):
            offset = index * 4
            value = int.from_bytes(
                raw[offset : offset + 4],
                byteorder="big",
                signed=False,
            )

            normalized_value = (value / (2**32 - 1)) * 2.0 - 1.0
            vector.append(normalized_value)

        norm = math.sqrt(sum(value * value for value in vector))

        if norm == 0.0:
            return vector

        return [value / norm for value in vector]

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one deterministic 1024-dimensional vector per text."""
        return [self._embedding(text) for text in texts]

    def rerank(self, query: str, texts: list[str]) -> list[float]:
        """Score texts using deterministic word overlap."""
        query_tokens = self._tokenize(query)

        if not query_tokens:
            return [0.0 for _ in texts]

        scores: list[float] = []

        for text in texts:
            text_tokens = self._tokenize(text)
            overlap = query_tokens.intersection(text_tokens)
            score = len(overlap) / len(query_tokens)
            scores.append(float(score))

        return scores
