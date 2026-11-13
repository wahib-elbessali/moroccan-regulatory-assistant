"""Real P4 writer: draft from sources, verify claims, and build a cited Answer."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from html import escape
from pathlib import Path
from time import perf_counter

from src.agents.answer.citations import Source, build_sources, renumber, split_claims
from src.agents.answer.judge import judge
from src.agents.answer.settings import setting
from src.agents.answer.texts import UNKNOWN, WEB_ONLY, WEB_PART
from src.core.contracts import detect_language
from src.core.contracts.enums import AnswerStatus, StepType
from src.core.contracts.errors import ServiceError
from src.core.contracts.models import Answer, Passage, ProcessEvent, UserContext, WebResult
from src.core.contracts.protocols import LLMClient, Writer


def get_llm() -> LLMClient:
    """Resolve P6's LLM through P5's registry only when a real write is requested."""
    from src.core.contracts.registry import get_llm as registry_get_llm

    return registry_get_llm()


_LOGGER = logging.getLogger(__name__)
_PROMPTS = Path(__file__).with_name("prompts")


def _language_name(language: str) -> str:
    return "Modern Standard Arabic" if language == "ar" else "French"


def _writer_messages(question: str, sources: list[Source], language: str) -> list[dict[str, str]]:
    system = (_PROMPTS / "writer_system.md").read_text(encoding="utf-8")
    user = (_PROMPTS / "writer_user.md").read_text(encoding="utf-8")
    source_tags = "\n".join(source.prompt_tag() for source in sources)
    return [
        {
            "role": "system",
            "content": system.format(language_name=_language_name(language)),
        },
        {
            "role": "user",
            "content": user.format(question=escape(question), sources=source_tags),
        },
    ]


def _count_tokens(llm: LLMClient, messages: list[dict[str, str]], reply: str) -> int:
    text = "\n".join(message["content"] for message in messages) + "\n" + reply
    try:
        return int(llm.count_tokens(text))
    except Exception:
        return 0


def _unknown(language: str) -> Answer:
    return Answer(
        status=AnswerStatus.UNKNOWN,
        text=UNKNOWN[language],
        citations=[],
        confidence=0.0,
        language=language,
    )


class RealWriter(Writer):
    """LLM-backed writer which retains only claims with checked source excerpts."""

    def write(
        self,
        question: str,
        passages: list[Passage],
        web: list[WebResult],
        ctx: UserContext,
        emit: Callable[[ProcessEvent], None] | None = None,
    ) -> Answer:
        started = perf_counter()
        language = detect_language(question)  # P3 owns this shared detector.
        metrics: dict[str, int | bool] = {
            "source_count": 0,
            "claim_count": 0,
            "supported_count": 0,
            "judge_fallback": False,
            "writer_tokens": 0,
            "judge_tokens": 0,
            "source_build_ms": 0,
            "writer_ms": 0,
            "split_ms": 0,
            "judge_ms": 0,
            "citation_ms": 0,
        }

        def finish(answer: Answer, status: str | None = None) -> Answer:
            payload = {
                "request_id": str(ctx.request_id),
                **metrics,
                "status": status or answer.status,
                "confidence": answer.confidence,
                "total_ms": round((perf_counter() - started) * 1000),
            }
            _LOGGER.info(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
            return answer

        if not passages and not web:
            return finish(_unknown(language))

        stage = perf_counter()
        sources = build_sources(passages, web)
        metrics["source_count"] = len(sources)
        metrics["source_build_ms"] = round((perf_counter() - stage) * 1000)

        stage = perf_counter()
        try:
            llm = get_llm()
            messages = _writer_messages(question, sources, language)
            draft = llm.chat(
                messages,
                max_tokens=int(setting("answer", "max_answer_tokens", 800)),
            ).strip()
        except Exception:
            metrics["writer_ms"] = round((perf_counter() - stage) * 1000)
            finish(_unknown(language), status="error")
            raise ServiceError("Writer service unavailable") from None
        metrics["writer_ms"] = round((perf_counter() - stage) * 1000)
        metrics["writer_tokens"] = _count_tokens(llm, messages, draft)
        if draft == "NO_ANSWER" or not draft:
            return finish(_unknown(language))

        stage = perf_counter()
        claims = split_claims(draft, {source.number for source in sources})
        metrics["claim_count"] = len(claims)
        metrics["split_ms"] = round((perf_counter() - stage) * 1000)

        judge_metrics = judge(
            claims,
            sources,
            llm,
            max_tokens=int(setting("answer", "max_judge_tokens", 600)),
        )
        metrics["judge_ms"] = judge_metrics.duration_ms
        metrics["judge_tokens"] = judge_metrics.tokens_used
        metrics["judge_fallback"] = judge_metrics.fallback_used
        kept = [claim for claim in claims if claim.supported]
        metrics["supported_count"] = len(kept)

        if emit is not None:
            emit(
                ProcessEvent(
                    step=StepType.VERIFY,
                    data={
                        "supported": len(kept),
                        "total": len(claims),
                        "reasons": [
                            claim.reason for claim in claims if not claim.supported and claim.reason
                        ],
                    },
                )
            )
        if not kept:
            return finish(_unknown(language))

        stage = perf_counter()
        answer_text, citations = renumber(kept, sources)
        metrics["citation_ms"] = round((perf_counter() - stage) * 1000)
        if not citations:
            return finish(_unknown(language))

        confidence = round(len(kept) / len(claims), 2)
        all_web = all(citation.url is not None for citation in citations)
        if all_web:
            confidence = min(confidence, float(setting("answer", "web_confidence_cap", 0.5)))
        if confidence < float(setting("agents", "confidence_unknown_below", 0.4)):
            return finish(_unknown(language))

        if any(citation.url is not None for citation in citations):
            notice = WEB_ONLY[language] if all_web else WEB_PART[language]
            answer_text = f"{notice}\n{answer_text}"
        answer = Answer(
            status=AnswerStatus.ANSWERED,
            text=answer_text,
            citations=citations,
            confidence=confidence,
            language=language,
        )
        return finish(answer)


def real_writer() -> Writer:
    """Factory used by P5's contract registry when ``contracts.writer`` is ``real``."""
    return RealWriter()
