"""Tests for the web-search leak filter."""

import sys
from pathlib import Path

import pytest

SERVICE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_DIR))

from leak_filter import LeakFilter
from store import SQLiteLeakStore

KEY = b"test-leak-key"

INTERNAL_TEXT = (
    "تلتزم الوكالة الوطنية بحماية المعطيات الشخصية للمرتفقين وفق المذكرة الداخلية رقم 12"
)

LEAKING_QUERY = "بحماية المعطيات الشخصية للمرتفقين وفق"
GENERIC_QUERY = "ما هي شروط حماية المعطيات الشخصية في المغرب"


@pytest.fixture
def components(tmp_path: Path) -> tuple[SQLiteLeakStore, LeakFilter]:
    store = SQLiteLeakStore(tmp_path / "leak.sqlite3")
    leak_filter = LeakFilter(
        store,
        KEY,
        ngram=4,
        min_hits=3,
        max_df=20,
        overlap_threshold=0.2,
    )
    return store, leak_filter


def test_internal_query_is_detected(components) -> None:
    store, leak_filter = components
    from src.core.leak.fingerprint import fingerprints

    grams, refs = fingerprints(INTERNAL_TEXT, KEY)
    store.register("internal-doc", grams, refs)

    hits = leak_filter.leak_hits(LEAKING_QUERY)

    assert len(hits) == 2


def test_internal_query_is_blocked(components) -> None:
    store, leak_filter = components
    from src.core.leak.fingerprint import fingerprints

    grams, refs = fingerprints(INTERNAL_TEXT, KEY)
    store.register("internal-doc", grams, refs)

    blocked, hit_count = leak_filter.check(LEAKING_QUERY)

    assert blocked is True
    assert hit_count == 2


def test_generic_query_is_not_blocked(components) -> None:
    _, leak_filter = components

    blocked, hit_count = leak_filter.check(GENERIC_QUERY)

    assert blocked is False
    assert hit_count == 0


def test_public_document_prevents_blocking(components) -> None:
    store, leak_filter = components
    from src.core.leak.fingerprint import fingerprints

    grams, refs = fingerprints(INTERNAL_TEXT, KEY)
    store.register("internal-doc", grams, refs)

    public_grams, public_refs = fingerprints(
        "بحماية المعطيات الشخصية للمرتفقين وفق",
        KEY,
    )
    store.register("public-doc", public_grams, public_refs)
    store.set_blocking("public-doc", False)

    assert leak_filter.leak_hits(LEAKING_QUERY) == []


def test_reference_match_blocks_immediately(components) -> None:
    store, leak_filter = components
    from src.core.leak.fingerprint import fingerprints

    text = "دورية رقم 12/2025 الصادرة عن الوكالة الوطنية"
    grams, refs = fingerprints(text, KEY)
    store.register("internal-doc", grams, refs)

    query = "ما هو مضمون دورية رقم 12/2025"
    blocked, hit_count = leak_filter.check(query)

    assert blocked is True
    assert hit_count >= 1


def test_common_fingerprint_is_ignored(components) -> None:
    store, leak_filter = components
    from src.core.leak.fingerprint import fingerprints

    leak_filter.max_df = 2

    grams, refs = fingerprints(INTERNAL_TEXT, KEY)
    store.register("doc-1", grams, refs)
    store.register("doc-2", grams, refs)

    assert leak_filter.leak_hits(LEAKING_QUERY) == []

def test_unknown_query_is_not_blocked(components) -> None:
    _, leak_filter = components

    assert leak_filter.check("الطقس في مدينة الرباط اليوم") == (False, 0)


def test_invalid_configuration_is_rejected(tmp_path: Path) -> None:
    store = SQLiteLeakStore(tmp_path / "leak.sqlite3")

    with pytest.raises(ValueError):
        LeakFilter(store, KEY, ngram=0)


def test_min_hits_threshold_blocks_independently(components, monkeypatch) -> None:
    store, leak_filter = components
    import leak_filter as leak_filter_module

    def fake_fingerprints(text, key, ngram=4):
        return ["fp-1", "fp-2", "fp-3"], []

    monkeypatch.setattr(
        leak_filter_module,
        "fingerprints",
        fake_fingerprints,
    )

    store.register("internal-doc", ["fp-1", "fp-2", "fp-3"], [])

    query = (
        "un deux trois quatre cinq six sept huit neuf dix "
        "onze douze treize quatorze quinze seize dixsept "
        "dixhuit dixneuf vingt"
    )

    blocked, hit_count = leak_filter.check(query)

    assert hit_count == 3
    assert 3 / 17 < leak_filter.overlap_threshold
    assert blocked is True

def test_overlap_threshold_blocks_independently(components, monkeypatch) -> None:
    store, leak_filter = components
    import leak_filter as leak_filter_module

    def fake_fingerprints(text, key, ngram=4):
        return ["fp-1", "fp-2"], []

    monkeypatch.setattr(
        leak_filter_module,
        "fingerprints",
        fake_fingerprints,
    )

    store.register("internal-doc", ["fp-1", "fp-2"], [])

    query = "un deux trois quatre cinq six sept huit neuf dix"

    blocked, hit_count = leak_filter.check(query)

    assert hit_count == 2
    assert hit_count < leak_filter.min_hits
    assert 2 / 7 >= leak_filter.overlap_threshold
    assert blocked is True

def test_disabling_blocking_allows_previously_blocked_query(components) -> None:
    store, leak_filter = components
    from src.core.leak.fingerprint import fingerprints

    grams, refs = fingerprints(INTERNAL_TEXT, KEY)
    store.register("internal-doc", grams, refs)

    assert leak_filter.check(LEAKING_QUERY)[0] is True

    store.set_blocking("internal-doc", False)

    blocked, hit_count = leak_filter.check(LEAKING_QUERY)

    assert blocked is False
    assert hit_count == 0


def test_deleting_document_allows_previously_blocked_query(components) -> None:
    store, leak_filter = components
    from src.core.leak.fingerprint import fingerprints

    grams, refs = fingerprints(INTERNAL_TEXT, KEY)
    store.register("internal-doc", grams, refs)

    assert leak_filter.check(LEAKING_QUERY)[0] is True

    store.delete("internal-doc")

    blocked, hit_count = leak_filter.check(LEAKING_QUERY)

    assert blocked is False
    assert hit_count == 0
