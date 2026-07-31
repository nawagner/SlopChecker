"""Pangram AI-detection check (#12, #23): wires `PangramDetector` into the registry.

Registering this check means every pipeline run that includes the ``api``
tier sends document text to Pangram's API — but only when
``PANGRAM_API_KEY`` is set in the environment. Without the key the detector
degrades internally to a ``skipped`` coverage-gap row and no document text
ever leaves the process. That means the #23 data-handling decision (whether
sending applicant text to a third-party API is acceptable) gates on whether
the key is set in production, not on anything in this module.
"""

from __future__ import annotations

from slopchecker.detect import PangramConfig, PangramDetector
from slopchecker.models import FlattenedDoc, LedgerRow
from slopchecker.pipeline.registry import CheckContext, CheckOutput, register


@register(
    id="pangram_document",
    name="AI detection (Pangram)",
    tier="api",
    needs_network=True,
    timeout_s=120.0,
    # est_cost_usd left at 0.0: registry metadata is static, but real per-run
    # spend is returned via CheckOutput.cost_usd, and a per-document estimate
    # (for --dry-run) needs PangramDetector.estimate_cost(doc), not a constant.
)
def pangram_document(doc: FlattenedDoc, ctx: CheckContext) -> CheckOutput:
    """Run Pangram's AI-detection API on `doc` and map the result to a `CheckOutput`.

    A fresh `PangramDetector` is instantiated per call (no `cache_dir` — the
    server filesystem is ephemeral). The detector itself handles a missing
    API key, transport failures, and retries; this function never raises.
    """
    detector = PangramDetector(PangramConfig())
    result = detector.check(doc)

    ledger_row = result.ledger_row
    if ledger_row is None:
        # Defensive only — the detector's own discipline guarantees a ledger
        # row for all three statuses. Should this invariant ever slip, still
        # degrade to a gap rather than crash the run.
        ledger_row = LedgerRow(
            check="pangram_document",
            label="AI detection (Pangram)",
            status="errored",
            reason=result.reason or "detector returned no ledger row",
        )

    return CheckOutput(
        ledger=[ledger_row],
        findings=result.findings,
        cost_usd=result.cost_usd,
    )
