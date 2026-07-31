"""Tagging: topics, document type, and submitter type (#15).

Routing is half the value for a funder: which program officer should read this,
is it a grant application or a blog post at all, and is the applicant a
university, a nonprofit, a company, or an individual. This check answers those
three questions from the document text alone — deterministic tier, no LLM and no
network, so it runs on a keyless checkout and is trivially auditable.

Design (decided on #15):

- **Pure functions first.** ``detect_doc_type`` / ``infer_submitter_type`` /
  ``tag_topics`` are importable on their own. ``detect_doc_type`` is the seam
  the AC asks for — other checks gate on document kind via the registry's
  ``applies_to`` hook, e.g. ``applies_to=lambda doc: detect_doc_type(doc).kind
  in {"grant_application", "think_tank_report"}``.

- **Categorical values are evidence, not results.** ``LedgerRow.result`` is
  strictly ``bool | int | float`` — a tag string can't live there. So the
  ledger carries the machine-scoreable rollups (doc-type confidence as a float,
  topic count as an int, submitter-type-identified as a bool) and the actual
  tags ride in quote-anchored ``Finding`` evidence. No change to the #3 model.

- **Conservative by construction.** Every inference reports a confidence and
  attaches the exact phrase it matched. No signal → ``kind="unknown"`` at
  confidence 0.0, never a guess. A mis-tagged applicant type could route a
  proposal to the wrong reviewer, so the tool states what it saw and how sure
  it is, and leaves the call to a human.

The taxonomy is data, not code: replace it wholesale by pointing
``SLOPCHECKER_TAXONOMY`` at your own TOML file (see ``taxonomy.example.toml``).
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from slopchecker.models import Anchor, Finding, FlattenedDoc, LedgerRow, Span
from slopchecker.pipeline.registry import CheckContext, CheckOutput, register

# --- default taxonomy -------------------------------------------------------
# Shipped as a Python literal (always importable, no packaged-data-file
# fragility) and mirrored in taxonomy.example.toml as the user-facing template.
# Deliberately small: the domains this team actually sees. Replace, don't
# extend in place — a funder's vocabulary is their own.

DEFAULT_TAXONOMY: dict[str, dict[str, list[str]]] = {
    "topics": {
        "science_policy": ["science policy", "nsf", "research enterprise", "science funding"],
        "ai": ["artificial intelligence", "machine learning", "frontier model", "compute", "llm"],
        "biosecurity": [
            "biosecurity",
            "biosafety",
            "pathogen",
            "dual-use research",
            "select agent",
        ],
        "metascience": ["metascience", "replication", "peer review", "research on research"],
        "energy": ["energy", "grid", "nuclear", "emissions", "renewable"],
    },
    "doc_types": {
        "grant_application": [
            "project narrative",
            "budget justification",
            "specific aims",
            "statement of work",
            "principal investigator",
        ],
        "think_tank_report": [
            "executive summary",
            "recommendations",
            "about the authors",
            "acknowledgments",
        ],
        # blog_post is the fallback (short, no structural markers) — no phrases.
        "blog_post": [],
    },
    "submitter_types": {
        "university": ["university", "college", "school of", "department of", "faculty of"],
        "nonprofit": ["501(c)(3)", "501c3", "nonprofit", "non-profit", "foundation", "institute"],
        "company": ["inc.", "llc", "corporation", "ltd.", "startup"],
        # individual is the fallback — no phrases.
        "individual": [],
    },
}

# A blog post is the doc-type fallback only when the document is also short:
# a 40-page PDF with no structural markers is "unknown", not a blog post.
_BLOG_MAX_WORDS = 1500

# Confidence ladder by count of distinct matched signal phrases. Transparent on
# purpose — a reviewer can see exactly why the number is what it is.
_CONFIDENCE_BY_HITS = {0: 0.0, 1: 0.5, 2: 0.75}
_CONFIDENCE_CAP = 0.9  # 3+ distinct signals

# US Employer Identification Number: NN-NNNNNNN. A strong organization signal.
_EIN_RE = re.compile(r"\b\d{2}-\d{7}\b")


def _confidence(hits: int) -> float:
    return _CONFIDENCE_BY_HITS.get(hits, _CONFIDENCE_CAP)


# --- results ----------------------------------------------------------------


@dataclass(frozen=True)
class Match:
    """A verbatim phrase hit: the exact substring and where it sits in text."""

    phrase: str  # the taxonomy phrase that matched (lowercased key)
    quote: str  # the verbatim slice of doc.text (original casing)
    start: int
    end: int


@dataclass(frozen=True)
class DocTypeResult:
    kind: str  # grant_application | think_tank_report | blog_post | unknown
    confidence: float
    matches: list[Match] = field(default_factory=list)


@dataclass(frozen=True)
class SubmitterTypeResult:
    kind: str  # university | nonprofit | company | individual | unknown
    confidence: float
    matches: list[Match] = field(default_factory=list)


@dataclass(frozen=True)
class TopicHit:
    topic: str
    matches: list[Match]


# --- taxonomy loading -------------------------------------------------------


def load_taxonomy(path: str | os.PathLike[str] | None = None) -> dict[str, dict[str, list[str]]]:
    """Return the taxonomy, from ``path`` / ``$SLOPCHECKER_TAXONOMY`` / default.

    Explicit ``path`` wins; otherwise the ``SLOPCHECKER_TAXONOMY`` env var; then
    the built-in ``DEFAULT_TAXONOMY``. A configured file that is missing or
    malformed raises — a silently-ignored taxonomy override would tag every
    document against the wrong vocabulary and no one would notice.
    """
    source = path or os.environ.get("SLOPCHECKER_TAXONOMY") or None
    if source is None:
        return DEFAULT_TAXONOMY
    with Path(source).open("rb") as fh:
        loaded = tomllib.load(fh)
    # Keep only the sections we understand, validating shape so a typo'd file
    # fails here rather than deep inside a matcher. A value must be a list of
    # phrases: a bare string ("zoning" instead of ["zoning"]) would otherwise
    # iterate into single characters and match nearly every document — silently.
    result: dict[str, dict[str, list[str]]] = {}
    for section in ("topics", "doc_types", "submitter_types"):
        entries = loaded.get(section, {})
        parsed: dict[str, list[str]] = {}
        for key, value in entries.items():
            if not isinstance(value, list):
                raise ValueError(
                    f"taxonomy [{section}].{key} must be a list of phrases, "
                    f"got {type(value).__name__} ({value!r})"
                )
            parsed[str(key)] = [str(phrase) for phrase in value]
        result[section] = parsed
    return result


# --- matching ---------------------------------------------------------------


@lru_cache(maxsize=2048)
def _phrase_re(phrase: str) -> re.Pattern[str]:
    """Case-insensitive, whole-token match for ``phrase``.

    Boundaries are alphanumeric-based rather than ``\\b`` so punctuated phrases
    ("501(c)(3)", "inc.", "dual-use research") behave, while a token can't match
    inside a larger word: "grid" won't fire on "gridlock", "compute" won't fire
    on "computer". Cached because ``applies_to`` may run the detectors per check.
    """
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(phrase)}(?![A-Za-z0-9])", re.IGNORECASE)


def _find_matches(text: str, phrases: list[str]) -> list[Match]:
    """First whole-token occurrence of each phrase, case-insensitive, in order.

    The quote is sliced from the original text so the anchor is verbatim,
    preserving the document's own casing for the reviewer.
    """
    found: list[Match] = []
    for phrase in phrases:
        m = _phrase_re(phrase).search(text)
        if m is not None:
            found.append(
                Match(phrase=phrase.lower(), quote=m.group(0), start=m.start(), end=m.end())
            )
    return found


def _best_category(
    text: str, categories: dict[str, list[str]], fallback: str
) -> tuple[str, float, list[Match]]:
    """Score each category by distinct phrase hits; return the winner.

    Ties break toward the category with the earliest first match, then
    alphabetically — deterministic, so the same document always tags the same
    way. No category matches → ``(fallback, 0.0, [])``; the caller decides
    whether the fallback is warranted.
    """
    scored: list[tuple[int, int, str, list[Match]]] = []
    for kind, phrases in categories.items():
        if not phrases:  # fallback categories carry no signal phrases
            continue
        matches = _find_matches(text, phrases)
        if matches:
            earliest = min(m.start for m in matches)
            scored.append((len(matches), -earliest, kind, matches))
    if not scored:
        return fallback, 0.0, []
    scored.sort(key=lambda s: (s[0], s[1], _neg_alpha(s[2])), reverse=True)
    hits, _, kind, matches = scored[0]
    return kind, _confidence(hits), matches


def _neg_alpha(s: str) -> tuple[int, ...]:
    """Sort key so that, under reverse=True, earlier-alphabetical wins ties."""
    return tuple(-ord(c) for c in s)


# --- pure detectors (importable by other checks' applies_to) ----------------


def detect_doc_type(doc: FlattenedDoc, taxonomy: dict | None = None) -> DocTypeResult:
    """Grant application / think-tank report / blog post, from structural cues.

    The seam the runner uses to route checks: a citation-heavy check can gate on
    ``detect_doc_type(doc).kind``. Cheap and side-effect-free so it's safe to
    call from many ``applies_to`` predicates in one run.
    """
    tax = taxonomy or load_taxonomy()
    text = doc.text
    kind, confidence, matches = _best_category(text, tax["doc_types"], fallback="unknown")
    if kind == "unknown":
        # No structural markers: call it a blog post only if it's also short.
        if 0 < len(text.split()) <= _BLOG_MAX_WORDS:
            return DocTypeResult(kind="blog_post", confidence=0.4, matches=[])
        return DocTypeResult(kind="unknown", confidence=0.0, matches=[])
    return DocTypeResult(kind=kind, confidence=confidence, matches=matches)


def infer_submitter_type(doc: FlattenedDoc, taxonomy: dict | None = None) -> SubmitterTypeResult:
    """University / nonprofit / company / individual, from letterhead-ish signals.

    An EIN is a strong organization signal and bumps confidence when it lines up
    with a nonprofit/company phrase; on its own it still isn't enough to name a
    specific type, so a lone EIN reports the phrase-based kind (or unknown) and
    lets the confidence number speak.
    """
    tax = taxonomy or load_taxonomy()
    text = doc.text
    kind, confidence, matches = _best_category(text, tax["submitter_types"], fallback="unknown")
    ein = _EIN_RE.search(text)
    if ein:
        m = Match(phrase="ein", quote=ein.group(0), start=ein.start(), end=ein.end())
        matches = [*matches, m]
        if kind in {"nonprofit", "company"}:
            confidence = min(_CONFIDENCE_CAP, confidence + 0.15)
    if kind == "unknown":
        return SubmitterTypeResult(kind="unknown", confidence=0.0, matches=matches)
    return SubmitterTypeResult(kind=kind, confidence=confidence, matches=matches)


def tag_topics(doc: FlattenedDoc, taxonomy: dict | None = None) -> list[TopicHit]:
    """Every topic with at least one term hit, most-hit first (then earliest).

    Multi-label on purpose — a proposal can be both AI and biosecurity. Returns
    an empty list when nothing matches rather than forcing a topic.
    """
    tax = taxonomy or load_taxonomy()
    text = doc.text
    hits: list[TopicHit] = []
    for topic, terms in tax["topics"].items():
        matches = _find_matches(text, terms)
        if matches:
            hits.append(TopicHit(topic=topic, matches=matches))
    hits.sort(key=lambda h: (len(h.matches), -min(m.start for m in h.matches)), reverse=True)
    return hits


# --- anchoring --------------------------------------------------------------


def _page_of(doc: FlattenedDoc, offset: int) -> int | None:
    """1-based page containing ``offset``, if the doc tracks page offsets (#4)."""
    if not doc.page_offsets:
        return None
    page = 0
    for start in doc.page_offsets:
        if start <= offset:
            page += 1
        else:
            break
    return page or None


def _anchor(doc: FlattenedDoc, m: Match) -> Anchor:
    """A quote-anchored pointer at a match — verbatim quote plus exact span."""
    return Anchor(page=_page_of(doc, m.start), quote=m.quote, span=Span(start=m.start, end=m.end))


# --- the registered check ---------------------------------------------------


@register(
    id="tagging",
    name="Topic and document-type tags",
    tier="deterministic",
    timeout_s=5.0,
)
def tagging(doc: FlattenedDoc, ctx: CheckContext) -> CheckOutput:
    """Emit tag rollups to the ledger and the tags themselves as evidence.

    Ledger (machine-scoreable):
      - ``doc_type_confidence`` (float) — kind + matched cues in ``detail``
      - ``topic_tags`` (int) — count of topics, names in ``detail``

    Submitter type is deliberately NOT emitted (dropped 2026-07-31, Emerson):
    on real uploads it was almost always "unknown (no supporting signal)" or
    a weak guess — a row that never informs a decision is noise in a report
    whose whole pitch is signal density. ``infer_submitter_type`` and its
    taxonomy stay for when a consumer earns it.

    Findings (the actual categorical tags, quote-anchored where a phrase grounds
    them) carry the values in ``evidence`` so the batch summary (#20) can sort
    and filter on them without re-running anything.
    """
    tax = load_taxonomy()
    doc_type = detect_doc_type(doc, tax)
    topics = tag_topics(doc, tax)

    ledger = [
        # The registered-id row (#142): every registered check must be traceable
        # to at least one ledger row bearing its own id — `--only tagging`,
        # coverage audits, and the e2e roster invariant all key on it. The
        # detailed rollups below keep their established ids for the renderer.
        LedgerRow(
            check="tagging",
            label="Topic and document-type tags",
            result=True,
            detail=f"{doc_type.kind} · {len(topics)} topic tag(s)",
        ),
        LedgerRow(
            check="doc_type_confidence",
            label="Document type",
            result=round(doc_type.confidence, 2),
            detail=_detail(doc_type.kind, doc_type.matches),
        ),
        LedgerRow(
            check="topic_tags",
            label="Topic tags",
            result=len(topics),
            detail=", ".join(h.topic for h in topics) or "none matched",
        ),
    ]

    findings = [
        Finding(
            id="tag-doc-type",
            label="Document type",
            anchor=_anchor(doc, doc_type.matches[0]) if doc_type.matches else None,
            evidence={
                "kind": doc_type.kind,
                "confidence": round(doc_type.confidence, 2),
                "signals": [m.phrase for m in doc_type.matches],
            },
            note=f"inferred document type: {doc_type.kind}",
        ),
    ]
    findings.extend(
        Finding(
            id=f"tag-topic-{h.topic}",
            label="Topic",
            anchor=_anchor(doc, h.matches[0]),
            evidence={"topic": h.topic, "terms": [m.phrase for m in h.matches]},
            note=f"topic tag: {h.topic}",
        )
        for h in topics
    )

    return CheckOutput(ledger=ledger, findings=findings)


def _detail(kind: str, matches: list[Match]) -> str:
    """Short human context for a ledger row: kind plus the cues behind it."""
    if not matches:
        return f"{kind} (no supporting signal)" if kind == "unknown" else kind
    cues = ", ".join(dict.fromkeys(m.phrase for m in matches))  # dedup, keep order
    return f"{kind} — {cues}"
