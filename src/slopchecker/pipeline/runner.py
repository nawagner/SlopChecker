"""Tiered pipeline runner (#5).

Executes checks tier by tier (deterministic → api → llm), in parallel within
a tier, with per-check timeouts and error isolation. "Degrade to gaps, never
crash": a check that raises becomes an ``errored`` ledger row, a check whose
credential is missing becomes ``skipped: missing PANGRAM_API_KEY``, and the
run continues either way.
"""

from __future__ import annotations

import time
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import date

from slopchecker import __version__
from slopchecker.config import MissingCredential
from slopchecker.models import (
    EvidenceReport,
    FlattenedDoc,
    LedgerRow,
    RunInfo,
)
from slopchecker.pipeline.registry import (
    TIER_ORDER,
    CheckContext,
    CheckOutput,
    RegisteredCheck,
)

_MAX_WORKERS = 8


def _call_check(rc: RegisteredCheck, doc: FlattenedDoc, ctx: CheckContext) -> CheckOutput:
    out = rc.fn(doc, ctx)
    if not isinstance(out, CheckOutput):
        raise TypeError(f"check '{rc.meta.id}' returned {type(out).__name__}, expected CheckOutput")
    return out


def _gap_row(rc: RegisteredCheck, status: str, reason: str) -> LedgerRow:
    return LedgerRow(check=rc.meta.id, label=rc.meta.name, status=status, reason=reason)


def _collect(rc: RegisteredCheck, future: Future, deadline: float) -> CheckOutput | LedgerRow:
    """One check's outcome: its CheckOutput, or the gap row that stands in."""
    try:
        return future.result(timeout=max(0.0, deadline - time.monotonic()))
    except MissingCredential as exc:
        return _gap_row(rc, "skipped", f"missing {exc.env_var}")
    except FutureTimeoutError:
        # The worker thread may still be running; we stop waiting and record
        # the gap. Fine for a screening run, revisit if a check holds the
        # interpreter open at exit.
        return _gap_row(rc, "errored", f"timed out after {rc.timeout_s:g}s")
    except Exception as exc:  # noqa: BLE001 — isolation is the whole point
        return _gap_row(rc, "errored", f"{type(exc).__name__}: {exc}")


def run_checks(
    doc: FlattenedDoc,
    checks: list[RegisteredCheck],
    *,
    context: CheckContext | None = None,
) -> EvidenceReport:
    """Run ``checks`` against ``doc`` and assemble the EvidenceReport.

    Callers pick the check list (usually ``select_checks(all_checks(), ...)``);
    the runner owns ordering, parallelism, timeouts, and gap rows.
    """
    ctx = context or CheckContext()
    started = time.monotonic()
    cost_usd = 0.0
    report = EvidenceReport(document=doc)

    for tier in TIER_ORDER:
        tier_checks = [rc for rc in checks if rc.meta.tier == tier]
        if not tier_checks:
            continue

        runnable: list[RegisteredCheck] = []
        for rc in tier_checks:
            if rc.applies_to is not None and not rc.applies_to(doc):
                report.ledger.append(_gap_row(rc, "skipped", "not applicable to this document"))
            else:
                runnable.append(rc)
        if not runnable:
            continue

        # No `with` block: its shutdown(wait=True) would join a timed-out
        # check's lingering thread, blocking the run past the timeout.
        pool = ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(runnable)))
        submitted = time.monotonic()
        futures = [pool.submit(_call_check, rc, doc, ctx) for rc in runnable]
        for rc, future in zip(runnable, futures, strict=True):
            outcome = _collect(rc, future, deadline=submitted + rc.timeout_s)
            if isinstance(outcome, LedgerRow):
                report.ledger.append(outcome)
            else:
                report.ledger.extend(outcome.ledger)
                report.findings.extend(outcome.findings)
                cost_usd += outcome.cost_usd
        pool.shutdown(wait=False, cancel_futures=True)

    report.run = RunInfo(
        date=date.today().isoformat(),
        seconds=round(time.monotonic() - started, 3),
        version=__version__,
        cost_usd=round(cost_usd, 6),
    )
    return report
