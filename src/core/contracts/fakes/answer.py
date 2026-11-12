"""Fakes for P4's Writer and Narrator contracts (00-shared §6.6, §9)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable

from src.agents.answer.narration_templates import render_template
from src.agents.answer.texts import UNKNOWN, WEB_ONLY
from src.core.contracts.enums import AnswerStatus, StepType
from src.core.contracts.lang import detect_language
from src.core.contracts.models import (
    Answer,
    Citation,
    Passage,
    ProcessEvent,
    UserContext,
    WebResult,
)
from src.core.contracts.protocols import Narrator, Writer


class FakeWriter(Writer):
    """Small deterministic writer fake for P3 and the contract tests."""

    def write(
        self,
        question: str,
        passages: list[Passage],
        web: list[WebResult],
        ctx: UserContext,
        emit: Callable[[ProcessEvent], None] | None = None,
    ) -> Answer:
        del ctx  # The fake exercises the contract, not identity or access control.
        language = detect_language(question)
        if not passages and not web:
            return Answer(
                status=AnswerStatus.UNKNOWN,
                text=UNKNOWN[language],
                citations=[],
                confidence=0.0,
                language=language,
            )

        if passages:
            chunk = passages[0].chunk
            citation = Citation(
                doc_id=chunk.doc_id,
                url=None,
                title=chunk.title,
                article=chunk.article,
                page=chunk.page_start,
                source=chunk.source,
                date=chunk.date,
                excerpt=chunk.text,
            )
            text = (
                "Réponse de test fondée sur une source [1]."
                if language == "fr"
                else "إجابة اختبار مستندة إلى مصدر [1]."
            )
            confidence = 1.0
        else:
            result = web[0]
            citation = Citation(
                doc_id=None,
                url=result.url,
                title=result.title,
                article=None,
                page=None,
                source=None,
                date=None,
                excerpt=result.snippet,
            )
            body = "Résultat web de test [1]." if language == "fr" else "نتيجة ويب للاختبار [1]."
            text = f"{WEB_ONLY[language]}\n{body}"
            confidence = 0.5

        if emit is not None:
            emit(
                ProcessEvent(
                    step=StepType.VERIFY,
                    data={"supported": 1, "total": 1, "reasons": []},
                )
            )

        return Answer(
            status=AnswerStatus.ANSWERED,
            text=text,
            citations=[citation],
            confidence=confidence,
            language=language,
        )


class FakeNarrator(Narrator):
    """Deterministic narrator fake with a template for every process event."""

    async def narrate(self, event: ProcessEvent, language: str) -> AsyncIterator[str]:
        yield render_template(event, language)
