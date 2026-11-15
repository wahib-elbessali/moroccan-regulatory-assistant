"""Fake of the ``Orchestrator`` Protocol (00-shared §6.5, §9).

Plays the same scenario every time: 3 ``thinking`` events, then one fixed ``answer``.
No ``done``: ``audited_stream`` (P5) adds it, because only it measures the latency.

Used by P5 (end-to-end with fakes), P7 (the chat screen) and the /ask route until the real
LangGraph orchestrator exists. Events and logs never contain the question (P3-23, P3-27).
"""

import asyncio
from collections.abc import AsyncIterator

from ..lang import detect_language
from ..models import Answer, Citation, UserContext

# Each text ends with "\n" so P7 can tell the steps apart (P3-25).
THINKING = {
    "fr": (
        "Je découpe la question.\n",
        "Je cherche dans les documents autorisés.\n",
        "Je rédige la réponse.\n",
    ),
    "ar": (
        "أقوم بتقسيم السؤال.\n",
        "أبحث في الوثائق المتاحة لك.\n",
        "أقوم بصياغة الجواب.\n",
    ),
}

_ANSWERS = {
    "fr": "Ceci est une réponse fictive du FakeOrchestrator [1].",
    "ar": "هذا جواب تجريبي من FakeOrchestrator [1].",
}


def _fixed_answer(language: str) -> Answer:
    """A valid Answer: marker [1] in the text, exactly one matching Citation (00-shared §5.5)."""
    return Answer(
        status="answered",
        text=_ANSWERS[language],
        citations=[
            Citation(
                doc_id="fake-doc",
                url=None,
                title="Document fictif",
                article="المادة 1",
                page=1,
                source=None,
                date=None,
                excerpt="Extrait fictif du document.",
            )
        ],
        confidence=0.9,
        language=language,
    )


class FakeOrchestrator:
    """``Orchestrator`` that ignores the question's content and plays a fixed scenario.

    Args:
        delay_s: Pause before each event. 0 in tests; set to 0.3 so P7 sees the stream arrive.
    """

    def __init__(self, *, delay_s: float = 0.0) -> None:
        self.delay_s = delay_s

    async def run(
        self, question: str, ctx: UserContext, use_web: bool = True
    ) -> AsyncIterator[dict]:
        language = detect_language(question)  # the question is only used for this
        for text in THINKING[language]:
            await self._pause()
            yield {"event": "thinking", "data": {"text": text}}
        await self._pause()
        yield {"event": "answer", "data": _fixed_answer(language).model_dump(mode="json")}

    async def _pause(self) -> None:
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
