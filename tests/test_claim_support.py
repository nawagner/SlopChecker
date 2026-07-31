"""Tests for #11: claim-support LLM check.

Adversarial-verify shape ported from pat-helper: a judge model returns a
Verdict + supporting passage; a refuter (currently the same provider) tries
to knock it down. Two invariants are non-negotiable and every test here
asserts one of them:

1. Every emitted Finding carries a passage the LLM claimed *and*
   mechanically verified against the retrieved source text via
   ``match_quote``. No passage or unmatched passage → no finding.
2. The check biases hard toward silence — ``supported`` verdicts, the
   refuter's ``refuted`` verdict, low confidence, and unretrievable
   sources all produce no finding. Only ``overstated``, ``unsupported``,
   and ``contradicted`` verdicts (surviving the refuter) reach the
   report as concerns.

Fabricated fixtures only, per CLAUDE.md.
"""

from __future__ import annotations

from pathlib import Path

from slopchecker.models import FlattenedDoc, Verdict
from slopchecker.pipeline.claim_support import ClaimSupportCheck, ClaimSupportConfig
from slopchecker.pipeline.claim_support.llm import (
    TransportAuthError,
    TransportRateLimit,
    TransportServerError,
)
from slopchecker.pipeline.quotes import LocalFileFetcher
from slopchecker.pipeline.registry import CheckContext

FIXTURES = Path(__file__).parent / "fixtures"
SOURCES = FIXTURES / "sources"


def _sample_doc() -> FlattenedDoc:
    text = (FIXTURES / "citations" / "apa.txt").read_text()
    return FlattenedDoc(file="apa.txt", text=text)


def _config(**overrides) -> ClaimSupportConfig:
    base = dict(
        judge_model="claude-opus-5",
        refuter_model="claude-opus-5",
        max_citations_per_doc=20,
        max_source_chars=30_000,
        min_confidence=0.6,
    )
    base.update(overrides)
    return ClaimSupportConfig(**base)


# --- Fake transport ---------------------------------------------------------


class FakeTransport:
    """Replays scripted judge/refuter turns; records every call for assertions.

    Each item in ``turns`` is either a dict (parsed structured output — what
    the Anthropic Messages API's ``output_config.format`` guarantees) or an
    Exception subclass instance to raise. The transport asserts the intended
    ``role`` matches so a test that scripts refuter responses for a judge
    call blows up loudly instead of silently mis-aligning.
    """

    # `name` lands in Finding.evidence["provider"]; asserting the exact
    # value confirms the pass-through works rather than relying on a
    # fallback default.
    name = "anthropic-fake"

    def __init__(self, turns: list[object]) -> None:
        self._turns = list(turns)
        self.calls: list[dict] = []

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict,
        model: str,
        role: str,
    ) -> dict:
        self.calls.append(
            {"system": system, "user": user, "model": model, "role": role, "schema": schema}
        )
        if not self._turns:
            raise AssertionError(f"FakeTransport out of scripted turns (role={role})")
        turn = self._turns.pop(0)
        if isinstance(turn, Exception):
            raise turn
        expected_role = turn.pop("_expect_role", None)
        if expected_role is not None and expected_role != role:
            raise AssertionError(
                f"scripted turn expected role={expected_role!r} but got role={role!r}"
            )
        return turn


# --- Judge / refuter response builders --------------------------------------


def judge_response(
    *,
    verdict: str,
    passage: str = "",
    confidence: float = 0.9,
    reasoning: str = "",
) -> dict:
    return {
        "_expect_role": "judge",
        "verdict": verdict,
        "supporting_passage": passage,
        "confidence": confidence,
        "reasoning": reasoning or f"judge picked {verdict}",
    }


def refuter_response(
    *,
    outcome: str,
    reasoning: str = "",
) -> dict:
    return {
        "_expect_role": "refuter",
        "outcome": outcome,
        "reasoning": reasoning or f"refuter said {outcome}",
    }


# --- Tests ------------------------------------------------------------------


def test_skipped_when_api_key_missing(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    doc = _sample_doc()
    check = ClaimSupportCheck(
        config=_config(),
        fetcher=LocalFileFetcher(SOURCES),
        transport=FakeTransport([]),  # never touched
    )
    out = check.run(doc, CheckContext())

    # One skipped ledger row, no findings, no cost.
    assert out.findings == []
    assert out.cost_usd == 0.0
    assert len(out.ledger) == 1
    row = out.ledger[0]
    assert row.status == "skipped"
    assert "ANTHROPIC_API_KEY" in (row.reason or "")


def test_supported_verdict_stays_silent(monkeypatch):
    """Bias-toward-silence: a supported claim produces no finding.

    apa.txt yields 3 citations with fetchable sources (Smith narrative,
    Smith in multi-cite, Delacroix). All three judge-supported → no findings.
    Citations to Vance and Okafor resolve to references but have no source
    file on disk, so they're skipped before any LLM call.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    doc = _sample_doc()
    transport = FakeTransport(
        [
            judge_response(verdict="supported", passage="durable attitude change"),
            judge_response(verdict="supported", passage="durable attitude change"),
            judge_response(verdict="supported", passage="prebunking interventions"),
        ]
    )
    check = ClaimSupportCheck(
        config=_config(),
        fetcher=LocalFileFetcher(SOURCES),
        transport=transport,
    )
    out = check.run(doc, CheckContext())

    assert out.findings == []
    # Ledger records what we checked, with a zero concern count.
    [row] = out.ledger
    assert row.check == "claim_supported"
    assert row.status == "ok"
    assert row.result == 0


def test_concern_verdict_emits_finding_with_verified_passage(monkeypatch):
    """A grounded overstated/unsupported/contradicted verdict emits a Finding."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    doc = _sample_doc()
    # First Smith citation: judge says overstated with a passage that IS
    # in the Smith source text. Refuter upholds → emit one finding.
    # Second Smith and Delacroix: supported (silent).
    smith_passage = "durable attitude change requires repeated exposure"
    transport = FakeTransport(
        [
            judge_response(
                verdict="overstated",
                passage=smith_passage,
                reasoning="source qualifies the claim more than the paper conveys",
            ),
            refuter_response(outcome="upheld", reasoning="qualifier is real"),
            judge_response(verdict="supported", passage="durable attitude change"),
            judge_response(verdict="supported", passage="prebunking interventions"),
        ]
    )
    check = ClaimSupportCheck(
        config=_config(),
        fetcher=LocalFileFetcher(SOURCES),
        transport=transport,
    )
    out = check.run(doc, CheckContext())

    assert len(out.findings) == 1
    f = out.findings[0]
    assert f.verdict is Verdict.overstated
    assert f.anchor is not None
    # Anchor.quote is the claim sentence from the PROPOSAL (that's what
    # the renderer highlights in-line). The LLM's supporting source
    # passage lands in evidence, not the anchor.
    assert f.anchor.quote in doc.text
    assert "Smith" in f.anchor.quote  # the claim citing Smith
    # The verified source passage rides in evidence.
    assert f.evidence["source_passage"] == smith_passage
    # Evidence carries provider/model/refuter provenance.
    assert f.evidence["provider"] == "anthropic-fake"
    assert f.evidence["judge_model"] == "claude-opus-5"
    assert f.evidence["refuter_model"] == "claude-opus-5"
    assert f.evidence["refuter_outcome"] == "upheld"
    # The source reference the finding points at.
    assert f.target == "smith-2021"
    # Concern count in the ledger.
    [row] = out.ledger
    assert row.check == "claim_supported"
    assert row.result == 1


def test_hallucinated_passage_is_dropped(monkeypatch):
    """Passage not in the source text → finding discarded (invariant 1)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    doc = _sample_doc()
    # Judge claims a passage that is NOT in either source. All three
    # citations judged that way → all three dropped by quotecheck; refuter
    # never runs (invariant 1).
    fabricated = "this exact sentence appears nowhere in the source at all"
    transport = FakeTransport(
        [
            judge_response(verdict="unsupported", passage=fabricated),
            judge_response(verdict="unsupported", passage=fabricated),
            judge_response(verdict="unsupported", passage=fabricated),
        ]
    )
    check = ClaimSupportCheck(
        config=_config(),
        fetcher=LocalFileFetcher(SOURCES),
        transport=transport,
    )
    out = check.run(doc, CheckContext())

    assert out.findings == []
    # One judge call per citation; no refuter call — the finding is dropped
    # by quotecheck before it reaches the refuter.
    roles = [c["role"] for c in transport.calls]
    assert roles == ["judge", "judge", "judge"]


def test_anchor_uses_proposal_claim_not_source_passage(monkeypatch):
    """Regression: Anchor.quote must come from FlattenedDoc.text, not source.

    Renderer locates `anchor.quote` via `text.find(quote)` on the proposal;
    an anchor set to a source passage that doesn't appear in the proposal
    leaves the finding un-anchored in-line. Uses a source passage that
    exists in the source but NOT in the proposal to catch this.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    doc = _sample_doc()
    # A phrase that appears (verbatim) in the Delacroix source on one line
    # but NOT in apa.txt.
    delacroix_source_only = "cohort age or platform tenure"
    assert delacroix_source_only in (SOURCES / "doi-10.1234_jams.2023.0142.txt").read_text()
    assert delacroix_source_only not in doc.text

    transport = FakeTransport(
        [
            judge_response(verdict="supported", passage="whatever"),
            judge_response(verdict="supported", passage="whatever"),
            judge_response(verdict="overstated", passage=delacroix_source_only),
            refuter_response(outcome="upheld"),
        ]
    )
    check = ClaimSupportCheck(
        config=_config(),
        fetcher=LocalFileFetcher(SOURCES),
        transport=transport,
    )
    out = check.run(doc, CheckContext())

    assert len(out.findings) == 1
    f = out.findings[0]
    # Hard rule: the anchor quote MUST exist verbatim in the proposal.
    assert f.anchor is not None
    assert f.anchor.quote in doc.text
    # The source-only passage is preserved in evidence, not the anchor.
    assert f.evidence["source_passage"] == delacroix_source_only


def test_refuter_refuted_drops_finding(monkeypatch):
    """Bias-toward-silence: refuter refuting the judge drops the finding."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    doc = _sample_doc()
    smith_passage = "durable attitude change requires repeated exposure"
    transport = FakeTransport(
        [
            judge_response(verdict="unsupported", passage=smith_passage),
            refuter_response(outcome="refuted", reasoning="judge misread the source"),
            judge_response(verdict="supported", passage="durable attitude change"),
            judge_response(verdict="supported", passage="prebunking interventions"),
        ]
    )
    check = ClaimSupportCheck(
        config=_config(),
        fetcher=LocalFileFetcher(SOURCES),
        transport=transport,
    )
    out = check.run(doc, CheckContext())

    assert out.findings == []


def test_low_confidence_verdict_is_silent(monkeypatch):
    """Bias-toward-silence: confidence below threshold → no finding."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    doc = _sample_doc()
    smith_passage = "durable attitude change requires repeated exposure"
    transport = FakeTransport(
        [
            judge_response(
                verdict="overstated",
                passage=smith_passage,
                confidence=0.3,  # below the 0.6 default → dropped before refuter
            ),
            judge_response(verdict="supported", passage="durable attitude change"),
            judge_response(verdict="supported", passage="prebunking interventions"),
        ]
    )
    check = ClaimSupportCheck(
        config=_config(),
        fetcher=LocalFileFetcher(SOURCES),
        transport=transport,
    )
    out = check.run(doc, CheckContext())

    assert out.findings == []
    roles = [c["role"] for c in transport.calls]
    assert roles == ["judge", "judge", "judge"]


def test_unverifiable_verdict_never_emits(monkeypatch):
    """`unverifiable` is a silent outcome — the LLM says it can't tell."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    doc = _sample_doc()
    transport = FakeTransport(
        [
            judge_response(verdict="unverifiable", passage=""),
            judge_response(verdict="unverifiable", passage=""),
            judge_response(verdict="unverifiable", passage=""),
        ]
    )
    check = ClaimSupportCheck(
        config=_config(),
        fetcher=LocalFileFetcher(SOURCES),
        transport=transport,
    )
    out = check.run(doc, CheckContext())
    assert out.findings == []


def test_source_unavailable_is_skipped_per_citation(monkeypatch, tmp_path):
    """A citation whose reference source can't be fetched is silently skipped.

    Not a finding, not an error — matches the check_quotes precedent
    (a check that couldn't run is a gap, not a fail). With no sources on
    disk, no LLM call happens at all.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    doc = _sample_doc()
    empty_fetcher = LocalFileFetcher(tmp_path / "empty")
    transport = FakeTransport([])  # must be untouched
    check = ClaimSupportCheck(
        config=_config(),
        fetcher=empty_fetcher,
        transport=transport,
    )
    out = check.run(doc, CheckContext())

    assert out.findings == []
    assert transport.calls == []
    # Ledger row records that we tried but had no sources.
    [row] = out.ledger
    assert row.status == "ok"
    assert row.result == 0
    assert "source" in (row.detail or "").lower()


def test_no_citations_emits_ok_ledger(monkeypatch):
    """A doc with no citations is a valid no-op, not an error."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    doc = FlattenedDoc(file="empty.txt", text="No references anywhere in this text.\n")
    transport = FakeTransport([])
    check = ClaimSupportCheck(
        config=_config(),
        fetcher=LocalFileFetcher(SOURCES),
        transport=transport,
    )
    out = check.run(doc, CheckContext())
    assert out.findings == []
    assert transport.calls == []
    [row] = out.ledger
    assert row.status == "ok"
    assert row.result == 0


def test_citation_cap_enforced(monkeypatch):
    """Per-doc citation cap: only the first N citations reach the LLM.

    This is one half of the cost-ceiling acceptance criterion. Combined
    with prompt-char truncation (tested separately), it caps LLM spend
    at a bounded worst-case per document.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    doc = _sample_doc()  # apa.txt has 7 citations with resolved refs
    transport = FakeTransport([judge_response(verdict="supported", passage="anything")])
    check = ClaimSupportCheck(
        # Cap to 1 citation regardless of the fixture size.
        config=_config(max_citations_per_doc=1),
        fetcher=LocalFileFetcher(SOURCES),
        transport=transport,
    )
    out = check.run(doc, CheckContext())

    # apa.txt's first resolved-reference candidate is Vance, whose source
    # file isn't on disk → the one kept candidate is skipped before any
    # LLM call. So zero calls even though the cap allows one.
    assert len(transport.calls) == 0
    [row] = out.ledger
    # Detail should surface the cap so the user sees which citations were skipped.
    assert row.detail and "cap" in row.detail.lower()


def test_transient_errors_retry_then_succeed(monkeypatch):
    """429/5xx retries follow the pangram pattern; permanent 4xx surfaces."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    doc = _sample_doc()
    smith_passage = "durable attitude change requires repeated exposure"
    transport = FakeTransport(
        [
            TransportRateLimit("[429] slow down"),
            TransportServerError(503, "unavailable"),
            judge_response(verdict="overstated", passage=smith_passage),
            refuter_response(outcome="upheld"),
            judge_response(verdict="supported", passage="durable attitude change"),
            judge_response(verdict="supported", passage="prebunking"),
        ]
    )
    check = ClaimSupportCheck(
        config=_config(max_attempts=3, initial_backoff_seconds=0.0),
        fetcher=LocalFileFetcher(SOURCES),
        transport=transport,
    )
    out = check.run(doc, CheckContext())

    # 2 retries + 1 success (Smith #1 judge) + refuter + Smith #2 judge +
    # Delacroix judge = 6 transport calls total.
    assert len(transport.calls) == 6
    assert len(out.findings) == 1


def test_permanent_transport_error_records_error_ledger(monkeypatch):
    """Auth failure is not a rate-limit blip — surfaces as an errored ledger row."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    doc = _sample_doc()
    transport = FakeTransport([TransportAuthError(401, "invalid key")])
    check = ClaimSupportCheck(
        config=_config(),
        fetcher=LocalFileFetcher(SOURCES),
        transport=transport,
    )
    out = check.run(doc, CheckContext())

    # No findings; ledger has an errored row so the report shows the gap.
    assert out.findings == []
    [row] = out.ledger
    assert row.status == "errored"
    assert row.reason and "401" in row.reason


def test_refuter_softened_still_emits_finding(monkeypatch):
    """`softened` is not `refuted` — the concern survives, with a note tag."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    doc = _sample_doc()
    smith_passage = "durable attitude change requires repeated exposure"
    transport = FakeTransport(
        [
            judge_response(verdict="overstated", passage=smith_passage),
            refuter_response(outcome="softened", reasoning="mild qualifier"),
            judge_response(verdict="supported", passage="durable attitude change"),
            judge_response(verdict="supported", passage="prebunking"),
        ]
    )
    check = ClaimSupportCheck(
        config=_config(),
        fetcher=LocalFileFetcher(SOURCES),
        transport=transport,
    )
    out = check.run(doc, CheckContext())

    assert len(out.findings) == 1
    f = out.findings[0]
    assert f.evidence["refuter_outcome"] == "softened"
    # The note reflects the softening so a reader knows the refuter half-agreed.
    assert f.note is not None
    assert "soften" in f.note.lower()


def test_mid_loop_error_preserves_prior_findings(monkeypatch):
    """A transport error after a good finding lands preserves that finding.

    Per CLAUDE.md's degrade-to-gaps rule: a partial evidence report is
    better than dropping real findings when the LLM later 401s.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    doc = _sample_doc()
    smith_passage = "durable attitude change requires repeated exposure"
    transport = FakeTransport(
        [
            judge_response(verdict="overstated", passage=smith_passage),
            refuter_response(outcome="upheld"),
            # Second citation: transport blows up permanently.
            TransportAuthError(401, "invalid key mid-run"),
        ]
    )
    check = ClaimSupportCheck(
        config=_config(),
        fetcher=LocalFileFetcher(SOURCES),
        transport=transport,
    )
    out = check.run(doc, CheckContext())

    # First finding survives.
    assert len(out.findings) == 1
    # Ledger shows the check errored so the reader knows the count isn't
    # authoritative.
    [row] = out.ledger
    assert row.status == "errored"
    assert row.reason and "401" in row.reason


def test_refusal_on_one_citation_does_not_abort_doc(monkeypatch):
    """`TransportRefusal` is per-citation: skip that one, continue the run."""
    from slopchecker.pipeline.claim_support.llm import TransportRefusal

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    doc = _sample_doc()
    # Citation-ordering note: apa.txt yields Smith×2 + Delacroix in that
    # order among the fetchable candidates. The Smith source contains the
    # 'durable attitude change' passage; the Delacroix source has the
    # 'sixty percent' passage. Each script item must be paired with the
    # source that actually contains the passage, or quotecheck drops the
    # would-be finding for the wrong reason.
    delacroix_passage = "roughly\nsixty percent of their measured effect"
    transport = FakeTransport(
        [
            # Citation 1 (Smith #1): judge refuses. Skip, don't abort.
            TransportRefusal("policy refusal on this claim"),
            # Citation 2 (Smith #2): normal supported.
            judge_response(verdict="supported", passage="durable attitude change"),
            # Citation 3 (Delacroix): concern, refuter upholds → finding.
            judge_response(verdict="overstated", passage=delacroix_passage),
            refuter_response(outcome="upheld"),
        ]
    )
    check = ClaimSupportCheck(
        config=_config(),
        fetcher=LocalFileFetcher(SOURCES),
        transport=transport,
    )
    out = check.run(doc, CheckContext())

    # The run continued past the refusal and produced the finding from
    # citation 3.
    assert len(out.findings) == 1
    [row] = out.ledger
    assert row.status == "ok"
    # Detail surfaces the refusal so the reader sees the gap.
    assert row.detail and "refused" in row.detail.lower()


def test_source_truncation_bounds_prompt_size(monkeypatch):
    """`max_source_chars` is the second half of the cost ceiling.

    The user text sent to the judge must be no larger than the truncated
    excerpt plus the surrounding claim/marker framing — never the raw
    (potentially many-MB) source.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    doc = _sample_doc()
    transport = FakeTransport(
        [
            judge_response(verdict="supported", passage="anything"),
            judge_response(verdict="supported", passage="anything"),
            judge_response(verdict="supported", passage="anything"),
        ]
    )
    check = ClaimSupportCheck(
        config=_config(max_source_chars=200),
        fetcher=LocalFileFetcher(SOURCES),
        transport=transport,
    )
    check.run(doc, CheckContext())

    # Every judge user prompt has an inline SOURCE TEXT chunk bounded by
    # max_source_chars. Full sources on disk are ~1KB each; truncated to
    # 200 means the total prompt has to be well under ~1500 chars.
    for call in transport.calls:
        if call["role"] != "judge":
            continue
        assert len(call["user"]) < 1500


def test_mixed_source_availability_reports_partial_gap(monkeypatch):
    """`source_gaps` appears in the ledger detail only when SOME sources fetched.

    apa.txt has 7 resolved citations but only Smith×2 + Delacroix have
    source files on disk → 4 source-unavailable gaps, 3 LLM calls.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    doc = _sample_doc()
    transport = FakeTransport(
        [
            judge_response(verdict="supported", passage="anything"),
            judge_response(verdict="supported", passage="anything"),
            judge_response(verdict="supported", passage="anything"),
        ]
    )
    check = ClaimSupportCheck(
        config=_config(),
        fetcher=LocalFileFetcher(SOURCES),
        transport=transport,
    )
    out = check.run(doc, CheckContext())

    # Exactly 3 LLM calls fired (Smith×2 + Delacroix).
    assert len([c for c in transport.calls if c["role"] == "judge"]) == 3
    [row] = out.ledger
    assert row.status == "ok"
    assert row.detail is not None
    # Detail reports the 4 citations without local source text.
    assert "source unavailable" in row.detail.lower()
    assert "4 citation" in row.detail


def test_malformed_llm_payload_becomes_errored_ledger(monkeypatch):
    """Schema slip → errored ledger row, not an uncaught exception.

    output_config.format enforces the schema server-side but "degrade to
    gaps, never crash" means we don't rely on that — a payload with a
    bogus verdict must land as a gap, not a stack trace.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    doc = _sample_doc()
    transport = FakeTransport(
        [
            {
                "_expect_role": "judge",
                "verdict": "not_a_real_enum_value",
                "supporting_passage": "",
                "confidence": 0.9,
                "reasoning": "malformed",
            },
        ]
    )
    check = ClaimSupportCheck(
        config=_config(),
        fetcher=LocalFileFetcher(SOURCES),
        transport=transport,
    )
    out = check.run(doc, CheckContext())

    assert out.findings == []
    [row] = out.ledger
    assert row.status == "errored"


def test_registered_under_llm_tier():
    """The check must appear in the registry under tier=llm, off by default via tier gating."""
    # Importing the subpackage runs @register; verify discovery finds it.
    from slopchecker.pipeline import registry

    # Force discovery even if another test already ran it.
    registry.discover()
    ids = {rc.meta.id for rc in registry.all_checks() if rc.meta.tier == "llm"}
    assert "claim_supported" in ids
