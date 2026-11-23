"""BM25 tokenizer (P2 spec P2-20, P2-22, §6.6).

The input is already normalized by normalize_ar (P1): this module never normalizes.
The same tokenize() is used for chunks and for queries.

Light stemmer (P2-22): two rules of the spec's list are left out, after measuring them on the
corpus (18 public and 5 internal documents, 1,372 chunks):

- the prefix ``و`` alone: in many frequent nouns it is part of the word, not the conjunction
  (``وثيقه`` → ``ثيقه``, ``وزير`` → ``زير``, ``وكيل`` → ``كيل``). ``وال`` still covers "و + article";
- the suffix ``ه``: after normalize_ar it is mostly the ``ة`` of feminine nouns, so the rule cut
  almost every feminine noun and merged different words (``معالجه`` "processing" → ``معالج``
  "processor").

On 12 test questions with BM25 alone, this variant ranked the expected article as well as or
better than the full list on every question.
"""

from pathlib import Path

STOPWORDS_PATH = Path(__file__).with_name("stopwords_ar.txt")

# Longest first: "والقانون" loses "وال", not just "ال".
PREFIXES: tuple[str, ...] = ("وال", "بال", "كال", "فال", "لل", "ال")
SUFFIXES: tuple[str, ...] = ("ات", "ون", "ين", "ها", "هم")
MIN_STEM = 3


def load_stopwords(path: Path = STOPWORDS_PATH) -> frozenset[str]:
    """Reads one normalized word per line (UTF-8). Blank lines are ignored.

    Args:
        path: The stopword file. Also read by P4 (P4-14).

    Returns:
        The set of stopwords.
    """
    with path.open(encoding="utf-8-sig") as f:
        return frozenset(line.strip() for line in f if line.strip())


STOPWORDS: frozenset[str] = load_stopwords()


def light_stem(token: str) -> str:
    """Light stemmer (P2-22, SHOULD).

    Removes at most one prefix among PREFIXES (the first that matches, longest first), then at
    most one suffix among SUFFIXES, each only if at least MIN_STEM letters remain. Chunks and
    queries go through the same function, so an odd-looking stem (``قانون`` → ``قان``) still
    matches on both sides.

    Args:
        token: A normalized token.

    Returns:
        The stemmed token, e.g. ``والبيانات`` → ``بيان``, ``للقانون`` → ``قان``; ``الله`` and
        ``وزير`` are unchanged.
    """
    for prefix in PREFIXES:
        if token.startswith(prefix) and len(token) - len(prefix) >= MIN_STEM:
            token = token[len(prefix) :]
            break
    for suffix in SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= MIN_STEM:
            token = token[: -len(suffix)]
            break
    return token


def tokenize(normalized: str) -> list[str]:
    """Splits normalized text into BM25 tokens (P2-20).

    Split on spaces, drop 1-character tokens except digits, drop stopwords, light_stem, then drop
    stopwords again: stemming can turn a word into a stopword (``عليها`` → ``علي``), which would
    otherwise come back into the index.

    Args:
        normalized: Text already passed through normalize_ar.

    Returns:
        The tokens, in order. Empty if nothing remains (e.g. only stopwords).
    """
    tokens: list[str] = []
    for token in normalized.split():
        if (len(token) < 2 and not token.isdigit()) or token in STOPWORDS:
            continue
        stem = light_stem(token)
        if stem in STOPWORDS:
            continue
        tokens.append(stem)
    return tokens
