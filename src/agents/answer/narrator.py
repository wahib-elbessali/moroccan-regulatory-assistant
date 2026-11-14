"""Real P4 process narrators."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path

from src.agents.answer.narration_templates import render_template
from src.agents.answer.settings import app_mode, setting
from src.core.contracts.models import ProcessEvent
from src.core.contracts.protocols import LLMClient, Narrator

_LOGGER = logging.getLogger(__name__)
_PROMPTS = Path(__file__).with_name("prompts")


def get_llm() -> LLMClient:
    """Resolve P6's LLM lazily so template narration needs no LLM service."""
    from src.core.contracts.registry import get_llm as registry_get_llm

    return registry_get_llm()


def _language_name(language: str) -> str:
    return "Modern Standard Arabic" if language == "ar" else "French"


def _messages(event: ProcessEvent, language: str) -> list[dict[str, str]]:
    system = (_PROMPTS / "narrator_system.md").read_text(encoding="utf-8")
    user = (_PROMPTS / "narrator_user.md").read_text(encoding="utf-8")
    event_json = json.dumps(
        {"step": str(event.step), "data": event.data},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return [
        {
            "role": "system",
            "content": system.format(language_name=_language_name(language)),
        },
        {"role": "user", "content": user.format(event_json=event_json)},
    ]


class TemplateNarrator(Narrator):
    """Deterministic bilingual narrator used in light mode and as a fallback."""

    async def narrate(self, event: ProcessEvent, language: str) -> AsyncIterator[str]:
        yield render_template(event, language)


class LLMNarrator(Narrator):
    """Stream short process narration, with fixed templates for sensitive steps."""

    async def narrate(self, event: ProcessEvent, language: str) -> AsyncIterator[str]:
        if str(event.step) in {"web", "verify"}:
            yield render_template(event, language)
            return

        yielded = False
        try:
            async for piece in get_llm().stream(
                _messages(event, language),
                model=setting("llm", "narration_model", None),
                max_tokens=int(setting("answer", "narration_max_tokens", 60)),
            ):
                if piece:
                    yielded = True
                    yield piece
            if not yielded:
                yield render_template(event, language)
        except Exception:
            _LOGGER.warning("P4 narrator fallback activated")
            try:
                yield render_template(event, language)
            except Exception:
                return


def real_narrator() -> Narrator:
    """Choose deterministic narration in light mode and LLM narration otherwise."""
    if app_mode() == "light":
        return TemplateNarrator()
    return LLMNarrator()
