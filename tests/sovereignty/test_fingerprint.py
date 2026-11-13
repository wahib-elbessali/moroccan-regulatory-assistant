"""Unit tests for leak fingerprints (P6-29, P6-30, P6-35)."""

import re

import pytest

from src.core.contracts.errors import ServiceError
from src.core.leak.fingerprint import fingerprints, hmac16, load_hmac_key

KEY = b"test-leak-key"
HEX16 = re.compile(r"^[0-9a-f]{16}$")

SIX_WORDS = "تلتزم الوكالة الوطنية بحماية المعطيات الشخصية"


def test_every_fingerprint_is_16_hex_characters() -> None:
    """T15: what leaves api holds no text, only 16-character hex strings."""
    grams, refs = fingerprints(SIX_WORDS + " رقم 12/2025", KEY)
    assert grams and refs
    assert all(HEX16.match(fp) for fp in grams + refs)


def test_one_fingerprint_per_distinct_4gram() -> None:
    grams, refs = fingerprints(SIX_WORDS, KEY)
    assert len(grams) == 3  # 6 words -> 3 runs of 4
    assert refs == []


def test_repeated_4grams_are_counted_once() -> None:
    grams, _ = fingerprints("ا ب ج د ا ب ج د", KEY)
    assert len(grams) == len(set(grams)) == 4


def test_text_shorter_than_a_4gram_has_no_gram() -> None:
    assert fingerprints("تلتزم الوكالة الوطنية", KEY) == ([], [])


def test_same_text_and_key_give_the_same_fingerprints() -> None:
    assert fingerprints(SIX_WORDS, KEY) == fingerprints(SIX_WORDS, KEY)


def test_another_key_gives_other_fingerprints() -> None:
    assert set(fingerprints(SIX_WORDS, KEY)[0]).isdisjoint(fingerprints(SIX_WORDS, b"other")[0])


def test_text_is_normalized_before_hashing() -> None:
    """Diacritics and alef variants give the same fingerprints as the plain text."""
    plain = "بحماية المعطيات الشخصية للمرتفقين"
    marked = "بِحِمَايَةِ المعطيات الشخصية للمرتفقين"
    assert fingerprints(marked, KEY) == fingerprints(plain, KEY)


def test_reference_is_fingerprinted_with_its_prefix() -> None:
    """P6-30: "دورية رقم 12/2025" gives the reference "ref:رقم 12 2025"."""
    _, refs = fingerprints("دورية رقم 12/2025 الصادرة عن الوكالة", KEY)
    assert refs == [hmac16(KEY, "ref:رقم 12 2025")]


def test_reference_with_arabic_digits_matches_ascii_digits() -> None:
    """T8 relies on this: "رقم ١٢/٢٠٢٥" and "رقم 12/2025" are the same reference."""
    assert fingerprints("رقم ١٢/٢٠٢٥", KEY)[1] == fingerprints("رقم 12/2025", KEY)[1]


def test_reference_with_adad_is_found() -> None:
    _, refs = fingerprints("القرار عدد 2.19.300", KEY)
    assert refs == [hmac16(KEY, "ref:عدد 2 19 300")]


def test_load_hmac_key_reads_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEAK_HMAC_KEY", "abc")
    assert load_hmac_key() == b"abc"


@pytest.mark.parametrize("value", [None, ""])
def test_load_hmac_key_refuses_a_missing_key(
    monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    if value is None:
        monkeypatch.delenv("LEAK_HMAC_KEY", raising=False)
    else:
        monkeypatch.setenv("LEAK_HMAC_KEY", value)
    with pytest.raises(ServiceError):
        load_hmac_key()
