"""Tests of src/retrieval/store.py (P2 spec §8: T5–T11, T17, and the visibility filter)."""

import logging
import uuid
from unittest.mock import MagicMock

import pytest
from p2_helpers import HashModels, hash_vector, make_ctx, make_doc
from qdrant_client import QdrantClient, models

from src.core.contracts import (
    INTERNAL_ROLES,
    PUBLIC_ROLES,
    Chunk,
    InvalidInput,
    ServiceError,
    make_chunk_id,
)
from src.retrieval import store as store_module
from src.retrieval.store import QdrantStore, embedding_text, visibility_filter


@pytest.fixture
def writes() -> list[int]:
    return []


@pytest.fixture
def store(qdrant: QdrantClient, collection: str, writes: list[int]) -> QdrantStore:
    s = QdrantStore(
        qdrant,
        HashModels(),
        collection=collection,
        embed_batch_size=2,
        on_write=lambda: writes.append(1),
    )
    s.ensure_collection()
    return s


def visible_doc_ids(store: QdrantStore, ctx) -> set[str]:
    chunks = store.vector_search(hash_vector("سؤال"), visibility_filter(ctx), limit=100)
    return {c.doc_id for c in chunks}


def all_points(store: QdrantStore) -> list[dict]:
    return store.scroll_payloads()


# --- embedding_text (T17) -----------------------------------------------------------------------


def test_embedding_text_title_headings_text():
    chunk = make_doc("law", 1, article="المادة 12")[0].model_copy(
        update={"title": "القانون رقم 31.08", "hierarchy": ["الباب الثاني"], "text": "النص"}
    )
    assert embedding_text(chunk) == "القانون رقم 31.08\nالباب الثاني › المادة 12\nالنص"


def test_embedding_text_skips_empty_parts():
    chunk = make_doc("law", 1)[0].model_copy(update={"title": "عنوان", "text": "النص"})
    assert embedding_text(chunk) == "عنوان\nالنص"


def test_embedding_text_hierarchy_without_article():
    chunk = make_doc("law", 1)[0].model_copy(
        update={"title": "ع", "hierarchy": ["الكتاب الأول", "الباب الثاني"], "text": "ن"}
    )
    assert embedding_text(chunk) == "ع\nالكتاب الأول › الباب الثاني\nن"


# --- collection ---------------------------------------------------------------------------------


def test_ensure_collection_is_idempotent(store: QdrantStore, qdrant: QdrantClient):
    store.ensure_collection()
    info = qdrant.get_collection(store.collection)
    assert info.config.params.vectors.size == 1024
    assert info.config.params.vectors.distance == models.Distance.COSINE


# --- index (P2-05…P2-10, T10, T11) --------------------------------------------------------------


def test_index_stores_every_field_and_hidden(store: QdrantStore):
    owner = uuid.uuid4()
    chunks = make_doc("upload", 3, owner_id=owner)
    store.index(chunks)
    payloads = sorted(all_points(store), key=lambda p: p["chunk_index"])
    assert len(payloads) == 3
    for chunk, payload in zip(chunks, payloads, strict=True):
        assert payload == {**chunk.model_dump(mode="json"), "hidden": True}
        assert payload["owner_id"] == str(owner)


def test_index_embeds_in_batches(qdrant: QdrantClient, collection: str):
    models_client = HashModels()
    s = QdrantStore(qdrant, models_client, collection=collection, embed_batch_size=2)
    s.ensure_collection()
    s.index(make_doc("law", 5))
    assert models_client.embed_calls == [2, 2, 1]


def test_reindex_shorter_document_removes_leftovers(store: QdrantStore):  # T10
    store.index(make_doc("law", 5))
    store.index(make_doc("law", 3))
    indexes = sorted(p["chunk_index"] for p in all_points(store))
    assert indexes == [0, 1, 2]
    assert all(p["total_chunks"] == 3 for p in all_points(store))


def test_reindex_does_not_touch_other_documents(store: QdrantStore):
    store.index(make_doc("a", 4))
    store.index(make_doc("b", 1))
    assert len(all_points(store)) == 5


def _two_docs() -> list[Chunk]:
    return make_doc("a", 1) + make_doc("b", 1)


def _wrong_chunk_id() -> list[Chunk]:
    chunk = make_doc("a", 1)[0]
    return [chunk.model_copy(update={"chunk_id": make_chunk_id(chunk.doc_id, 7)})]


def _mixed_totals() -> list[Chunk]:
    chunks = make_doc("a", 2)
    return [chunks[0], chunks[1].model_copy(update={"total_chunks": 3})]


def _index_out_of_range() -> list[Chunk]:
    chunk = make_doc("a", 1)[0]
    data = chunk.model_dump() | {"chunk_index": 1, "chunk_id": make_chunk_id(chunk.doc_id, 1)}
    return [Chunk.model_construct(**data)]  # skips the model's own check


@pytest.mark.parametrize(
    "build",
    [lambda: [], _two_docs, _wrong_chunk_id, _mixed_totals, _index_out_of_range],
    ids=["empty", "two-doc-ids", "wrong-chunk-id", "mixed-totals", "index-out-of-range"],
)
def test_index_rejects_invalid_lists(store: QdrantStore, writes: list[int], build):  # T11
    with pytest.raises(InvalidInput):
        store.index(build())
    assert all_points(store) == []
    assert writes == []


def test_index_rejects_bad_vectors(qdrant: QdrantClient, collection: str):
    bad = MagicMock()
    bad.embed.return_value = [[0.1, 0.2]]
    s = QdrantStore(qdrant, bad, collection=collection)
    s.ensure_collection()
    with pytest.raises(ServiceError):
        s.index(make_doc("a", 1))
    assert s.scroll_payloads() == []


# --- visibility filter (P2-12, 00-shared §6.3) --------------------------------------------------

LECTEUR_A = uuid.uuid4()
LECTEUR_B = uuid.uuid4()
ADMIN = uuid.uuid4()


@pytest.fixture
def corpus(store: QdrantStore) -> dict[str, str]:
    """Shown documents of every kind, plus one never shown. Returns name -> doc_id."""
    docs = {
        "public": make_doc("public", roles=PUBLIC_ROLES),
        "internal": make_doc("internal", roles=INTERNAL_ROLES),
        "private_a": make_doc("private_a", owner_id=LECTEUR_A),
        "private_b": make_doc("private_b", owner_id=LECTEUR_B),
        "never_shown": make_doc("never_shown", roles=PUBLIC_ROLES),
    }
    for name, chunks in docs.items():
        store.index(chunks)
        if name != "never_shown":
            store.show(chunks[0].doc_id)
    return {name: chunks[0].doc_id for name, chunks in docs.items()}


@pytest.mark.parametrize(
    "role, user_id, expected",
    [
        ("lecteur", LECTEUR_A, {"public", "private_a"}),
        ("lecteur", LECTEUR_B, {"public", "private_b"}),
        ("editeur", uuid.uuid4(), {"public", "internal"}),
        ("admin", ADMIN, set()),
    ],
    ids=["lecteur-a", "lecteur-b", "editeur", "admin"],
)
def test_vector_search_returns_only_visible_chunks(store, corpus, role, user_id, expected):
    ctx = make_ctx(role, user_id)
    assert visible_doc_ids(store, ctx) == {corpus[name] for name in expected}


def test_never_shown_document_is_not_returned_even_on_exact_text(store, corpus):  # T5
    target = make_doc("never_shown", roles=PUBLIC_ROLES)[0]
    for role in ("lecteur", "editeur", "admin"):
        hits = store.vector_search(
            hash_vector(embedding_text(target)), visibility_filter(make_ctx(role)), limit=100
        )
        assert corpus["never_shown"] not in {c.doc_id for c in hits}


def test_private_upload_not_returned_to_other_user_on_exact_text(store, corpus):
    target = make_doc("private_a", owner_id=LECTEUR_A)[0]
    hits = store.vector_search(
        hash_vector(embedding_text(target)),
        visibility_filter(make_ctx("lecteur", LECTEUR_B)),
        limit=100,
    )
    assert corpus["private_a"] not in {c.doc_id for c in hits}


def test_visibility_filter_requires_context():
    with pytest.raises(InvalidInput):
        visibility_filter(None)  # type: ignore[arg-type]


def test_vector_search_returns_chunks(store, corpus):
    hits = store.vector_search(
        hash_vector("سؤال"), visibility_filter(make_ctx("editeur")), limit=100
    )
    assert all(isinstance(c, Chunk) for c in hits)
    assert len(hits) == 4  # 2 documents x 2 chunks


def test_vector_search_respects_limit(store, corpus):
    hits = store.vector_search(hash_vector("سؤال"), visibility_filter(make_ctx("editeur")), 1)
    assert len(hits) == 1


# --- recheck (P2-14) ----------------------------------------------------------------------------


def test_recheck_keeps_only_visible_ids(store, corpus):
    ids = [p["chunk_id"] for p in all_points(store)]
    ctx = make_ctx("lecteur", LECTEUR_A)
    kept = store.recheck(ids, visibility_filter(ctx))
    assert {c.doc_id for c in kept.values()} == {corpus["public"], corpus["private_a"]}
    assert all(cid == c.chunk_id for cid, c in kept.items())


def test_recheck_drops_a_chunk_hidden_since(store, corpus):
    ids = [p["chunk_id"] for p in all_points(store) if p["doc_id"] == corpus["public"]]
    store.hide(corpus["public"])
    assert store.recheck(ids, visibility_filter(make_ctx("lecteur"))) == {}


def test_recheck_empty_list(store):
    assert store.recheck([], visibility_filter(make_ctx("lecteur"))) == {}


def test_recheck_unknown_id(store, corpus):
    unknown = str(uuid.uuid4())
    assert store.recheck([unknown], visibility_filter(make_ctx("editeur"))) == {}


# --- rights and state (P2-23…P2-27, T6–T9) ------------------------------------------------------


def test_hide_then_show(store, corpus):  # T6
    lecteur = make_ctx("lecteur")
    store.hide(corpus["public"])
    assert corpus["public"] not in visible_doc_ids(store, lecteur)
    store.show(corpus["public"])
    assert corpus["public"] in visible_doc_ids(store, lecteur)


def test_update_roles_opens_internal_document(store, corpus):  # T7
    lecteur = make_ctx("lecteur")
    assert corpus["internal"] not in visible_doc_ids(store, lecteur)
    store.update_roles(corpus["internal"], PUBLIC_ROLES)
    assert corpus["internal"] in visible_doc_ids(store, lecteur)


def test_update_roles_does_not_change_hidden(store, corpus):
    store.update_roles(corpus["never_shown"], PUBLIC_ROLES)
    assert corpus["never_shown"] not in visible_doc_ids(store, make_ctx("lecteur"))


def test_rights_change_every_chunk_of_the_document(store, corpus):
    store.update_roles(corpus["public"], INTERNAL_ROLES)
    store.hide(corpus["public"])
    points = [p for p in all_points(store) if p["doc_id"] == corpus["public"]]
    assert len(points) == 2
    assert all(p["allowed_roles"] == INTERNAL_ROLES and p["hidden"] for p in points)


def test_delete_twice(store, corpus):  # T8
    store.delete(corpus["public"])
    store.delete(corpus["public"])
    assert not [p for p in all_points(store) if p["doc_id"] == corpus["public"]]
    assert len(all_points(store)) == 8  # the 4 other documents are untouched


def test_unknown_doc_id_is_a_warning(store, writes, caplog):  # T9
    caplog.set_level(logging.WARNING)
    for call in (store.hide, store.show, store.delete):
        call("unknown")
    store.update_roles("unknown", PUBLIC_ROLES)
    assert writes == []
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 4


def test_every_write_calls_on_write(store, writes):
    doc = make_doc("a")
    doc_id = doc[0].doc_id
    store.index(doc)
    store.update_roles(doc_id, PUBLIC_ROLES)
    store.show(doc_id)
    store.hide(doc_id)
    store.delete(doc_id)
    assert len(writes) == 5


# --- scroll_payloads ----------------------------------------------------------------------------


def test_scroll_payloads_reads_every_page(store, monkeypatch):
    monkeypatch.setattr(store_module, "_SCROLL_PAGE", 2)
    store.index(make_doc("a", 5))
    store.index(make_doc("b", 2))
    payloads = store.scroll_payloads()
    assert len(payloads) == 7
    assert all("hidden" in p and "text_normalized" in p for p in payloads)


# --- errors and logs ----------------------------------------------------------------------------


def test_qdrant_down_raises_service_error():
    client = MagicMock()
    for name in ("count", "upsert", "query_points", "scroll", "collection_exists"):
        getattr(client, name).side_effect = ConnectionError("refused")
    s = QdrantStore(client, HashModels())
    flt = visibility_filter(make_ctx("lecteur"))
    with pytest.raises(ServiceError):
        s.hide("doc")
    with pytest.raises(ServiceError):
        s.index(make_doc("a"))
    with pytest.raises(ServiceError):
        s.vector_search(hash_vector("x"), flt, 5)
    with pytest.raises(ServiceError):
        s.recheck(["id"], flt)
    with pytest.raises(ServiceError):
        s.ensure_collection()


def test_logs_hold_no_text_or_title(store, caplog):
    caplog.set_level(logging.DEBUG)
    doc = make_doc("secret", texts=["نص سري جدا"])
    store.index(doc)
    store.show(doc[0].doc_id)
    store.vector_search(hash_vector("x"), visibility_filter(make_ctx("lecteur")), 5)
    store.hide("unknown")
    for record in caplog.records:
        if not record.name.startswith("src.retrieval"):
            continue
        dumped = record.getMessage() + " " + " ".join(str(v) for v in record.__dict__.values())
        assert "نص سري جدا" not in dumped
        assert doc[0].title not in dumped
