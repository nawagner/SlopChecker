"""Core data model (#3): the report.json contract between checkers and renderer.

Naming: CLAUDE.md's names (``FlattenedDoc`` / ``Finding`` / ``EvidenceReport``)
win over the issue-body strawman (``Document`` / ``Report``); aliases for the
issue names are provided at the bottom. Field layout codifies the shape already
shipped in #35/#40 (reference: ``tests/fixtures/sample_report.json``), which is
exactly what ``report/html.py`` consumes — so the renderer wires in unchanged.

Ground rules baked into the types (see #3 discussion and CLAUDE.md):

- Check results are strictly ``bool | int | float`` — never free text. Human
  framing lives in the renderer.
- Findings are evidence, not verdicts. No "is_ai_generated" style fields; a
  detector score is just a number in its own lane.
- A check that fails to run is first-class: ``status: skipped | errored`` with
  a mandatory ``reason`` — never a silently missing result.
- Findings are quote-anchored: ``Anchor.quote`` must be mechanically grounded
  in ``FlattenedDoc.text`` (quotecheck enforces this upstream of the report).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    model_validator,
)

SCHEMA_VERSION = "0.1"

Tier = Literal["deterministic", "api", "llm"]
CheckStatus = Literal["ok", "skipped", "errored"]

# A check result is a boolean or a number. Never prose. Strict so that a
# checker emitting "true" or "0.98" as strings fails loudly at the boundary.
Result = StrictBool | StrictInt | StrictFloat


class _Model(BaseModel):
    """Base config: unknown keys are typos in a contract — fail loudly."""

    model_config = ConfigDict(extra="forbid")


class Verdict(StrEnum):
    """Categorical outcome of an LLM claim-vs-source judgment (#11).

    Closed enum, not prose. ``overstated`` (source supports less than the
    paper claims) is deliberately distinct from ``unsupported`` (no support)
    and ``contradicted`` (source refutes); ``unverifiable`` (text not
    retrievable) never hides inside ``unsupported``.
    """

    supported = "supported"
    overstated = "overstated"
    unsupported = "unsupported"
    contradicted = "contradicted"
    unverifiable = "unverifiable"


class EntityKind(StrEnum):
    """Kind of named entity we look up in a public registry (#18)."""

    org = "org"
    person = "person"


class BackgroundConfidence(StrEnum):
    """How strongly a structured-registry hit attaches to a named entity (#18).

    - ``verified``: single hit with corroborating affiliation (or a
      registry-native unique id like an EIN or ORCID).
    - ``probable``: name matches plus one corroborating field, but not enough
      to be sure the record is the person or org named in the proposal.
    - ``unverified``: produced by a lookup for its own bookkeeping — never
      reaches a shipping report. ``BackgroundReport`` rejects it at assembly.

    The ``unverified`` state exists so a lookup can enumerate ambiguous
    matches (\"N candidates, none verified\") before deciding whether to
    surface any of them — the invariant is *filtering happens*, not that
    it happens early.
    """

    verified = "verified"
    probable = "probable"
    unverified = "unverified"


class Span(_Model):
    """Character offsets into ``FlattenedDoc.text`` (half-open: [start, end))."""

    start: int = Field(ge=0)
    end: int = Field(ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> Span:
        if self.end < self.start:
            raise ValueError(f"span end ({self.end}) precedes start ({self.start})")
        return self


class Anchor(_Model):
    """Where in the document a finding points: page + exact quote.

    ``quote`` is the verbatim excerpt from the flattened text (the renderer
    locates it by string match); ``span`` optionally pins exact offsets when
    the producer knows them (#4).
    """

    page: int | None = Field(default=None, ge=1)
    quote: str
    span: Span | None = None


class Check(_Model):
    """A check *definition* (registry entry) — not a result.

    Lets the orchestrator budget and gate: skip ``needs_network`` checks
    offline, sum ``est_cost_usd`` before a run, run the ``deterministic``
    tier with no LLM at all.
    """

    id: str
    name: str
    tier: Tier
    est_cost_usd: float = Field(default=0.0, ge=0.0)
    needs_network: bool = False


class CheckResult(_Model):
    """One check's outcome inside a finding.

    ``status`` is first-class: a check that didn't run is ``skipped`` (e.g.,
    no API key) or ``errored`` (it tried and failed), with a mandatory
    ``reason``. A missing result is never silent.
    """

    name: str
    result: Result | None = None
    status: CheckStatus = "ok"
    reason: str | None = None

    @model_validator(mode="after")
    def _status_consistent(self) -> CheckResult:
        if self.status == "ok" and self.result is None:
            raise ValueError(f"check '{self.name}': status 'ok' requires a result")
        if self.status != "ok" and self.reason is None:
            raise ValueError(f"check '{self.name}': status '{self.status}' requires a reason")
        if self.status != "ok" and self.result is not None:
            raise ValueError(f"check '{self.name}': status '{self.status}' cannot carry a result")
        return self


class Finding(_Model):
    """One quote-anchored piece of evidence about the document.

    Evidence, not a verdict: ``checks`` carries bool/number results,
    ``evidence`` carries the raw supporting data (resolved metadata, source
    excerpt, HTTP status, model/score details) so a human can verify the
    claim without re-running anything. ``verdict`` is the optional closed
    enum for LLM claim-support judgments (#11) — never free text.
    """

    id: str
    target: str | None = None
    label: str | None = None
    anchor: Anchor | None = None
    checks: list[CheckResult] = Field(default_factory=list)
    verdict: Verdict | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    note: str | None = None

    @model_validator(mode="after")
    def _note_one_line(self) -> Finding:
        if self.note is not None and "\n" in self.note:
            raise ValueError(f"finding '{self.id}': note must be one line")
        return self


class FlattenedDoc(_Model):
    """The normalized document: flattened text plus source metadata.

    ``text`` is the single normalized string all anchors/spans index into.
    ``page_offsets`` (optional) gives the char offset where each page starts,
    for producers that track page structure (#4). Section structure is
    deferred until a loader needs it.
    """

    file: str
    text: str
    sha256: str | None = None
    pages: int | None = Field(default=None, ge=0)
    page_offsets: list[int] | None = None
    media_type: str | None = None
    title: str | None = None
    byline: str | None = None
    submitter: str | None = None


class LedgerRow(_Model):
    """One row of the all-checks ledger (document-level results table).

    Same first-class ``status`` discipline as ``CheckResult``; ``detail`` is
    the renderer's short human context ("3 / 4 — ref [3] not found").
    """

    check: str
    label: str | None = None
    result: Result | None = None
    detail: str | None = None
    status: CheckStatus = "ok"
    reason: str | None = None

    @model_validator(mode="after")
    def _status_consistent(self) -> LedgerRow:
        if self.status == "ok" and self.result is None:
            raise ValueError(f"ledger '{self.check}': status 'ok' requires a result")
        if self.status != "ok" and self.reason is None:
            raise ValueError(f"ledger '{self.check}': status '{self.status}' requires a reason")
        if self.status != "ok" and self.result is not None:
            raise ValueError(f"ledger '{self.check}': status '{self.status}' cannot carry a result")
        return self


class RunInfo(_Model):
    """Run metadata: when, how long, which code, what it cost."""

    date: str | None = None
    seconds: int | float | None = None
    version: str | None = None
    cost_usd: float | None = Field(default=None, ge=0.0)


class Summary(_Model):
    """The tool recommends; it never auto-rejects. Counts are derived from
    the ledger (``EvidenceReport.counts()``), not stored."""

    recommendation: str = "human_review"


# --- Background lookups (#18) ------------------------------------------------
#
# Structured public-registry lookups (ProPublica / OpenAlex / ORCID) and the
# optional open-web research pass both write into ``BackgroundReport``. Every
# item in the report is source-linked; anything a registry couldn't
# corroborate is either explicitly ``EntityNotFound`` or a coverage
# ``BackgroundGap`` — silent absence would be indistinguishable from
# "checked and clean" and is disallowed.


class Entity(_Model):
    """A named person or organization extracted from the proposal.

    ``affiliation`` is the corroboration hook: for a person, the org they
    claim to be with; for an org, typically unset. Common-name
    disambiguation (\"no verified match for a person without an
    affiliation\") is a code-level invariant enforced at the lookup site,
    not by this model — different registries have different fields that
    count as \"corroboration.\"
    """

    id: str
    kind: EntityKind
    name: str
    affiliation: str | None = None
    anchor: Anchor | None = None


class BackgroundFinding(_Model):
    """One source-linked datum about an entity from a public registry.

    ``source_url`` is required — no unsourced findings. ``data`` carries
    the raw registry fields so a human can verify the claim without
    re-running the lookup. ``secondary_sources`` supports cross-client
    dedup (OpenAlex + ORCID hitting the same person are one finding, not
    two).
    """

    id: str
    entity_id: str
    registry: str
    source_url: str
    confidence: BackgroundConfidence
    label: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    secondary_sources: list[str] = Field(default_factory=list)


class EntityNotFound(_Model):
    """Explicit \"we looked for this entity in this registry and it isn't there.\"

    Distinct from ``BackgroundGap`` (something prevented us from looking)
    and from absence (silent — never allowed). ``query_url`` records the
    URL we hit that returned zero results, so the negative is auditable.
    """

    entity_id: str
    registry: str
    query_url: str


class BackgroundGap(_Model):
    """Per-(entity, registry) coverage gap for the background lookups.

    Distinct from ``LedgerRow``'s skipped/errored (which is per-check-run).
    ``entity_id=None`` means the whole registry was unreachable (no key,
    HTTP 5xx on every request, ...); a set ``entity_id`` scopes the gap
    to one lookup that failed while others succeeded.
    """

    entity_id: str | None = None
    registry: str
    reason: str


class BackgroundReport(_Model):
    """Structured background lookups on an application's entities (#18).

    Rides on ``EvidenceReport`` as an optional field so this shape can
    ship independently of the runner integration. The open-web lane's
    generated brief lands in ``brief_markdown``; the structured lane
    leaves it ``None``.
    """

    entities: list[Entity] = Field(default_factory=list)
    findings: list[BackgroundFinding] = Field(default_factory=list)
    not_found: list[EntityNotFound] = Field(default_factory=list)
    gaps: list[BackgroundGap] = Field(default_factory=list)
    brief_markdown: str | None = None

    @model_validator(mode="after")
    def _referential_integrity(self) -> BackgroundReport:
        entity_ids = {e.id for e in self.entities}
        for f in self.findings:
            if f.confidence is BackgroundConfidence.unverified:
                raise ValueError(
                    f"finding '{f.id}': unverified findings must not enter a BackgroundReport"
                )
            if f.entity_id not in entity_ids:
                raise ValueError(f"finding '{f.id}': entity_id '{f.entity_id}' not in entities")
        for nf in self.not_found:
            if nf.entity_id not in entity_ids:
                raise ValueError(f"not_found: entity_id '{nf.entity_id}' not in entities")
        for g in self.gaps:
            if g.entity_id is not None and g.entity_id not in entity_ids:
                raise ValueError(f"gap: entity_id '{g.entity_id}' not in entities")
        return self


class EvidenceReport(_Model):
    """The report.json contract: everything the renderer needs, nothing else."""

    schema_version: str = SCHEMA_VERSION
    document: FlattenedDoc
    solicitation: str | None = None
    run: RunInfo = Field(default_factory=RunInfo)
    findings: list[Finding] = Field(default_factory=list)
    ledger: list[LedgerRow] = Field(default_factory=list)
    summary: Summary = Field(default_factory=Summary)
    background: BackgroundReport | None = None

    def counts(self) -> dict[str, int]:
        """Summary tallies derived from the ledger (never stored)."""
        results = [row.result for row in self.ledger if row.status == "ok"]
        return {
            "passed": sum(1 for r in results if r is True),
            "failed": sum(1 for r in results if r is False),
            "scores": sum(1 for r in results if not isinstance(r, bool)),
            "skipped": sum(1 for row in self.ledger if row.status == "skipped"),
            "errored": sum(1 for row in self.ledger if row.status == "errored"),
        }

    def to_report_dict(self) -> dict[str, Any]:
        """JSON-ready dict in the exact shape ``report.html.render_report``
        consumes (``exclude_none`` so absent fields stay absent)."""
        return self.model_dump(mode="json", exclude_none=True)


# Issue #3 names the models Document/Report; CLAUDE.md names won. Aliases so
# code written against the issue strawman still imports.
Document = FlattenedDoc
Report = EvidenceReport
