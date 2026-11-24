"""BM25 tokenizer (P2 spec P2-20, P2-22, §6.6).

The input is already normalized by normalize_ar (P1): this module never normalizes.
The same tokenize() is used for chunks and for queries.

Light stemmer (P2-22), measured on the corpus (18 public and 5 internal documents):

- the prefix ``و`` alone is the conjunction "and" in most words (``وحمايه`` → ``حمايه``), but in
  some frequent words it is part of the word (``وزير`` "minister", ``وثيقه`` "document"). Those
  words are listed in WAW_WORDS, built from the most frequent words of the corpus that start
  with ``و``, and keep their ``و``;
- the suffix ``ه`` is left out: after normalize_ar it is mostly the ``ة`` of feminine nouns, so
  the rule cut almost every feminine noun and merged different words (``معالجه`` "processing"
  → ``معالج`` "processor").
"""

from pathlib import Path

STOPWORDS_PATH = Path(__file__).with_name("stopwords_ar.txt")

# Longest first: "والقانون" loses "وال", not just "ال" or "و".
PREFIXES: tuple[str, ...] = ("وال", "بال", "كال", "فال", "لل", "ال", "و")
SUFFIXES: tuple[str, ...] = ("ات", "ون", "ين", "ها", "هم")
MIN_STEM = 3

# Normalized words whose first و belongs to the word: the lone prefix و is never removed from
# them. Built from the words of the corpus that start with و and appear at least 3 times.
# fmt: off
WAW_WORDS: frozenset[str] = frozenset(
    {
        "واحد", "واحده", "واحدا",  # one
        "وحده", "وحدها",  # unit, alone
        "وزير", "وزيره",  # minister
        "وزاره",  # ministry
        "وثيقه", "وثيقتي", "وثائق",  # document
        "وسيله", "وسائل",  # means
        "وضعيه",  # situation
        "وارث", "ورثه",  # heir
        "وكيل",  # agent, proxy
        "وكاله",  # agency, power of attorney
        "ولاده", "ولادته",  # birth
        "وفاه", "وفاته", "وفاتهم",  # death
        "وقعه", "وقعت", "وقوع", "وقائع", "واقعه",  # signed, occurred, facts
        "وقائيه",  # preventive
        "وجود",  # existence
        "وجبت", "وجوبا", "واجب",  # obligation
        "وجدت",  # was found
        "واضح", "واضحه",  # clear
        "وفقا",  # according to
        "وليه", "ولايه",  # guardian, guardianship
        "وافق",  # agreed
        "وظيفه",  # function, job
        "وطنيه",  # national
        "وصيه", "وصيته",  # will (testament)
        "ولوج",  # access
        "وادي",  # valley
        "ورزازات", "ورززات",  # Ouarzazate (the second is an OCR spelling found in the corpus)
    }
)
# fmt: on


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
    most one suffix among SUFFIXES, each only if at least MIN_STEM letters remain. The lone
    prefix ``و`` is not removed from a word of WAW_WORDS. Chunks and queries go through the same
    function, so an odd-looking stem (``قانون`` → ``قان``) still matches on both sides.

    Args:
        token: A normalized token.

    Returns:
        The stemmed token, e.g. ``والبيانات`` → ``بيان``, ``للقانون`` → ``قان``, ``وحمايه`` →
        ``حمايه``; ``الله`` and ``وزير`` are unchanged.
    """
    for prefix in PREFIXES:
        if prefix == "و" and token in WAW_WORDS:
            continue
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
