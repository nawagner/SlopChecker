"""Tests for #7's registered check: citations_linked."""

from __future__ import annotations

import slopchecker.pipeline.checks_citations  # noqa: F401  (runs @register regardless of order)
from slopchecker.models import FlattenedDoc
from slopchecker.pipeline import all_checks, discover
from slopchecker.pipeline.checks_citations import citations_linked
from slopchecker.pipeline.registry import CheckContext

ORPHAN_TEXT = (
    "Recent field trials show durable gains from prebunking interventions [1]. "
    "Cross-platform replication has proven more difficult than expected [3].\n\n"
    "References\n\n"
    '[1] J. Okafor, "Prebunking at scale," Journal of Applied Misinformation Studies, '
    "vol. 4, no. 2, pp. 10-22, 2021.\n"
)

LINKED_TEXT = (
    "Recent field trials show durable gains from prebunking interventions [1]. "
    "Cross-platform replication has proven more difficult than expected [2].\n\n"
    "References\n\n"
    '[1] J. Okafor, "Prebunking at scale," Journal of Applied Misinformation Studies, '
    "vol. 4, no. 2, pp. 10-22, 2021.\n"
    '[2] M. Reyes, "Cross-platform replication of prebunking effects," '
    "Journal of Applied Misinformation Studies, vol. 5, no. 1, pp. 30-40, 2022.\n"
)

NO_CITATIONS_TEXT = (
    "This is a plain proposal narrative with no in-text citation markers at all, just prose."
)


def _ctx() -> CheckContext:
    return CheckContext()


def test_orphan_marker_fails_and_details_the_target():
    doc = FlattenedDoc(file="orphan.txt", text=ORPHAN_TEXT)
    out = citations_linked(doc, _ctx())

    row = out.ledger[0]
    assert row.result is False
    assert "[3]" in row.detail

    assert len(out.findings) == 1
    finding = out.findings[0]
    assert finding.anchor is not None
    assert finding.anchor.quote  # non-empty
    assert finding.anchor.quote in ORPHAN_TEXT  # verbatim in source text


def test_fully_linked_document_passes_with_no_findings():
    doc = FlattenedDoc(file="linked.txt", text=LINKED_TEXT)
    out = citations_linked(doc, _ctx())

    row = out.ledger[0]
    assert row.result is True
    assert out.findings == []


def test_no_citations_reports_gap_and_passes():
    doc = FlattenedDoc(file="none.txt", text=NO_CITATIONS_TEXT)
    out = citations_linked(doc, _ctx())

    row = out.ledger[0]
    assert row.result is True
    assert row.detail == "no in-text citations found"
    assert out.findings == []


def test_registered_via_discovery():
    discover()
    matches = [rc for rc in all_checks() if rc.meta.id == "citations_linked"]
    assert len(matches) == 1
    assert matches[0].meta.tier == "deterministic"
