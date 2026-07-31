"""Claim-support LLM check (#11) — entry point + orchestration.

For each (claim, citation) pair in a document that has a retrievable source:

1. Ask a judge model: does the source support the claim? Return a verdict
   (``Verdict`` enum) and a verbatim supporting passage.
2. Verify the passage against the source text via ``match_quote``. If it
   isn't found, drop the finding — no passage, no finding.
3. If the verdict is a concern (``overstated`` / ``unsupported`` /
   ``contradicted``) with sufficient confidence, ask a refuter model to
   knock it down. If the refuter refutes, drop the finding.
4. Emit a ``Finding`` for surviving concerns; the ``supported`` and
   ``unverifiable`` outcomes are silent by design.

Cost ceiling per acceptance criterion 3:
- ``max_citations_per_doc`` bounds LLM calls to ``2N`` worst-case per doc
  (one judge call per citation, plus one refuter call per concern verdict
  that carries a verified passage; the ledger row is not an LLM call).
- ``max_source_chars`` truncates the source excerpt around the citation
  before it reaches the LLM.

Registered via ``@register`` at import time with ``tier="llm"``.
Off by default — the runner only runs it when ``--tier`` selects it.

All LLM plumbing (transport, retries, prompt assembly) lives in this
subpackage; the #37 comment prescribes keeping this private until a second
LLM caller exists.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from slopchecker import config as _config
from slopchecker.models import (
    Anchor,
    CheckResult,
    CheckStatus,
    Finding,
    FlattenedDoc,
    LedgerRow,
    Verdict,
)
from slopchecker.pipeline.citations import extract_citations
from slopchecker.pipeline.citations.models import Citation
from slopchecker.pipeline.claim_support.llm import (
    AnthropicTransport,
    Transport,
    TransportAuthError,
    TransportClientError,
    TransportError,
    TransportRateLimit,
    TransportRefusal,
    TransportServerError,
)
from slopchecker.pipeline.claim_support.prompts import (
    JUDGE_SCHEMA,
    REFUTER_SCHEMA,
    judge_prompt,
    refuter_prompt,
)
from slopchecker.pipeline.quotes.fetch import LocalFileFetcher, SourceFetcher
from slopchecker.pipeline.quotes.matching import QuoteStatus, match_quote
from slopchecker.pipeline.registry import CheckContext, CheckOutput, register

CHECK_ID = "claim_supported"

# Only concern verdicts reach the report — 'supported' and 'unverifiable'
# are silent by design (#11: bias hard toward silence).
_CONCERN_VERDICTS = {Verdict.overstated, Verdict.unsupported, Verdict.contradicted}


@dataclass(frozen=True)
class ClaimSupportConfig:
    """Knobs for the claim-support check.

    Defaults are conservative: a small set of citations, a low-effort model
    call, a confidence floor that keeps low-signal verdicts silent.
    """

    judge_model: str = "claude-opus-5"
    refuter_model: str = "claude-opus-5"
    # Hard cap on citations that reach the LLM — half of the cost ceiling.
    max_citations_per_doc: int = 20
    # Truncate the source excerpt around the citation before sending —
    # the other half of the cost ceiling.
    max_source_chars: int = 30_000
    # Verdicts below this confidence are dropped without asking the refuter.
    min_confidence: float = 0.6
    # Retry policy for 429/5xx (mirrors detect/pangram.py).
    max_attempts: int = 3
    initial_backoff_seconds: float = 0.5


@dataclass(frozen=True)
class _JudgeVerdict:
    verdict: Verdict
    passage: str
    confidence: float
    reasoning: str


@dataclass(frozen=True)
class _RefuterOutcome:
    outcome: str  # "upheld" | "softened" | "refuted"
    reasoning: str


class ClaimSupportCheck:
    """Public entry point.

    Instances are created by the registered wrapper below (which pulls the
    ``SourceFetcher`` off ``CheckContext.workdir`` — see comments there),
    or directly by tests with a fake ``Transport``.
    """

    name = CHECK_ID

    def __init__(
        self,
        *,
        config: ClaimSupportConfig,
        fetcher: SourceFetcher | None,
        transport: Transport | None = None,
    ) -> None:
        self._conf = config
        self._fetcher = fetcher
        self._transport = transport  # lazily built when a real call is needed

    # ---- Public entry point ---------------------------------------------

    def run(self, doc: FlattenedDoc, ctx: CheckContext) -> CheckOutput:
        # Credentials: skipped ledger row on missing key, matching pangram's
        # degrade-to-gap contract.
        try:
            api_key = _config.require("ANTHROPIC_API_KEY")
        except _config.MissingCredential as exc:
            return CheckOutput(ledger=[_gap_row("skipped", f"missing {exc.env_var}")])

        extraction = extract_citations(doc.text)
        candidates = _select_candidates(
            extraction.citations, cap=self._conf.max_citations_per_doc
        )

        if not candidates.usable:
            # No usable citations = valid no-op. Still record the ledger row
            # so the report shows we tried.
            return CheckOutput(ledger=[_ok_row(result=0, detail=candidates.summary)])

        transport = self._get_transport(api_key)

        findings: list[Finding] = []
        source_gaps = 0
        refusal_gaps = 0
        transport_error: TransportError | None = None
        for i, citation in enumerate(candidates.usable, start=1):
            # _select_candidates guarantees `citation.reference is not None`;
            # narrow for mypy.
            ref = citation.reference
            assert ref is not None
            source = self._fetcher.fetch(ref) if self._fetcher else None
            if source is None:
                source_gaps += 1
                continue

            claim = citation.mention.claim_text
            citation_marker = citation.mention.marker
            # Truncate the source excerpt around the citation before sending —
            # the second half of the cost ceiling.
            excerpt = _select_excerpt(source, self._conf.max_source_chars)

            # Stage 1: judge.
            try:
                judge = self._judge(
                    claim=claim,
                    citation_marker=citation_marker,
                    source=excerpt,
                    transport=transport,
                )
            except TransportRefusal:
                # Policy refusal on THIS request — record a per-citation gap
                # and move on. A doc-wide refusal is unusual; a refusal on
                # one claim shouldn't kill the whole check.
                refusal_gaps += 1
                continue
            except TransportError as exc:
                # Bail out but keep the findings we've gathered so far — a
                # partial evidence report is better than dropping real
                # findings on the floor (CLAUDE.md: "degrade to gaps, never
                # crash"). The errored ledger row makes the gap visible.
                transport_error = exc
                break

            # Silent outcomes: supported, unverifiable, low confidence.
            if judge.verdict not in _CONCERN_VERDICTS:
                continue
            if judge.confidence < self._conf.min_confidence:
                continue
            if not judge.passage.strip():
                # Concern verdicts require a supporting passage — no passage,
                # no finding (invariant 1).
                continue

            # Mechanical quotecheck. This is the hard rule — the passage must
            # exist in the source text or the finding is dropped.
            match = match_quote(judge.passage, source)
            if match.status not in (QuoteStatus.found_verbatim, QuoteStatus.found_minor_variation):
                continue

            # Stage 2: refuter. If it refutes, drop the finding — biased
            # toward silence.
            try:
                refuter = self._refute(
                    claim=claim,
                    citation_marker=citation_marker,
                    source=excerpt,
                    judge=judge,
                    transport=transport,
                )
            except TransportRefusal:
                # Refuter refused — no verification signal, so drop the
                # finding (bias toward silence — same as refuter="refuted").
                refusal_gaps += 1
                continue
            except TransportError as exc:
                transport_error = exc
                break

            if refuter.outcome == "refuted":
                continue

            findings.append(
                _build_finding(
                    i=i,
                    citation=citation,
                    judge=judge,
                    refuter=refuter,
                    match_window=match.window,
                    match_score=match.score,
                    match_status=match.status,
                    judge_model=self._conf.judge_model,
                    refuter_model=self._conf.refuter_model,
                    transport_name=getattr(transport, "name", "anthropic"),
                )
            )

        # Ledger: single errored row if we bailed, otherwise ok row + any
        # findings gathered so far. When we bail with partial findings, the
        # errored row *replaces* the ok row so the reader sees the check
        # didn't complete — findings are still returned as evidence, but the
        # ledger tells the reader the count isn't authoritative.
        if transport_error is not None:
            return CheckOutput(
                findings=findings,
                ledger=[_gap_row("errored", f"llm transport error: {transport_error}")],
            )
        detail_bits = [candidates.summary]
        if source_gaps:
            detail_bits.append(f"{source_gaps} citation(s) skipped: source unavailable")
        if refusal_gaps:
            detail_bits.append(f"{refusal_gaps} citation(s) skipped: model refused")
        detail = "; ".join(b for b in detail_bits if b) or None
        return CheckOutput(
            findings=findings,
            ledger=[_ok_row(result=len(findings), detail=detail)],
        )

    # ---- LLM turns -------------------------------------------------------

    def _judge(
        self, *, claim: str, citation_marker: str, source: str, transport: Transport
    ) -> _JudgeVerdict:
        system, user = judge_prompt(
            claim=claim, citation_marker=citation_marker, source_text=source
        )
        payload = self._call_with_retry(
            transport,
            system=system,
            user=user,
            schema=JUDGE_SCHEMA,
            model=self._conf.judge_model,
            role="judge",
        )
        # Schema is enforced server-side via ``output_config.format``, but
        # "degrade to gaps, never crash" means we don't rely on that. A
        # malformed payload becomes a client-side transport error so the
        # runner records a gap rather than blowing up.
        try:
            return _JudgeVerdict(
                verdict=Verdict(payload["verdict"]),
                passage=str(payload.get("supporting_passage", "") or ""),
                confidence=float(payload.get("confidence", 0.0)),
                reasoning=str(payload.get("reasoning", "") or ""),
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise TransportClientError(422, f"judge payload malformed: {exc}") from exc

    def _refute(
        self,
        *,
        claim: str,
        citation_marker: str,
        source: str,
        judge: _JudgeVerdict,
        transport: Transport,
    ) -> _RefuterOutcome:
        system, user = refuter_prompt(
            claim=claim,
            citation_marker=citation_marker,
            source_text=source,
            judge_verdict=str(judge.verdict),
            judge_passage=judge.passage,
            judge_reasoning=judge.reasoning,
        )
        payload = self._call_with_retry(
            transport,
            system=system,
            user=user,
            schema=REFUTER_SCHEMA,
            model=self._conf.refuter_model,
            role="refuter",
        )
        try:
            return _RefuterOutcome(
                outcome=str(payload["outcome"]),
                reasoning=str(payload.get("reasoning", "") or ""),
            )
        except (KeyError, TypeError) as exc:
            raise TransportClientError(422, f"refuter payload malformed: {exc}") from exc

    # ---- Retry loop -----------------------------------------------------

    def _call_with_retry(
        self,
        transport: Transport,
        *,
        system: str,
        user: str,
        schema: dict,
        model: str,
        role: str,
    ) -> dict[str, Any]:
        """Retry 429/5xx with exponential backoff; surface auth/client immediately.

        Kept private and inline per the #37 design comment — the shared
        Ladder is a follow-up refactor once #11 and #13 land. Same shape as
        ``detect/pangram.py:_call_with_retry``.
        """
        last_transient: TransportError | None = None
        for attempt in range(self._conf.max_attempts):
            try:
                return transport.complete_json(
                    system=system, user=user, schema=schema, model=model, role=role
                )
            except (TransportRateLimit, TransportServerError) as exc:
                last_transient = exc
                if attempt < self._conf.max_attempts - 1:
                    time.sleep(self._conf.initial_backoff_seconds * (2**attempt))
            except (TransportAuthError, TransportClientError, TransportRefusal):
                raise  # permanent — surface immediately
        assert last_transient is not None
        raise last_transient

    def _get_transport(self, api_key: str) -> Transport:
        if self._transport is None:
            self._transport = AnthropicTransport(api_key=api_key)
        return self._transport


# --- Ledger helpers --------------------------------------------------------


def _ok_row(*, result: int, detail: str | None) -> LedgerRow:
    return LedgerRow(
        check=CHECK_ID,
        label="Claim support (LLM)",
        result=result,
        detail=detail,
        status="ok",
    )


def _gap_row(status: CheckStatus, reason: str) -> LedgerRow:
    return LedgerRow(
        check=CHECK_ID,
        label="Claim support (LLM)",
        status=status,
        reason=reason,
    )


# --- Candidate selection ---------------------------------------------------


@dataclass(frozen=True)
class _Candidates:
    usable: list[Citation]
    summary: str


def _select_candidates(citations: list[Citation], *, cap: int) -> _Candidates:
    """Pick citations with resolved references, up to the per-doc cap.

    The runner-visible summary distinguishes "no citations" from "cap hit"
    so the report shows what happened.
    """
    resolved = [c for c in citations if c.reference is not None]
    if not resolved:
        return _Candidates(usable=[], summary="no citations with resolved references")
    if len(resolved) <= cap:
        return _Candidates(usable=resolved, summary=f"{len(resolved)} citation(s) checked")
    kept = resolved[:cap]
    skipped = len(resolved) - cap
    return _Candidates(
        usable=kept,
        summary=f"{cap} citation(s) checked; {skipped} skipped (per-doc cap)",
    )


def _select_excerpt(source: str, max_chars: int) -> str:
    """Truncate the source to ``max_chars``. Simple head-truncation for now.

    A future improvement: locate the citation's most likely relevant span
    (e.g. via ``match_quote`` on the claim itself as a first pass) and center
    the window there. For MVP, head-truncation with a generous default is
    predictable and covers the common case where the abstract/intro contains
    the load-bearing claim.
    """
    if len(source) <= max_chars:
        return source
    return source[:max_chars]


# --- Finding builder -------------------------------------------------------


def _build_finding(
    *,
    i: int,
    citation: Citation,
    judge: _JudgeVerdict,
    refuter: _RefuterOutcome,
    match_window: str | None,
    match_score: float,
    match_status: QuoteStatus,
    judge_model: str,
    refuter_model: str,
    transport_name: str,
) -> Finding:
    ref = citation.reference
    assert ref is not None  # candidate selection guarantees this
    # Anchor.quote is contractually the excerpt from the PROPOSAL
    # (FlattenedDoc.text) — that's what the renderer locates and highlights
    # in-line. The LLM's supporting_passage is from the CITED SOURCE, not
    # the proposal, so it lands in evidence instead. Anchoring to the
    # claim sentence means the report highlights the claim under scrutiny.
    mention = citation.mention
    anchor = Anchor(quote=mention.claim_text, span=mention.claim_span)
    checks = [
        CheckResult(
            name="claim_supported",
            result=False,  # concern verdict = "not supported as written"
        ),
        CheckResult(name="passage_match_score", result=round(match_score, 3)),
    ]
    evidence: dict[str, Any] = {
        "provider": transport_name,
        "judge_model": judge_model,
        "refuter_model": refuter_model,
        "judge_verdict": str(judge.verdict),
        "judge_confidence": round(judge.confidence, 3),
        "refuter_outcome": refuter.outcome,
        "passage_status": str(match_status),
        "citation_marker": citation.mention.marker,
        # The LLM-supplied source passage (already verified to appear in
        # the retrieved source text via match_quote).
        "source_passage": judge.passage,
    }
    if match_window is not None:
        evidence["source_window"] = match_window[:500]
    return Finding(
        id=f"CS{i}",
        target=ref.key,
        label="Claim support (LLM)",
        anchor=anchor,
        checks=checks,
        verdict=judge.verdict,
        evidence=evidence,
        note=_one_line_note(judge.verdict, refuter.outcome),
    )


def _one_line_note(verdict: Verdict, refuter_outcome: str) -> str:
    # Only concern verdicts reach this function (guarded upstream). A KeyError
    # here would be a programming bug — no default so it fails loudly.
    verdict_word = {
        Verdict.overstated: "overstated by the proposal",
        Verdict.unsupported: "not supported by the cited source",
        Verdict.contradicted: "contradicted by the cited source",
    }[verdict]
    if refuter_outcome == "softened":
        return f"Claim appears {verdict_word}; refuter softened the finding."
    return f"Claim appears {verdict_word}."


# --- Registration ---------------------------------------------------------


@register(
    id=CHECK_ID,
    name="Claim supported by cited source (LLM)",
    tier="llm",
    est_cost_usd=0.05,  # rough per-doc ceiling; refined once the eval on #11 lands
    needs_network=True,
    timeout_s=180.0,
)
def _run_claim_support(doc: FlattenedDoc, ctx: CheckContext) -> CheckOutput:
    """Registered wrapper.

    The runner-facing seam. Creates a ``LocalFileFetcher`` rooted at
    ``ctx.workdir / "sources"`` if the workdir exists — the check is
    stateless so we build the check + fetcher fresh per call. Real network
    fetchers (arXiv, PMC OA) plug in behind the same ``SourceFetcher``
    protocol; that's follow-up work on #10.
    """
    fetcher: SourceFetcher | None = None
    if ctx.workdir is not None:
        sources_dir = ctx.workdir / "sources"
        if sources_dir.is_dir():
            fetcher = LocalFileFetcher(sources_dir)
    check = ClaimSupportCheck(config=ClaimSupportConfig(), fetcher=fetcher)
    return check.run(doc, ctx)
