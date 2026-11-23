"""BM25 tokenizer (P2 spec P2-20, P2-22, §6.6).

The input is already normalized by normalize_ar (P1): this module never normalizes.
The same tokenize() is used for chunks and for queries.
"""

from pathlib import Path

STOPWORDS_PATH = Path(__file__).with_name("stopwords_ar.txt")

PREFIXES: tuple[str, ...] = ("وال", "بال", "كال", "فال", "لل", "ال", "و")
SUFFIXES: tuple[str, ...] = ("ات", "ون", "ين", "ها", "هم", "ه")
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
    """Light stemmer (P2-22, SHOULD). Minimum version: returns the token unchanged.

    The full version removes at most one prefix among PREFIXES and one suffix among
    SUFFIXES, keeping at least MIN_STEM letters.

    Args:
        token: A normalized token.

    Returns:
        The stemmed token.
    """
    return token


def tokenize(normalized: str) -> list[str]:
    """Splits normalized text into BM25 tokens (P2-20).

    Split on spaces, drop 1-character tokens except digits, drop stopwords, then light_stem.

    Args:
        normalized: Text already passed through normalize_ar.

    Returns:
        The tokens, in order. Empty if nothing remains (e.g. only stopwords).
    """
    tokens: list[str] = []
    for token in normalized.split():
        if (len(token) < 2 and not token.isdigit()) or token in STOPWORDS:
            continue
        tokens.append(light_stem(token))
    return tokens
