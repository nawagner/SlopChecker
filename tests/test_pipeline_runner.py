"""Registry + tiered runner (#5). All checks here are fakes: fast, offline."""

from __future__ import annotations

import time

import pytest

from slopchecker import config
from slopchecker.models import Check, EvidenceReport, Finding, FlattenedDoc, LedgerRow
from slopchecker.pipeline import (
    CheckContext,
    CheckOutput,
    RegisteredCheck,
    all_checks,
    discover,
    register,
    run_checks,
    select_checks,
)
from slopchecker.pipeline import registry as registry_mod

DOC = FlattenedDoc(file="sample.md", text="Prebunking achieves durable inoculation [1].")


@pytest.fixture
def clean_registry(monkeypatch):
    """Isolate the module-level registry so tests never leak registrations."""
    monkeypatch.setattr(registry_mod, "_REGISTRY", {})


def fake(check_id: str, tier: str = "deterministic", **kwargs) -> RegisteredCheck:
    """A RegisteredCheck whose fn emits one passing ledger row."""

    def fn(doc: FlattenedDoc, ctx: CheckContext) -> CheckOutput:
        return CheckOutput(ledger=[LedgerRow(check=check_id, result=True)])

    meta = Check(id=check_id, name=check_id, tier=tier)
    return RegisteredCheck(meta=meta, fn=fn, **kwargs)


def rows_by_check(report: EvidenceReport) -> dict[str, LedgerRow]:
    return {row.check: row for row in report.ledger}


# --- registration -----------------------------------------------------------


def test_register_adds_check_and_duplicate_id_raises(clean_registry):
    @register(id="c1", name="Check one", tier="deterministic")
    def c1(doc, ctx):
        return CheckOutput()

    assert [rc.meta.id for rc in all_checks()] == ["c1"]

    with pytest.raises(ValueError, match="already registered"):

        @register(id="c1", name="Check one again", tier="api")
        def c1_again(doc, ctx):
            return CheckOutput()


def test_discover_finds_builtin_checks(clean_registry, monkeypatch):
    # Drop the already-imported module so discover()'s import re-runs the
    # decorators against the clean registry. Also exercises the tolerated
    # absence of slopchecker.checks (Nick's package, not landed yet).
    import sys

    monkeypatch.delitem(sys.modules, "slopchecker.pipeline.checks_builtin", raising=False)
    discover()
    ids = {rc.meta.id for rc in all_checks()}
    assert {"has_text", "word_count"} <= ids


# --- selection --------------------------------------------------------------


def test_select_by_tier_only_skip():
    checks = [fake("det1"), fake("det2"), fake("api1", tier="api"), fake("llm1", tier="llm")]

    assert [rc.meta.id for rc in select_checks(checks, tier="api")] == ["api1"]
    assert [rc.meta.id for rc in select_checks(checks, only=["det2", "llm1"])] == ["det2", "llm1"]
    assert [rc.meta.id for rc in select_checks(checks, skip=["det1"])] == ["det2", "api1", "llm1"]
    # only + tier compose
    assert select_checks(checks, tier="llm", only=["det2", "llm1"])[0].meta.id == "llm1"


@pytest.mark.parametrize("kwargs", [{"only": ["nope"]}, {"skip": ["nope"]}, {"tier": "premium"}])
def test_select_unknown_ids_or_tier_raise(kwargs):
    with pytest.raises(ValueError):
        select_checks([fake("det1")], **kwargs)


# --- runner: happy path -----------------------------------------------------


def test_run_collects_ledger_and_findings():
    def with_finding(doc, ctx):
        return CheckOutput(
            ledger=[LedgerRow(check="finder", result=False)],
            findings=[Finding(id="C1", checks=[])],
            cost_usd=0.01,
        )

    checks = [
        fake("det1"),
        RegisteredCheck(meta=Check(id="finder", name="Finder", tier="api"), fn=with_finding),
    ]
    report = run_checks(DOC, checks)

    assert isinstance(report, EvidenceReport)
    assert rows_by_check(report)["det1"].result is True
    assert rows_by_check(report)["finder"].result is False
    assert [f.id for f in report.findings] == ["C1"]
    assert report.run.cost_usd == 0.01
    assert report.run.seconds is not None
    # the dict the renderer consumes round-trips
    assert report.to_report_dict()["ledger"][0]["check"] == "det1"


def test_tiers_run_in_order():
    started: list[str] = []

    def tracker(check_id: str, tier: str) -> RegisteredCheck:
        def fn(doc, ctx):
            started.append(check_id)
            return CheckOutput(ledger=[LedgerRow(check=check_id, result=True)])

        return RegisteredCheck(meta=Check(id=check_id, name=check_id, tier=tier), fn=fn)

    # Hand them to the runner llm-first; tier order must still win.
    report = run_checks(
        DOC, [tracker("l", "llm"), tracker("a", "api"), tracker("d", "deterministic")]
    )
    assert started == ["d", "a", "l"]
    assert len(report.ledger) == 3


def test_parallel_within_tier():
    def slow(doc, ctx):
        time.sleep(0.15)
        return CheckOutput(ledger=[LedgerRow(check="slow", result=True)])

    checks = [
        RegisteredCheck(meta=Check(id=f"slow{i}", name="s", tier="deterministic"), fn=slow)
        for i in range(3)
    ]
    t0 = time.monotonic()
    report = run_checks(DOC, checks)
    elapsed = time.monotonic() - t0
    assert len(report.ledger) == 3
    assert elapsed < 0.35, f"3 x 0.15s checks took {elapsed:.2f}s — not parallel"


# --- runner: error isolation, skips, timeouts (acceptance criteria) ---------


def test_raising_check_errors_and_run_continues():
    def boom(doc, ctx):
        raise RuntimeError("kaboom")

    checks = [
        RegisteredCheck(meta=Check(id="boom", name="Boom", tier="deterministic"), fn=boom),
        fake("survivor"),
        fake("later_tier", tier="llm"),
    ]
    report = run_checks(DOC, checks)
    rows = rows_by_check(report)

    assert rows["boom"].status == "errored"
    assert "RuntimeError: kaboom" in rows["boom"].reason
    assert rows["survivor"].status == "ok"
    assert rows["later_tier"].status == "ok"  # later tiers still ran


def test_missing_credential_reports_skipped(monkeypatch):
    monkeypatch.delenv("PANGRAM_API_KEY", raising=False)

    def needs_key(doc, ctx):
        config.require("PANGRAM_API_KEY")
        raise AssertionError("unreachable without the key")

    checks = [
        RegisteredCheck(
            meta=Check(id="pangram_document", name="Pangram", tier="api"), fn=needs_key
        ),
        fake("det1"),
    ]
    rows = rows_by_check(run_checks(DOC, checks))

    assert rows["pangram_document"].status == "skipped"
    assert rows["pangram_document"].reason == "missing PANGRAM_API_KEY"
    assert rows["det1"].status == "ok"


def test_timeout_errors_and_neighbors_survive():
    def sleepy(doc, ctx):
        time.sleep(0.25)
        return CheckOutput(ledger=[LedgerRow(check="sleepy", result=True)])

    checks = [
        RegisteredCheck(
            meta=Check(id="sleepy", name="Sleepy", tier="deterministic"), fn=sleepy, timeout_s=0.05
        ),
        fake("quick"),
    ]
    t0 = time.monotonic()
    rows = rows_by_check(run_checks(DOC, checks))
    assert time.monotonic() - t0 < 0.25, "runner waited past the timeout"

    assert rows["sleepy"].status == "errored"
    assert "timed out after 0.05s" in rows["sleepy"].reason
    assert rows["quick"].status == "ok"


def test_wrong_return_type_is_errored_not_fatal():
    def wrong(doc, ctx):
        return [LedgerRow(check="wrong", result=True)]  # a bare list, not CheckOutput

    checks = [RegisteredCheck(meta=Check(id="wrong", name="Wrong", tier="deterministic"), fn=wrong)]
    row = rows_by_check(run_checks(DOC, checks))["wrong"]
    assert row.status == "errored"
    assert "expected CheckOutput" in row.reason


def test_applies_to_false_reports_skipped():
    rc = fake("pdf_only", applies_to=lambda doc: doc.media_type == "application/pdf")
    rows = rows_by_check(run_checks(DOC, [rc]))
    assert rows["pdf_only"].status == "skipped"
    assert rows["pdf_only"].reason == "not applicable to this document"


# --- built-ins --------------------------------------------------------------


def test_builtin_has_text_and_word_count():
    from slopchecker.pipeline.checks_builtin import has_text, word_count

    ctx = CheckContext()
    assert has_text(DOC, ctx).ledger[0].result is True
    empty = FlattenedDoc(file="blank.pdf", text="   \n ")
    row = has_text(empty, ctx).ledger[0]
    assert row.result is False
    assert word_count(DOC, ctx).ledger[0].result == 5
