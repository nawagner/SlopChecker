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

from slopchecker.checks.cache import CONTENT_HASH_TTL_S, remote_cache
from slopchecker.detect import PangramConfig, PangramDetector
from slopchecker.models import Finding, FlattenedDoc, LedgerRow
from slopchecker.pipeline.registry import CheckContext, CheckOutput, register

# The report shows the MOST AI-like passages, ranked by Pangram's per-window
# score, not every AI-labeled window — a heavily-AI document would otherwise
# wallpaper the report and bury the rest of the evidence. The cut is stated
# in the ledger detail, never silent.
_MAX_AI_PASSAGES = 5


def _window_score(finding: Finding) -> float:
    for check in finding.checks:
        if check.name == "pangram_window_ai_score" and isinstance(check.result, (int, float)):
            return float(check.result)
    return 0.0


def _rank_findings(findings: list[Finding]) -> list[Finding]:
    """Top passages by AI score, relabeled with their rank.

    The detector's own label ("AI-Generated" / "AI-Assisted") moves to
    evidence; the display label carries rank + score so the report reads
    as a ranked list of the most AI-like passages.
    """
    ranked = sorted(findings, key=_window_score, reverse=True)[:_MAX_AI_PASSAGES]
    out: list[Finding] = []
    for rank, finding in enumerate(ranked, start=1):
        score = _window_score(finding)
        out.append(
            finding.model_copy(
                update={
                    "label": f"Most AI-like passage #{rank}",
                    "note": f"Pangram score {score:.2f} ({finding.label})",
                }
            )
        )
    return out


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

    A fresh `PangramDetector` is instantiated per call. No `cache_dir` — the
    server filesystem is ephemeral, which is exactly why the shared KV cache
    (#119) exists: keyed on the content hash, it survives deploys and is shared
    across runs, so re-running the same document costs nothing. Unconfigured
    (`SLOPCHECK_CACHE_URL` / `SLOPCHECK_CACHE_TOKEN` unset) it is simply None
    and the check behaves exactly as before.

    `--no-cache` is honoured here rather than inside the detector, so the flag
    means the same thing for every tier.

    The detector itself handles a missing API key, transport failures, and
    retries; this function never raises.
    """
    cache = None if ctx.no_cache else remote_cache(ttl_s=CONTENT_HASH_TTL_S)
    detector = PangramDetector(PangramConfig(cache=cache))
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

    findings = _rank_findings(result.findings)

    # Total score stays the headline: enrich the doc-level row's detail with
    # the passage ranking so ledger-only readers still get both numbers.
    if ledger_row.status == "ok" and findings:
        shown = ", ".join(f"{_window_score(f):.2f}" for f in findings)
        suffix = (
            f" (showing top {len(findings)} of {len(result.findings)})"
            if len(result.findings) > len(findings)
            else ""
        )
        ledger_row = ledger_row.model_copy(
            update={
                "detail": f"fraction of text AI-classified; "
                f"most AI-like passage scores: {shown}{suffix}"
            }
        )

    return CheckOutput(
        ledger=[ledger_row],
        findings=findings,
        cost_usd=result.cost_usd,
    )
