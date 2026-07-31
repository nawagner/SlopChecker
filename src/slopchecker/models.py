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


class EvidenceReport(_Model):
    """The report.json contract: everything the renderer needs, nothing else."""

    schema_version: str = SCHEMA_VERSION
    document: FlattenedDoc
    solicitation: str | None = None
    run: RunInfo = Field(default_factory=RunInfo)
    findings: list[Finding] = Field(default_factory=list)
    ledger: list[LedgerRow] = Field(default_factory=list)
    summary: Summary = Field(default_factory=Summary)

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
