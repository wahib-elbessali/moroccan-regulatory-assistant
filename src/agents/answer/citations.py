"""Source numbering, claim splitting and citation construction for P4."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape

from src.core.contracts.models import Citation, Passage, WebResult

_MARKER_RE = re.compile(r"\[(\d+)\]")
_CLAIM_BOUNDARY_RE = re.compile(r"(?<=[.!؟?])(?=\s|$)|\r?\n+")
_ENDING_PUNCTUATION_RE = re.compile(r"([.!؟?])([\"'’”»)]*)$")


@dataclass(frozen=True)
class Source:
    """A numbered passage or web result given to the writer and judge."""

    number: int
    kind: str
    title: str
    text: str
    doc_id: str | None = None
    article: str | None = None
    page: int | None = None
    source: str | None = None
    date: str | None = None
    url: str | None = None

    def prompt_tag(self) -> str:
        attrs = [f'n="{self.number}"', f'type="{escape(self.kind, quote=True)}"']
        attrs.append(f'title="{escape(self.title, quote=True)}"')
        if self.kind == "corpus":
            attrs.extend(
                [
                    f'article="{escape(self.article or "", quote=True)}"',
                    f'page="{self.page if self.page is not None else ""}"',
                ]
            )
        else:
            attrs.append(f'url="{escape(self.url or "", quote=True)}"')
        return f"<source {' '.join(attrs)}>{escape(self.text)}</source>"

    def citation(self, excerpt: str) -> Citation:
        if self.kind == "corpus":
            return Citation(
                doc_id=self.doc_id,
                url=None,
                title=self.title,
                article=self.article,
                page=self.page,
                source=self.source,
                date=self.date,
                excerpt=excerpt,
            )
        return Citation(
            doc_id=None,
            url=self.url,
            title=self.title,
            article=None,
            page=None,
            source=None,
            date=None,
            excerpt=excerpt,
        )


@dataclass
class Claim:
    """One sentence produced by the writer and its verification state."""

    text: str
    cited: list[int]
    supported: bool = False
    reason: str | None = None
    excerpt: str | None = None
    source_n: int | None = None


def build_sources(passages: list[Passage], web: list[WebResult]) -> list[Source]:
    """Number corpus passages first and web results second, preserving input order."""
    sources: list[Source] = []
    for number, passage in enumerate(passages, start=1):
        chunk = passage.chunk
        sources.append(
            Source(
                number=number,
                kind="corpus",
                title=chunk.title,
                text=chunk.text,
                doc_id=chunk.doc_id,
                article=chunk.article,
                page=chunk.page_start,
                source=chunk.source,
                date=chunk.date,
            )
        )
    offset = len(sources)
    for index, result in enumerate(web, start=1):
        sources.append(
            Source(
                number=offset + index,
                kind="web",
                title=result.title,
                text=result.snippet,
                url=result.url,
            )
        )
    return sources


def split_claims(text: str, valid_sources: set[int]) -> list[Claim]:
    """Split on sentence endings or line breaks and keep only valid source markers."""
    claims: list[Claim] = []
    for fragment in _CLAIM_BOUNDARY_RE.split(text):
        fragment = fragment.strip()
        if not fragment:
            continue
        cited: list[int] = []
        for match in _MARKER_RE.finditer(fragment):
            number = int(match.group(1))
            if number in valid_sources and number not in cited:
                cited.append(number)
        claims.append(Claim(text=fragment, cited=cited))
    return claims


def render_claim(claim: Claim, new_number: int) -> str:
    """Remove draft markers and add the verified, renumbered marker at sentence end."""
    text = _MARKER_RE.sub("", claim.text)
    text = re.sub(r"\s+", " ", text).strip()
    match = _ENDING_PUNCTUATION_RE.search(text)
    marker = f"[{new_number}]"
    if match:
        end = match.start(1)
        return f"{text[:end].rstrip()} {marker}{text[end:]}"
    return f"{text} {marker}".strip()


def renumber(kept: list[Claim], sources: list[Source]) -> tuple[str, list[Citation]]:
    """Keep one checked source per claim and assign citation IDs by first use."""
    by_number = {source.number: source for source in sources}
    citation_numbers: dict[int, int] = {}
    excerpts: dict[int, list[str]] = {}
    output_claims: list[str] = []

    for claim in kept:
        source_number = claim.source_n
        if source_number is None or claim.excerpt is None or source_number not in by_number:
            continue
        if source_number not in citation_numbers:
            citation_numbers[source_number] = len(citation_numbers) + 1
            excerpts[source_number] = []
        if claim.excerpt not in excerpts[source_number]:
            excerpts[source_number].append(claim.excerpt)
        output_claims.append(render_claim(claim, citation_numbers[source_number]))

    citations = [
        by_number[number].citation(" … ".join(excerpts[number])) for number in citation_numbers
    ]
    return " ".join(output_claims), citations


def checked_excerpt(excerpt: str, source_text: str, min_chars: int) -> str | None:
    """Return a verifiable excerpt copied from the source, or ``None``."""
    from src.ingestion.normalize import normalize_ar  # P1 owns normalization.

    sentences = [part for part in _CLAIM_BOUNDARY_RE.split(excerpt) if part.strip()]
    if len(sentences) > 1:
        return None

    normalized_excerpt = normalize_ar(excerpt)
    if len(normalized_excerpt) < min_chars:
        return None
    if normalized_excerpt not in normalize_ar(source_text):
        return None
    if excerpt in source_text:
        return excerpt

    # Normalization may make a model's copy differ from the original glyphs. In that case,
    # store the source sentence containing the normalized match, never the model's paraphrase.
    for sentence in _CLAIM_BOUNDARY_RE.split(source_text):
        candidate = sentence.strip()
        if normalized_excerpt in normalize_ar(candidate):
            return candidate if len(normalize_ar(candidate)) >= min_chars else None
    return None


def cited_source_text(claims: list[Claim], sources: list[Source]) -> list[Source]:
    """Return only sources cited by at least one claim, in their original order."""
    wanted = {number for claim in claims for number in claim.cited}
    return [source for source in sources if source.number in wanted]
