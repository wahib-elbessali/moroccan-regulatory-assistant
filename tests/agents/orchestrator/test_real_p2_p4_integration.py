# tests/agents/orchestrator/test_real_p2_p4_integration.py
"""P3 on top of the REAL P2 (T24) and the REAL P4 writer, judge and narrator.

Nothing is mocked in the access path: `Retrieval` is P2's real pipeline (Qdrant filter, BM25,
RRF, re-check) over `tests/fixtures/sample_chunks.jsonl`, with Qdrant in memory and a
deterministic embedding. The LLM is scripted, the writer and the narrator only record what P3
gives them.

T24 (P3-orchestration.md §8) and the owner isolation of the sample chunks are checked first with
a recording writer, then end to end with the real P4 `RealWriter` + judge + `LLMNarrator`. The
LLM is scripted, so nothing here depends on a model; a real model must produce what the scripted
one does: one cited sentence per claim, and a judge excerpt copied from ONE source sentence.

For every forbidden case there is a control case with the allowed user: without it, a search
that returns nothing at all would pass "no leak" for the wrong reason.
"""

import hashlib
import json
import math
import re
from collections.abc import AsyncIterator
from html import unescape

import pytest
from qdrant_client import QdrantClient

from src.agents.answer.narrator import LLMNarrator
from src.agents.answer.writer import RealWriter
from src.agents.orchestrator.real import RealOrchestrator
from src.core.contracts import registry
from src.core.contracts.enums import AnswerStatus
from src.core.contracts.models import (
    Answer,
    Passage,
    ProcessEvent,
    UserContext,
    WebLookup,
    WebResult,
)
from src.retrieval.bm25 import BM25Index
from src.retrieval.search import Retrieval
from src.retrieval.store import VECTOR_SIZE, QdrantStore
from src.retrieval.version import bump_version

DRAFT_TITLE = "مشروع قانون افتراضي"  # internal draft law: editeur only
STUDENT_TITLE = "ملخص مشروع طالب"  # private document of OTHER_LECTEUR_ID
DRAFT_QUESTION = (
    "ما هي مدة حفظ الوثائق وأجل إعداد خطة التصحيح بالنسبة لمقدم الخدمة الرقمية "
    "في مشروع القانون المتعلق بحوكمة أنظمة الذكاء الاصطناعي؟"
)
STUDENT_QUESTION = "ما هي أعلى قيمة استهلاك سجلت في المبنى B-02؟"


class HashModels:
    """Deterministic embeddings and a word-overlap re-ranker: no model is loaded."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def rerank(self, query: str, texts: list[str]) -> list[float]:
        words = set(query.split())
        return [float(len(words & set(t.split()))) for t in texts]

    @staticmethod
    def _vector(text: str) -> list[float]:
        raw: list[float] = []
        counter = 0
        while len(raw) < VECTOR_SIZE:
            raw += [b / 255 - 0.5 for b in hashlib.sha256(f"{counter}:{text}".encode()).digest()]
            counter += 1
        raw = raw[:VECTOR_SIZE]
        norm = math.sqrt(sum(x * x for x in raw))
        return [x / norm for x in raw]


class RoleLLM:
    """Plans one sub-question, then finds every passage relevant. Decided by message shape."""

    def __init__(self, question: str):
        self.question = question
        self.calls = 0

    def chat(self, messages, *, model=None, max_tokens=None, temperature=0.0) -> str:
        self.calls += 1
        user = messages[-1]["content"]
        if "<document" in user:  # grading call
            numbers = ", ".join(str(i) for i in range(1, user.count("<document") + 1))
            return f'{{"relevant": [{numbers}]}}'
        if self.calls == 1:  # planner
            return f'{{"sub_questions": ["{self.question}"], "needs_web": false}}'
        return ""

    async def stream(self, messages, *, model=None, max_tokens=None) -> AsyncIterator[str]:
        yield self.chat(messages)

    def count_tokens(self, text: str) -> int:
        return 10


class RecordingWriter:
    def __init__(self) -> None:
        self.passages: list[Passage] = []

    def write(
        self, question, passages, web: list[WebResult], ctx: UserContext, emit=None
    ) -> Answer:
        self.passages = list(passages)
        return Answer(
            status=AnswerStatus.ANSWERED if passages else AnswerStatus.UNKNOWN,
            text="x [1]" if passages else "لا أعلم",
            citations=[],
            confidence=0.8,
            language="ar",
        )


class SpyNarrator:
    def __init__(self) -> None:
        self.events: list[ProcessEvent] = []

    async def narrate(self, event: ProcessEvent, language: str) -> AsyncIterator[str]:
        self.events.append(event)
        yield "x"


class NoWebAgent:
    def lookup(self, question, ctx, language, use_web=True) -> WebLookup:
        return WebLookup(status="skipped", results=[])


@pytest.fixture
def real_p2(tmp_path, sample_chunks) -> Retrieval:
    """P2's real pipeline over the sample chunks (Qdrant in memory, hash embeddings)."""
    version_file = tmp_path / "retrieval.version"
    models = HashModels()
    store = QdrantStore(
        QdrantClient(":memory:"),
        models,
        collection="t24",
        on_write=lambda: bump_version(version_file),
    )
    store.ensure_collection()
    bm25 = BM25Index(load_payloads=store.scroll_payloads, version_file=version_file)
    retrieval = Retrieval(store, bm25, models=models)

    docs: dict[str, list] = {}
    for chunk in sample_chunks:
        docs.setdefault(chunk.doc_id, []).append(chunk)
    for doc_id, chunks in docs.items():
        retrieval.index(sorted(chunks, key=lambda c: c.chunk_index))
        retrieval.show(doc_id)
    return retrieval


async def _ask(real_p2, question: str, ctx: UserContext):
    writer, narrator = RecordingWriter(), SpyNarrator()
    registry.override("llm", RoleLLM(question))
    registry.override("retrieval", real_p2)
    registry.override("writer", writer)
    registry.override("narrator", narrator)
    registry.override("web_agent", NoWebAgent())
    events = [e async for e in RealOrchestrator().run(question, ctx, use_web=False)]
    searched_titles = [
        title for ev in narrator.events if ev.step == "search" for title in ev.data["titles"]
    ]
    return events, writer.passages, searched_titles


@pytest.mark.parametrize(
    ("ctx_fixture", "question", "title", "may_see"),
    [
        ("lecteur_ctx", DRAFT_QUESTION, DRAFT_TITLE, False),  # T24
        ("editeur_ctx", DRAFT_QUESTION, DRAFT_TITLE, True),  # control
        ("lecteur_ctx", STUDENT_QUESTION, STUDENT_TITLE, False),  # owner isolation
        ("other_lecteur_ctx", STUDENT_QUESTION, STUDENT_TITLE, True),  # control
    ],
    ids=["T24-lecteur", "T24-control-editeur", "owner-other-lecteur", "owner-control-owner"],
)
async def test_t24_access_filter_through_p3(
    request, real_p2, ctx_fixture, question, title, may_see
):
    ctx = request.getfixturevalue(ctx_fixture)
    events, written, searched_titles = await _ask(real_p2, question, ctx)

    assert events[-1]["event"] == "answer"
    seen_by_writer = [p.chunk.title for p in written if title in p.chunk.title]
    seen_in_search = [t for t in searched_titles if title in t]

    if may_see:
        # Control: the document is reachable for this user, so "no leak" elsewhere is meaningful.
        assert seen_by_writer, "the allowed user should reach the document"
        assert seen_in_search
    else:
        assert seen_by_writer == []  # `write` receives no chunk of that document
        assert seen_in_search == []  # the `search` events' titles do not name it
        assert title not in str(events)  # nor does anything streamed to the user


# --- P3 + the real P4 (writer, judge, narrator) -------------------------------------------------

_SENTENCE = re.compile(r"(?<=[.!؟?])\s+|\n+")
_SOURCE = re.compile(r'<source n="(\d+)"[^>]*>(.*?)</source>', re.DOTALL)
_CLAIM = re.compile(r'<claim n="(\d+)" cites="(\d*)"')


class ScriptedP4LLM(RoleLLM):
    """RoleLLM plus the answers P4 expects: a cited sentence, then one judge verdict per claim."""

    def chat(self, messages, *, model=None, max_tokens=None, temperature=0.0) -> str:
        user = messages[-1]["content"]
        if "<claim" in user:  # P4 judge: support every claim with ONE sentence of its source
            texts = {int(n): unescape(t) for n, t in _SOURCE.findall(user)}
            verdicts = []
            for number, cites in _CLAIM.findall(user):
                source = int(cites.split(",")[0])
                sentences = [x.strip() for x in _SENTENCE.split(texts[source]) if x.strip()]
                excerpt = max(sentences, key=len)
                verdicts.append(
                    {"claim": int(number), "supported": True, "source": source, "excerpt": excerpt}
                )
            return json.dumps({"verdicts": verdicts}, ensure_ascii=False)
        if "<source" in user:  # P4 writer
            return "تنص الوثيقة على ما يلي [1]."
        return super().chat(messages, model=model, max_tokens=max_tokens, temperature=temperature)


class SpyRealWriter(RealWriter):
    """The real P4 writer, remembering the passages P3 gave it."""

    def __init__(self) -> None:
        self.passages: list[Passage] = []

    def write(self, question, passages, web, ctx, emit=None) -> Answer:
        self.passages = list(passages)
        return super().write(question, passages, web, ctx, emit)


async def _ask_real_p4(real_p2, question: str, ctx: UserContext):
    writer = SpyRealWriter()
    registry.override("llm", ScriptedP4LLM(question))
    registry.override("retrieval", real_p2)
    registry.override("writer", writer)
    registry.override("narrator", LLMNarrator())
    registry.override("web_agent", NoWebAgent())
    events = [e async for e in RealOrchestrator().run(question, ctx, use_web=False)]
    return events, writer.passages


async def test_p3_with_real_p4_answers_with_a_checked_citation(real_p2, lecteur_ctx):
    events, passages = await _ask_real_p4(
        real_p2, "ما هي الشروط الواجب توفرها في عقد الزواج؟", lecteur_ctx
    )

    assert events[-1]["event"] == "answer"
    answer = events[-1]["data"]
    assert answer["status"] == "answered"
    assert answer["citations"], "the answer must cite a source"
    assert all(c["excerpt"] for c in answer["citations"])  # the judge kept a checked excerpt
    assert any(e["event"] == "thinking" and e["data"]["text"] for e in events)  # real narrator
    assert passages, "P3 must hand passages to the writer"


@pytest.mark.parametrize(
    ("ctx_fixture", "may_see"),
    [("lecteur_ctx", False), ("editeur_ctx", True)],
    ids=["T24-real-p4-lecteur", "T24-real-p4-control-editeur"],
)
async def test_t24_through_the_real_writer(request, real_p2, ctx_fixture, may_see):
    ctx = request.getfixturevalue(ctx_fixture)
    events, passages = await _ask_real_p4(real_p2, DRAFT_QUESTION, ctx)

    assert events[-1]["event"] == "answer"
    in_passages = [p for p in passages if DRAFT_TITLE in p.chunk.title]
    cited = [c for c in events[-1]["data"]["citations"] if DRAFT_TITLE in (c["title"] or "")]
    if may_see:
        assert in_passages  # control: the draft is reachable by an editeur
    else:
        assert in_passages == []
        assert cited == []
        assert DRAFT_TITLE not in str(events)
