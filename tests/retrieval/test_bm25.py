"""Tests of src/retrieval/bm25.py (P2 spec P2-04, P2-13, P2-21, §6.4, §6.5, §7, T14, T18, T19).

Most tests use payloads built by hand, the way ``QdrantStore.scroll_payloads`` returns them.
Every corpus includes public "filler" chunks without the query words: on a tiny corpus where
every chunk has the query words, BM25Okapi gives negative scores and nothing would be returned.
"""

import logging
import uuid
from pathlib import Path
from typing import Any

import pytest
from p2_helpers import HashModels, make_ctx, make_doc
from qdrant_client import QdrantClient
from rank_bm25 import BM25Okapi

from src.core.contracts import Chunk, InvalidInput, ServiceError
from src.ingestion import normalize_ar
from src.retrieval.bm25 import BM25Index, bm25_text
from src.retrieval.store import QdrantStore
from src.retrieval.tokenizer import tokenize
from src.retrieval.version import bump_version, read_version

PUBLIC = ["lecteur", "editeur"]
INTERNAL = ["editeur"]
U1 = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
U2 = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
QUERY_TEXT = "معالجة الطلبات"
MATCH_TEXT = normalize_ar("يتعين على المصالح معالجة الطلبات في أجل ثلاثين يوما")


def query(text: str = QUERY_TEXT) -> list[str]:
    return tokenize(normalize_ar(text))


def payloads_of(chunks: list[Chunk], *, hidden: bool = False) -> list[dict[str, Any]]:
    """Payloads as Qdrant stores them: every field of the Chunk + ``hidden``."""
    return [{**c.model_dump(mode="json"), "hidden": hidden} for c in chunks]


def doc(name: str, text: str = MATCH_TEXT, **kwargs: Any) -> list[Chunk]:
    return make_doc(name, texts=[text], **kwargs)


def filler(n: int = 10) -> list[dict[str, Any]]:
    """Public chunks without the query words, so the query words stay rare."""
    return payloads_of(
        [c for i in range(n) for c in doc(f"filler-{i}", f"موضوع مختلف رقم {i}", roles=PUBLIC)]
    )


class Loader:
    """``load_payloads`` that counts its calls."""

    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self.payloads = payloads
        self.calls = 0

    def __call__(self) -> list[dict[str, Any]]:
        self.calls += 1
        return self.payloads


@pytest.fixture
def version_file(tmp_path: Path) -> Path:
    return tmp_path / "indexes" / "retrieval.version"


@pytest.fixture
def corpus() -> dict[str, list[dict[str, Any]]]:
    """One chunk per kind of visibility, all containing the query words."""
    return {
        "public": payloads_of(doc("public", roles=PUBLIC)),
        "internal": payloads_of(doc("internal", roles=INTERNAL)),
        "private_u1": payloads_of(doc("private-u1", owner_id=U1)),
        "private_u2": payloads_of(doc("private-u2", owner_id=U2)),
        "hidden": payloads_of(doc("hidden", roles=PUBLIC), hidden=True),
    }


def ids(payloads: list[dict[str, Any]]) -> set[str]:
    return {p["chunk_id"] for p in payloads}


def build(payloads: list[dict[str, Any]], version_file: Path) -> tuple[BM25Index, Loader]:
    loader = Loader(payloads)
    return BM25Index(loader, version_file), loader


# --- bm25_text (P2-21) -------------------------------------------------------------------------


def test_bm25_text_joins_text_title_and_article_normalized() -> None:
    payload = {"text_normalized": "نص", "title": "القانون رقم 31.08", "article": "المادة 12"}
    assert bm25_text(payload) == "نص " + normalize_ar("القانون رقم 31.08") + " الماده 12"


def test_bm25_text_without_article() -> None:
    payload = {"text_normalized": "نص", "title": "عنوان", "article": None}
    assert tokenize(bm25_text(payload)) == ["نص", "عنوان"]


# --- Visibility before scoring (P2-13) ---------------------------------------------------------


@pytest.mark.parametrize(
    ("role", "user_id", "expected"),
    [
        ("lecteur", U1, {"public", "private_u1"}),
        ("lecteur", U2, {"public", "private_u2"}),
        ("editeur", None, {"public", "internal"}),
        ("editeur", U1, {"public", "internal", "private_u1"}),
        ("admin", None, set()),  # same rule as visibility_filter: "admin" is in no allowed_roles
    ],
)
def test_only_visible_chunks_are_returned(
    corpus: dict[str, list[dict[str, Any]]],
    version_file: Path,
    role: str,
    user_id: uuid.UUID | None,
    expected: set[str],
) -> None:
    index, _ = build([p for ps in corpus.values() for p in ps] + filler(), version_file)
    found = set(index.search(query(), make_ctx(role, user_id), 50))
    assert found == set().union(*(ids(corpus[k]) for k in expected))


def test_hidden_chunk_never_returned(
    corpus: dict[str, list[dict[str, Any]]], version_file: Path
) -> None:
    index, _ = build([p for ps in corpus.values() for p in ps] + filler(), version_file)
    for role in ("lecteur", "editeur", "admin"):
        assert not ids(corpus["hidden"]) & set(index.search(query(), make_ctx(role), 50))


def test_missing_hidden_field_counts_as_hidden(version_file: Path) -> None:
    payload = payloads_of(doc("no-hidden-field", roles=PUBLIC))
    del payload[0]["hidden"]
    index, _ = build(payload + filler(), version_file)
    assert index.search(query(), make_ctx("lecteur"), 50) == []


def test_invisible_chunks_are_never_scored(
    corpus: dict[str, list[dict[str, Any]]],
    version_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scored: list[int] = []
    original = BM25Okapi.get_batch_scores

    def spy(self: BM25Okapi, tokens: list[str], doc_ids: list[int]) -> list[float]:
        scored.extend(doc_ids)
        return original(self, tokens, doc_ids)  # type: ignore[no-any-return]

    monkeypatch.setattr(BM25Okapi, "get_batch_scores", spy)
    payloads = [p for ps in corpus.values() for p in ps] + filler()
    index, _ = build(payloads, version_file)
    index.search(query(), make_ctx("lecteur", U1), 50)

    scored_ids = {payloads[i]["chunk_id"] for i in scored}
    invisible = ids(corpus["internal"]) | ids(corpus["private_u2"]) | ids(corpus["hidden"])
    assert scored  # the spy really ran
    assert not scored_ids & invisible


def test_none_ctx_raises_invalid_input(version_file: Path) -> None:
    index, _ = build(filler(), version_file)
    with pytest.raises(InvalidInput):
        index.search(query(), None, 10)  # type: ignore[arg-type]


# --- Ranking (§6.4, T18, T19) ------------------------------------------------------------------


def test_article_number_ranks_its_own_article_first(version_file: Path) -> None:  # T18
    text = normalize_ar("نص المادة")
    a40 = payloads_of(doc("art-40", text, roles=PUBLIC, article="المادة 40"))
    a400 = payloads_of(doc("art-400", text, roles=PUBLIC, article="المادة 400"))
    index, _ = build(a400 + a40 + filler(), version_file)
    found = index.search(query("المادة 40"), make_ctx("lecteur"), 10)
    assert found[0] == a40[0]["chunk_id"]


def test_only_stopwords_gives_empty_list(version_file: Path) -> None:  # T19
    index, loader = build(filler(), version_file)
    tokens = query("في من على")
    assert tokens == []
    assert index.search(tokens, make_ctx("lecteur"), 10) == []
    assert loader.calls == 0  # nothing to search: Qdrant is not even read


def test_limit_is_respected(version_file: Path) -> None:
    matching = [p for i in range(5) for p in payloads_of(doc(f"match-{i}", roles=PUBLIC))]
    index, _ = build(matching + filler(), version_file)
    assert len(index.search(query(), make_ctx("lecteur"), 3)) == 3
    assert index.search(query(), make_ctx("lecteur"), 0) == []


def test_equal_scores_are_ordered_by_chunk_id(version_file: Path) -> None:
    matching = [p for i in range(5) for p in payloads_of(doc(f"tie-{i}", roles=PUBLIC))]
    index, _ = build(matching + filler(), version_file)
    found = index.search(query(), make_ctx("lecteur"), 10)
    assert found == sorted(ids(matching))


def test_chunks_without_query_words_are_not_returned(version_file: Path) -> None:
    index, _ = build(filler(), version_file)
    assert index.search(query(), make_ctx("lecteur"), 10) == []


def test_returns_chunk_ids_only(
    corpus: dict[str, list[dict[str, Any]]], version_file: Path
) -> None:
    index, _ = build(corpus["public"] + filler(), version_file)
    found = index.search(query(), make_ctx("lecteur"), 10)
    assert found == [corpus["public"][0]["chunk_id"]]
    assert all(isinstance(x, str) for x in found)  # no score leaves P2


@pytest.mark.parametrize(
    "payloads",
    [
        [],
        payloads_of(doc("only-stopwords", normalize_ar("في من على"), roles=PUBLIC)),
    ],
    ids=["empty-index", "no-token-at-all"],
)
def test_index_without_tokens_does_not_crash(
    payloads: list[dict[str, Any]], version_file: Path
) -> None:
    for p in payloads:
        p["title"] = ""  # nothing but stopwords in the whole index
    index, _ = build(payloads, version_file)
    assert index.search(query(), make_ctx("lecteur"), 10) == []


# --- Version file (§6.5, §7) -------------------------------------------------------------------


def test_missing_version_file_rebuilds_and_creates_it(version_file: Path) -> None:
    index, loader = build(filler(), version_file)
    assert read_version(version_file) is None
    index.search(query(), make_ctx("lecteur"), 10)
    assert loader.calls == 1
    assert read_version(version_file) is not None


def test_same_version_does_not_rebuild(version_file: Path) -> None:
    bump_version(version_file)
    index, loader = build(filler(), version_file)
    for _ in range(5):
        index.search(query(), make_ctx("lecteur"), 10)
    assert loader.calls == 1


def test_new_version_rebuilds(version_file: Path) -> None:
    bump_version(version_file)
    index, loader = build(filler(), version_file)
    index.search(query(), make_ctx("lecteur"), 10)
    bump_version(version_file)
    index.search(query(), make_ctx("lecteur"), 10)
    assert loader.calls == 2


def test_rebuild_sees_new_payloads(version_file: Path) -> None:
    bump_version(version_file)
    index, loader = build(filler(), version_file)
    assert index.search(query(), make_ctx("lecteur"), 10) == []

    new = payloads_of(doc("new", roles=PUBLIC))
    loader.payloads = loader.payloads + new
    assert index.search(query(), make_ctx("lecteur"), 10) == []  # version unchanged: not seen
    bump_version(version_file)
    assert index.search(query(), make_ctx("lecteur"), 10) == [new[0]["chunk_id"]]


def test_write_during_rebuild_is_not_missed(version_file: Path) -> None:
    """The version is read before the payloads, so a write during the rebuild forces one more."""
    bump_version(version_file)
    calls = 0

    def load() -> list[dict[str, Any]]:
        nonlocal calls
        calls += 1
        if calls == 1:
            bump_version(version_file)  # another process writes to Qdrant meanwhile
        return filler()

    index = BM25Index(load, version_file)
    index.search(query(), make_ctx("lecteur"), 10)
    index.search(query(), make_ctx("lecteur"), 10)
    assert calls == 2


def test_refresh_if_stale_can_be_called_directly(version_file: Path) -> None:
    bump_version(version_file)
    index, loader = build(filler(), version_file)
    index.refresh_if_stale()
    index.refresh_if_stale()
    assert loader.calls == 1


def test_qdrant_failure_is_raised_not_hidden(version_file: Path) -> None:  # §7: no fallback
    def down() -> list[dict[str, Any]]:
        raise ServiceError("qdrant unavailable (scroll_payloads)")

    index = BM25Index(down, version_file)
    with pytest.raises(ServiceError):
        index.search(query(), make_ctx("lecteur"), 10)


def test_works_again_after_qdrant_comes_back(version_file: Path) -> None:
    bump_version(version_file)
    public = payloads_of(doc("back", roles=PUBLIC))
    up = False

    def load() -> list[dict[str, Any]]:
        if not up:
            raise ServiceError("qdrant unavailable (scroll_payloads)")
        return public + filler()

    index = BM25Index(load, version_file)
    with pytest.raises(ServiceError):
        index.search(query(), make_ctx("lecteur"), 10)
    up = True
    assert index.search(query(), make_ctx("lecteur"), 10) == [public[0]["chunk_id"]]


# --- Logs (P2-29) ------------------------------------------------------------------------------


def test_logs_hold_no_text(
    corpus: dict[str, list[dict[str, Any]]],
    version_file: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="src.retrieval.bm25")
    index, _ = build([p for ps in corpus.values() for p in ps] + filler(), version_file)
    index.search(query(), make_ctx("lecteur", U1), 10)

    logged = " ".join(
        r.getMessage() + " " + " ".join(str(v) for v in r.__dict__.values()) for r in caplog.records
    )
    assert caplog.records  # the rebuild is logged
    for word in query() + ["عنوان", "يتعين", "المصالح"]:
        assert word not in logged


# --- With Qdrant: the real load_payloads and on_write ------------------------------------------


@pytest.fixture
def store_and_index(
    qdrant: QdrantClient, collection: str, version_file: Path
) -> tuple[QdrantStore, BM25Index]:
    store = QdrantStore(
        qdrant, HashModels(), collection=collection, on_write=lambda: bump_version(version_file)
    )
    store.ensure_collection()
    return store, BM25Index(load_payloads=store.scroll_payloads, version_file=version_file)


def index_and_show(store: QdrantStore, chunks: list[Chunk]) -> None:
    store.index(chunks)  # indexed hidden (P2-08)
    store.show(chunks[0].doc_id)


def test_hidden_by_another_process_not_returned(
    store_and_index: tuple[QdrantStore, BM25Index], qdrant: QdrantClient, version_file: Path
) -> None:  # T14
    store, index = store_and_index
    target = doc("target", roles=PUBLIC)
    index_and_show(store, target)
    for i in range(10):
        index_and_show(store, doc(f"q-filler-{i}", f"موضوع مختلف رقم {i}", roles=PUBLIC))
    ctx = make_ctx("lecteur")
    assert index.search(query(), ctx, 10) == [target[0].chunk_id]

    # Another process (P1's command line) writes to Qdrant directly, then bumps the version.
    qdrant.set_payload(store.collection, payload={"hidden": True}, points=[target[0].chunk_id])
    bump_version(version_file)
    assert index.search(query(), ctx, 10) == []


def test_hide_through_store_is_seen_by_bm25(
    store_and_index: tuple[QdrantStore, BM25Index],
) -> None:
    store, index = store_and_index
    target = doc("hide-me", roles=PUBLIC)
    index_and_show(store, target)
    for i in range(10):
        index_and_show(store, doc(f"h-filler-{i}", f"موضوع مختلف رقم {i}", roles=PUBLIC))
    ctx = make_ctx("lecteur")
    assert index.search(query(), ctx, 10) == [target[0].chunk_id]

    store.hide(target[0].doc_id)  # on_write bumps the version
    assert index.search(query(), ctx, 10) == []


def test_newly_indexed_document_stays_invisible_until_shown(
    store_and_index: tuple[QdrantStore, BM25Index],
) -> None:
    store, index = store_and_index
    for i in range(10):
        index_and_show(store, doc(f"n-filler-{i}", f"موضوع مختلف رقم {i}", roles=PUBLIC))
    target = doc("new-doc", roles=PUBLIC)
    store.index(target)
    ctx = make_ctx("lecteur")
    assert index.search(query(), ctx, 10) == []
    store.show(target[0].doc_id)
    assert index.search(query(), ctx, 10) == [target[0].chunk_id]


# --- With P1's sample chunks -------------------------------------------------------------------


def test_sample_chunks_private_upload_only_for_its_owner(
    sample_chunks: list[Chunk], version_file: Path
) -> None:
    payloads = payloads_of(sample_chunks)
    index, _ = build(payloads, version_file)
    private = next(c for c in sample_chunks if c.owner_id)  # owner taken from the data
    tokens = tokenize(private.text_normalized)

    assert private.chunk_id in index.search(tokens, make_ctx("lecteur", private.owner_id), 50)
    for role in ("lecteur", "editeur", "admin"):
        assert private.chunk_id not in index.search(tokens, make_ctx(role), 50)


def test_sample_chunks_internal_document_only_for_editeur(
    sample_chunks: list[Chunk], version_file: Path
) -> None:
    index, _ = build(payloads_of(sample_chunks), version_file)
    internal = {c.chunk_id for c in sample_chunks if c.allowed_roles == INTERNAL}
    some = next(c for c in sample_chunks if c.allowed_roles == INTERNAL)
    tokens = tokenize(some.text_normalized)

    assert not internal & set(index.search(tokens, make_ctx("lecteur"), 50))
    assert internal & set(index.search(tokens, make_ctx("editeur"), 50))


def test_sample_chunks_article_40_before_400(
    sample_chunks: list[Chunk], version_file: Path
) -> None:  # T18 on P1's data
    index, _ = build(payloads_of(sample_chunks), version_file)
    found = index.search(query("المادة 40"), make_ctx("lecteur"), 10)
    by_id = {c.chunk_id: c for c in sample_chunks}
    assert by_id[found[0]].article == "المادة 40"
