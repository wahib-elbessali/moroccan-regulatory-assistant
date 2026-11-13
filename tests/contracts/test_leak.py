"""Contract tests for the ``LeakIndex`` Protocol (00-shared §6.4, §9; P6 spec §8).

Each test runs on both implementations: ``FakeLeakIndex`` and the real one. The Protocol has no
read method, so what the index holds is read through ``hits``, which only the fake has. On the
real index, a test that needs it is skipped: there the same checks go through the ``web-search``
``/search`` endpoint (P6 spec §8, T7, T9, T10).
"""

import importlib
from collections.abc import Callable, Iterator

import pytest

from src.core.contracts import LeakIndex
from src.core.contracts.fakes.leak import FakeLeakIndex

INTERNAL_DOC = "internal-doc"
PUBLIC_DOC = "public-doc"
UNKNOWN_DOC = "never-registered"
PROBE_DOC = "contract-probe"  # deleted once to check web-search answers; never registered

INTERNAL_TEXT = (
    "تلتزم الوكالة الوطنية بحماية المعطيات الشخصية للمرتفقين وفق المذكرة الداخلية رقم 12"
)
PUBLIC_TEXT = "تلتزم الوكالة الوطنية بنشر التقرير السنوي في الجريدة الرسمية"

# Four words copied from INTERNAL_TEXT only: two 4-grams found in no public document.
LEAKING_QUERY = "بحماية المعطيات الشخصية للمرتفقين وفق"
# The first four words of both texts: a phrase public law also contains.
SHARED_QUERY = "تلتزم الوكالة الوطنية"
SHARED_4GRAM_QUERY = "تلتزم الوكالة الوطنية بحماية"
GENERIC_QUERY = "ما هي شروط حماية المعطيات الشخصية في المغرب"

REAL_FACTORY = "real_leak_index"  # src/core/leak/__init__.py:real_leak_index() (00-shared §9)


def _real_leak_index() -> LeakIndex:
    """The real implementation, or a skip while it does not exist or cannot reach web-search."""
    module = importlib.import_module("src.core.leak")
    factory: Callable[[], LeakIndex] | None = getattr(module, REAL_FACTORY, None)
    if factory is None:
        pytest.skip(f"{REAL_FACTORY}() does not exist yet")
    try:
        impl = factory()
        impl.delete(PROBE_DOC)  # creating the client does not contact web-search; this does
    except Exception as exc:  # web-search unreachable, missing LEAK_HMAC_KEY…
        pytest.skip(f"real leak index unusable ({type(exc).__name__})")
    return impl


@pytest.fixture(params=["fake", "real"])
def index(request: pytest.FixtureRequest) -> Iterator[LeakIndex]:
    """One ``LeakIndex`` implementation, cleaned of this module's documents before and after."""
    impl: LeakIndex = FakeLeakIndex() if request.param == "fake" else _real_leak_index()
    for doc_id in (INTERNAL_DOC, PUBLIC_DOC):
        impl.delete(doc_id)
    yield impl
    for doc_id in (INTERNAL_DOC, PUBLIC_DOC):
        impl.delete(doc_id)


def _hits(index: LeakIndex, query: str) -> int:
    """The query's hit count, read through the fake's ``hits``; a skip on the real index."""
    hits: Callable[[str], int] | None = getattr(index, "hits", None)
    if hits is None:
        pytest.skip("the real index is read through web-search /search (P6 T7, T9, T10)")
    return hits(query)


# --- Idempotence (P6-31) ----------------------------------------------------------------------


def test_register_twice_leaves_the_same_state(index: LeakIndex) -> None:
    index.register(INTERNAL_DOC, INTERNAL_TEXT)
    first = _hits(index, LEAKING_QUERY)
    index.register(INTERNAL_DOC, INTERNAL_TEXT)
    assert _hits(index, LEAKING_QUERY) == first > 0


def test_set_blocking_twice_is_not_an_error(index: LeakIndex) -> None:
    index.register(INTERNAL_DOC, INTERNAL_TEXT)
    index.set_blocking(INTERNAL_DOC, False)
    index.set_blocking(INTERNAL_DOC, False)
    assert _hits(index, LEAKING_QUERY) == 0


def test_delete_twice_is_not_an_error(index: LeakIndex) -> None:
    index.register(INTERNAL_DOC, INTERNAL_TEXT)
    index.delete(INTERNAL_DOC)
    index.delete(INTERNAL_DOC)
    assert _hits(index, LEAKING_QUERY) == 0


def test_unknown_document_is_ignored(index: LeakIndex) -> None:
    index.set_blocking(UNKNOWN_DOC, True)
    index.delete(UNKNOWN_DOC)
    assert _hits(index, LEAKING_QUERY) == 0


# --- What blocks (P6-31, P6-33) ---------------------------------------------------------------


def test_registered_document_is_blocking(index: LeakIndex) -> None:
    index.register(INTERNAL_DOC, INTERNAL_TEXT)
    assert _hits(index, LEAKING_QUERY) == 2


def test_set_blocking_turns_the_document_off_and_on(index: LeakIndex) -> None:
    """T9: a document set non-blocking no longer blocks; set blocking again, it does."""
    index.register(INTERNAL_DOC, INTERNAL_TEXT)
    index.set_blocking(INTERNAL_DOC, False)
    assert _hits(index, LEAKING_QUERY) == 0
    index.set_blocking(INTERNAL_DOC, True)
    assert _hits(index, LEAKING_QUERY) == 2


def test_register_again_makes_the_document_blocking(index: LeakIndex) -> None:
    index.register(INTERNAL_DOC, INTERNAL_TEXT)
    index.set_blocking(INTERNAL_DOC, False)
    index.register(INTERNAL_DOC, INTERNAL_TEXT)
    assert _hits(index, LEAKING_QUERY) == 2


def test_deleted_document_no_longer_blocks(index: LeakIndex) -> None:
    """T10."""
    index.register(INTERNAL_DOC, INTERNAL_TEXT)
    index.delete(INTERNAL_DOC)
    assert _hits(index, LEAKING_QUERY) == 0


def test_phrase_also_in_a_public_document_never_blocks(index: LeakIndex) -> None:
    """T7: a 4-gram found in a non-blocking document is not a hit."""
    index.register(INTERNAL_DOC, INTERNAL_TEXT)
    index.register(PUBLIC_DOC, "تلتزم الوكالة الوطنية بحماية الحقوق")
    index.set_blocking(PUBLIC_DOC, False)
    assert _hits(index, SHARED_4GRAM_QUERY) == 0
    assert _hits(index, LEAKING_QUERY) == 2


def test_query_shorter_than_a_4gram_has_no_hit(index: LeakIndex) -> None:
    index.register(INTERNAL_DOC, INTERNAL_TEXT)
    index.register(PUBLIC_DOC, PUBLIC_TEXT)
    assert _hits(index, SHARED_QUERY) == 0


def test_generic_question_has_no_hit(index: LeakIndex) -> None:
    index.register(INTERNAL_DOC, INTERNAL_TEXT)
    assert _hits(index, GENERIC_QUERY) == 0


def test_query_is_normalized_like_the_document(index: LeakIndex) -> None:
    """Diacritics and alef variants do not hide a copied sentence (normalize_ar, P1)."""
    index.register(INTERNAL_DOC, INTERNAL_TEXT)
    assert _hits(index, "بِحِمَايَةِ المعطيات الشخصية للمرتفقين") == 1


# --- Fake only --------------------------------------------------------------------------------


def test_fake_rejects_an_ngram_below_one() -> None:
    with pytest.raises(ValueError):
        FakeLeakIndex(ngram=0)
