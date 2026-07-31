"""Cited-vs-canonical metadata comparison (#9) — fuzzy on purpose.

The failure mode this catches is a real DOI attached to a different paper.
The failure mode it must *not* create is calling ordinary citation sloppiness
a fabrication: abbreviated venues, initials instead of given names, a
subtitle dropped after the colon, and ±1 year for online-first publication
are all normal, and all of them grade as *minor* at worst.

Thresholds live in one place (the module constants) so they can be tuned
against fixtures without hunting through the check code. stdlib only —
``difflib`` plus token overlap gets us there without a new dependency.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import StrEnum

from slopchecker.checks.providers import SourceRecord
from slopchecker.pipeline.citations import first_surname
from slopchecker.pipeline.citations.models import ReferenceEntry

# Title similarity: at or above STRONG the works are the same; below WEAK
# they are different works. Between them is "minor discrepancy" territory.
TITLE_STRONG = 0.90
TITLE_WEAK = 0.70
VENUE_STRONG = 0.85
VENUE_WEAK = 0.55
# Online-first means the cited year and the issue year legitimately differ.
YEAR_TOLERANCE = 1

_ARTICLES = ("the ", "a ", "an ")
_PUNCT = re.compile(r"[^\w\s]+")
_WS = re.compile(r"\s+")
_STOPWORDS = frozenset(
    "the a an of and or for in on to with by from at as is are its their".split()
)
# Whole words that flip a title's meaning. Kept deliberately small: these are
# matched as tokens, never as substrings, so "non" here would still not fire
# on "nonlinear".
_NEGATIONS = frozenset("not no never without cannot none nor neither".split())
# Surname particles. A citation that drops "van der" is citing the same
# person, and treating it as a different author turned an ordinary Dutch or
# German name into a "different work entirely" verdict.
_PARTICLES = frozenset(
    "van von der den de del della di da dos das du la le les el al bin ibn mac mc o".split()
)


class Grade(StrEnum):
    """Per-field and overall grades. #9's vocabulary, as a closed enum."""

    matches = "matches"
    minor = "minor"
    different = "different"
    unknown = "unknown"  # nothing to compare — a coverage gap, not a defect


def normalize(text: str | None) -> str:
    """Casefolded, accent-stripped, punctuation-free, article-free."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_ish = "".join(c for c in decomposed if not unicodedata.combining(c))
    cleaned = _WS.sub(" ", _PUNCT.sub(" ", ascii_ish)).strip().casefold()
    for article in _ARTICLES:
        if cleaned.startswith(article):
            return cleaned[len(article) :]
    return cleaned


def similarity(left: str | None, right: str | None) -> float:
    """0.0–1.0 similarity: sequence ratio and content-word overlap, best of.

    Two measures because they fail differently — the sequence ratio handles
    small edits, the token overlap handles reordering and dropped subtitles.
    """
    a, b = normalize(left), normalize(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ratio = SequenceMatcher(None, a, b).ratio()
    tokens_a = {t for t in a.split() if t not in _STOPWORDS}
    tokens_b = {t for t in b.split() if t not in _STOPWORDS}
    if tokens_a and tokens_b:
        # Jaccard, not containment. Dividing by min() would score any title
        # whose words are a subset of the other's a perfect 1.0 — so
        # "Thermometry of a living cell nucleus" would "match" the paper it
        # merely extends. Truncated subtitles are handled explicitly in
        # title_similarity instead, where the truncation is the point.
        jaccard = len(tokens_a & tokens_b) / len(tokens_a | tokens_b)
        ratio = max(ratio, jaccard)
    return ratio


def _head(title: str) -> str:
    """Everything before the subtitle separator. Colons are the common case,
    but em- and en-dashes separate subtitles just as often in practice."""
    for sep in (":", "—", "–", " - "):
        if sep in title:
            return title.split(sep)[0]
    return title


def _negations(text: str | None) -> set[str]:
    """Whole-word negations only — "non" must not match "nonlinear"."""
    return {t for t in normalize(text).split() if t in _NEGATIONS}


def title_similarity(cited: str | None, canonical: str | None) -> float:
    """Title similarity that tolerates a truncated subtitle.

    "Nanometre-scale thermometry" vs "Nanometre-scale thermometry in a living
    cell" is a citation that dropped the tail, not a different paper — so the
    head of each title is compared as well as the whole thing.
    """
    best = similarity(cited, canonical)
    for a, b in ((cited, canonical), (canonical, cited)):
        head = _head(a or "")
        if head and head != a:
            best = max(best, similarity(head, _head(b or "")), similarity(head, b))
    return best


def negation_mismatch(cited: str | None, canonical: str | None) -> bool:
    """True when one title negates and the other doesn't.

    On a short title one inserted word barely moves any similarity measure:
    "Attention Is All You Need" vs "Attention Is Not All You Need" scores
    0.93 and sailed through as a clean match — while being, of course, the
    opposite paper. Titles are short and negations are load-bearing, so
    asymmetric negation is treated as a signal in its own right rather than
    left to the ratio.
    """
    return _negations(cited) != _negations(canonical)


def grade_similarity(score: float, strong: float, weak: float) -> Grade:
    if score >= strong:
        return Grade.matches
    if score >= weak:
        return Grade.minor
    return Grade.different


def grade_year(cited: int | None, canonical: int | None) -> Grade:
    if cited is None or canonical is None:
        return Grade.unknown
    if cited == canonical:
        return Grade.matches
    if abs(cited - canonical) <= YEAR_TOLERANCE:
        return Grade.minor  # online-first / issue-date drift
    return Grade.different


def _core_surname(surname: str) -> str:
    """Surname with leading particles dropped: "van der Berg" → "berg"."""
    tokens = [t for t in normalize(surname).split() if t]
    while len(tokens) > 1 and tokens[0] in _PARTICLES:
        tokens.pop(0)
    return " ".join(tokens)


def grade_author(cited_surname: str | None, canonical: SourceRecord) -> Grade:
    """First-author surname against the canonical author list.

    Cited-first-author appearing anywhere in the real author list is a
    *minor* discrepancy (wrong author ordered first), not a different work;
    absent entirely is a real signal.

    Particles are compared both ways: "Berg" for "van der Berg" is how half
    the world's bibliographies alphabetize, and scoring it as a different
    author was enough — combined with a merely-uncertain title — to push an
    honest citation all the way to "different work entirely".
    """
    cited = normalize(cited_surname)
    if not cited or not canonical.surnames:
        return Grade.unknown
    surnames = [normalize(s) for s in canonical.surnames]
    cores = [_core_surname(s) for s in canonical.surnames]
    cited_core = _core_surname(cited_surname or "")
    if surnames and (cited == surnames[0] or cited_core == cores[0]):
        return Grade.matches
    if cited in surnames or cited_core in cores:
        return Grade.minor
    if any(similarity(cited, s) >= 0.85 for s in surnames):
        return Grade.minor  # transliteration or hyphenation drift
    return Grade.different


def grade_venue(cited: str | None, canonical: str | None) -> Grade:
    """Venue comparison that forgives abbreviation ("J. Am. Chem. Soc.")."""
    if not cited or not canonical:
        return Grade.unknown
    a, b = normalize(cited), normalize(canonical)
    if a in b or b in a:
        return Grade.matches
    if _initials(a) == _initials(b) or a == _initials(b) or b == _initials(a):
        return Grade.matches
    return grade_similarity(similarity(a, b), VENUE_STRONG, VENUE_WEAK)


def _initials(text: str) -> str:
    return "".join(word[0] for word in text.split() if word not in _STOPWORDS)


@dataclass(frozen=True)
class MetadataMatch:
    """Field-by-field comparison plus the overall grade.

    ``fields`` is what the report shows: a reviewer wants to see *which* part
    disagreed, not a single opaque score.
    """

    grade: Grade
    title_score: float
    fields: dict[str, str]
    canonical: SourceRecord | None
    cited_title: str | None = None

    @property
    def is_different_work(self) -> bool:
        return self.grade is Grade.different

    def as_evidence(self) -> dict:
        evidence: dict = {
            "grade": str(self.grade),
            "fields": self.fields,
            "title_similarity": round(self.title_score, 3),
            "cited_title": self.cited_title,
        }
        if self.canonical is not None:
            evidence["canonical"] = self.canonical.as_evidence()
        return evidence

    def summary(self) -> str:
        """One line for ``Finding.note`` — descriptive, never accusatory."""
        if self.grade is Grade.matches:
            return "Cited metadata matches the canonical record."
        if self.grade is Grade.unknown:
            return "Not enough parsed metadata in the reference to compare."
        disagreeing = [f for f, g in self.fields.items() if g in ("minor", "different")]
        if self.grade is Grade.different:
            return f"Identifier resolves to a different work ({', '.join(disagreeing)} differ)."
        return f"Minor discrepancy against the canonical record ({', '.join(disagreeing)})."


def compare(ref: ReferenceEntry, canonical: SourceRecord | None) -> MetadataMatch:
    """Grade one reference against the canonical record for its identifier.

    No canonical record, or no parsed title to compare, grades ``unknown`` —
    the gray-literature case. Reporting low confidence there is the whole
    point; a book the providers have never heard of is not a fake book.
    """
    if canonical is None:
        return MetadataMatch(Grade.unknown, 0.0, {}, None, ref.title)
    if not ref.title:
        return MetadataMatch(Grade.unknown, 0.0, {}, canonical, None)

    title_score = title_similarity(ref.title, canonical.title)
    title_grade = grade_similarity(title_score, TITLE_STRONG, TITLE_WEAK)
    if negation_mismatch(ref.title, canonical.title) and title_grade is Grade.matches:
        # Surfaced for a human rather than escalated to "different work": the
        # tool's job is to raise the signal, not to decide the citation is
        # wrong on the strength of one token.
        title_grade = Grade.minor
    fields = {"title": str(title_grade)}

    # first_surname (#7) already knows both author shapes — "Surname, I. I."
    # and "I. I. Surname". Splitting on the comma ourselves turned "G. Kucsko"
    # into a surname of "G. Kucsko" and graded a correct citation as sloppy.
    author = grade_author(first_surname(ref), canonical)
    if author is not Grade.unknown:
        fields["author"] = str(author)
    year = grade_year(ref.year, canonical.year)
    if year is not Grade.unknown:
        fields["year"] = str(year)
    venue = grade_venue(ref.venue, canonical.venue)
    if venue is not Grade.unknown:
        fields["venue"] = str(venue)

    return MetadataMatch(
        grade=_overall(title_grade, author, year),
        title_score=title_score,
        fields=fields,
        canonical=canonical,
        cited_title=ref.title,
    )


def _overall(title: Grade, author: Grade, year: Grade) -> Grade:
    """Title carries the verdict; author and year can only escalate a doubt.

    Venue never decides on its own: abbreviations, imprints, and preprint
    servers disagree with the canonical record constantly on honest citations.
    """
    if title is Grade.different:
        return Grade.different
    if title is Grade.minor:
        # An uncertain title plus a wrong first author is the "real DOI,
        # invented reference" shape. An uncertain title alone is sloppiness.
        return Grade.different if author is Grade.different else Grade.minor
    if author is Grade.different or year is Grade.different:
        return Grade.minor
    if author is Grade.minor or year is Grade.minor:
        return Grade.minor
    return Grade.matches
