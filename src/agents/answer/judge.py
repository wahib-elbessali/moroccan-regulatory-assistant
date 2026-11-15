"""One-call claim verification and deterministic excerpt checking for P4."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from src.agents.answer.citations import (
    Claim,
    Source,
    checked_excerpt,
    cited_source_text,
)
from src.agents.answer.settings import setting
from src.core.contracts.protocols import LLMClient
from src.retrieval.tokenizer import STOPWORDS

_LOGGER = logging.getLogger(__name__)
_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL | re.IGNORECASE)


@dataclass(frozen=True)
class JudgeMetrics:
    fallback_used: bool
    tokens_used: int
    duration_ms: int


def _prompt(claims: list[Claim], sources: list[Source]) -> list[dict[str, str]]:
    from html import escape
    from pathlib import Path

    prompts = Path(__file__).with_name("prompts")
    claim_tags = []
    for number, claim in enumerate(claims, start=1):
        cited = ",".join(str(value) for value in claim.cited)
        claim_tags.append(f'<claim n="{number}" cites="{cited}">{escape(claim.text)}</claim>')
    source_tags = "\n".join(source.prompt_tag() for source in sources)
    user_template = (prompts / "judge_user.md").read_text(encoding="utf-8")
    return [
        {"role": "system", "content": (prompts / "judge_system.md").read_text(encoding="utf-8")},
        {
            "role": "user",
            "content": user_template.format(claims="\n".join(claim_tags), sources=source_tags),
        },
    ]


def _parse_verdicts(raw: str, expected: int) -> dict[int, dict[str, Any]]:
    match = _FENCE_RE.match(raw)
    payload = json.loads(match.group(1) if match else raw)
    if not isinstance(payload, dict) or not isinstance(payload.get("verdicts"), list):
        raise ValueError("judge response must contain a verdicts list")

    verdicts: dict[int, dict[str, Any]] = {}
    for item in payload["verdicts"]:
        if not isinstance(item, dict):
            raise ValueError("judge verdict must be an object")
        number = item.get("claim")
        supported = item.get("supported")
        if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= expected:
            raise ValueError("judge claim number is invalid")
        if number in verdicts or not isinstance(supported, bool):
            raise ValueError("judge verdict is duplicated or has no boolean result")
        if supported:
            source_n = item.get("source")
            excerpt = item.get("excerpt")
            if isinstance(source_n, bool) or not isinstance(source_n, int):
                raise ValueError("supported verdict has no valid source number")
            if not isinstance(excerpt, str):
                raise ValueError("supported verdict has no excerpt")
        verdicts[number] = item
    if set(verdicts) != set(range(1, expected + 1)):
        raise ValueError("judge response is missing a verdict")
    return verdicts


def _tokens(text: str) -> list[str]:
    from src.ingestion.normalize import normalize_ar  # P1 owns normalization.

    return [word for word in normalize_ar(text).split() if word not in STOPWORDS]


def _word_check(claim: Claim, sources: list[Source], min_chars: int) -> None:
    """P4-14 fallback: keep claims with at least half their words in a cited source."""
    best: tuple[float, int, str] | None = None
    claim_words = _tokens(claim.text)
    if not claim_words:
        claim.supported = False
        claim.reason = "not_supported"
        return

    from src.agents.answer.citations import split_claims

    for source in sources:
        if source.number not in claim.cited:
            continue
        for sentence in split_claims(source.text, set()):
            sentence_words = set(_tokens(sentence.text))
            overlap = sum(word in sentence_words for word in claim_words)
            ratio = overlap / len(claim_words)
            if best is None or ratio > best[0]:
                best = (ratio, source.number, sentence.text)

    if best is None or best[0] < 0.5:
        claim.supported = False
        claim.reason = "not_supported"
        return

    source_by_number = {source.number: source for source in sources}
    excerpt = checked_excerpt(best[2], source_by_number[best[1]].text, min_chars)
    if excerpt is None:
        claim.supported = False
        claim.reason = "excerpt_not_found"
        return
    claim.supported = True
    claim.reason = None
    claim.excerpt = excerpt
    claim.source_n = best[1]


def _count_tokens(llm: LLMClient, messages: list[dict[str, str]], reply: str) -> int:
    text = "\n".join(message["content"] for message in messages) + "\n" + reply
    try:
        return int(llm.count_tokens(text))
    except Exception:
        return 0


def judge(
    claims: list[Claim],
    sources: list[Source],
    llm: LLMClient,
    *,
    max_tokens: int,
) -> JudgeMetrics:
    """Verify cited claims in one LLM call, then validate every excerpt in code."""
    started = perf_counter()
    to_check = [claim for claim in claims if claim.cited]
    for claim in claims:
        if not claim.cited:
            claim.supported = False
            claim.reason = "no_citation"
    if not to_check:
        return JudgeMetrics(False, 0, round((perf_counter() - started) * 1000))

    selected_sources = cited_source_text(to_check, sources)
    messages = _prompt(to_check, selected_sources)
    fallback = False
    raw = ""
    try:
        raw = llm.chat(messages, max_tokens=max_tokens)
        verdicts = _parse_verdicts(raw, len(to_check))
    except Exception:
        fallback = True
        _LOGGER.warning("P4 judge fallback activated")
        verdicts = None

    min_chars = int(setting("answer", "min_excerpt_chars", 10))
    if fallback:
        for claim in to_check:
            _word_check(claim, sources, min_chars)
    else:
        assert verdicts is not None
        for number, claim in enumerate(to_check, start=1):
            verdict = verdicts[number]
            if not verdict["supported"]:
                claim.supported = False
                claim.reason = "not_supported"
                continue
            source_n = verdict["source"]
            source_by_number = {source.number: source for source in sources}
            if source_n not in claim.cited or source_n not in source_by_number:
                claim.supported = False
                claim.reason = "excerpt_not_found"
                continue
            excerpt = checked_excerpt(
                verdict["excerpt"], source_by_number[source_n].text, min_chars
            )
            if excerpt is None:
                claim.supported = False
                claim.reason = "excerpt_not_found"
                continue
            claim.supported = True
            claim.reason = None
            claim.excerpt = excerpt
            claim.source_n = source_n

    return JudgeMetrics(
        fallback_used=fallback,
        tokens_used=_count_tokens(llm, messages, raw),
        duration_ms=round((perf_counter() - started) * 1000),
    )
