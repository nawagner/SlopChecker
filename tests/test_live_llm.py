"""Real-key smoke of the LLM/API tier plumbing (#142).

Opt-in: ``pytest -m live_llm`` (deselected by addopts, like ``live``). Each
test additionally skips cleanly when its key isn't in the environment, so the
CI job is inert until a human sets the repo secrets.

Why this exists: the checks in here are exactly the code Railway executes on
every live upload — and before #142 no automated test anywhere executed them
with a real client (#115, ``ModuleNotFoundError: anthropic`` on every upload,
shipped through green CI). Unit suites cover the logic with fake transports;
this file covers the seam those fakes stand in for: real SDK import, real
auth, real response shapes.

Assertions are about plumbing, not model behavior — a row must come back
``ok`` (or a reasoned ``skipped`` where the check's preconditions aren't met),
never ``errored``, and findings must honor the quote-anchor contract. No
assertion depends on what the model happens to say.

Cost ceiling: one small fabricated fixture (harness corpus), a handful of
calls per run. Keep it that way.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from slopchecker.ingest import ingest
from slopchecker.models import EvidenceReport
from slopchecker.pipeline import all_checks, build_context, discover, run_checks, select_checks

pytestmark = pytest.mark.live_llm

HARNESS_FIXTURES = Path(__file__).resolve().parents[1] / "harness" / "fixtures"


def _key_set(var: str) -> bool:
    return bool(os.environ.get(var, "").strip())


requires_anthropic = pytest.mark.skipif(
    not _key_set("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY not set"
)
requires_pangram = pytest.mark.skipif(
    not _key_set("PANGRAM_API_KEY"), reason="PANGRAM_API_KEY not set"
)


@pytest.fixture(scope="module")
def doc():
    discover()
    result = ingest(HARNESS_FIXTURES / "proposal_climate.md")
    assert result.status == "ok" and result.document is not None
    return result.document


def _run_only(doc, check_id: str) -> EvidenceReport:
    checks = select_checks(all_checks(), tier="all", only=[check_id], skip=[])
    return run_checks(doc, checks, context=build_context([doc]))


@requires_anthropic
def test_claims_lens_runs_against_real_anthropic(doc):
    report = _run_only(doc, "claims")
    rows = {row.check: row for row in report.ledger}
    row = rows["claims"]
    assert row.status == "ok", f"claims errored/skipped with a real key: {row.reason!r}"
    # Quote-anchor contract holds all the way through a real model response.
    for finding in report.findings:
        if finding.anchor is not None:
            assert finding.anchor.quote and finding.anchor.quote in doc.text


@requires_anthropic
def test_claim_support_never_errors_with_real_key(doc):
    """`claim_supported` may legitimately skip (no resolvable cited sources in
    the fabricated fixture) — but with a real key it must never *error*."""
    report = _run_only(doc, "claim_supported")
    rows = {row.check: row for row in report.ledger}
    row = rows["claim_supported"]
    assert row.status in ("ok", "skipped"), f"errored: {row.reason!r}"
    if row.status == "skipped":
        assert row.reason


@requires_pangram
def test_pangram_document_runs_against_real_api(doc):
    report = _run_only(doc, "pangram_document")
    rows = {row.check: row for row in report.ledger}
    row = rows["pangram_document"]
    assert row.status == "ok", f"pangram errored/skipped with a real key: {row.reason!r}"
    assert isinstance(row.result, int | float) and 0.0 <= row.result <= 1.0
