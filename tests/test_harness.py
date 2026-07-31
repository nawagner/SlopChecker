"""End-to-end canary for the planted-defect harness (#29).

Runs the real harness against the real fixtures + defects.yaml, in a
temp `out/` dir. Asserts the expected recall shape so a regression in
citation extraction, quote-matching, injection, or the harness's own
match vocabulary shows up as a test failure.

Offline, deterministic, part of the normal pytest run.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "harness"))

# Skip cleanly if pyyaml isn't installed (harness is an optional extra).
pytest.importorskip("yaml")

from injector import inject  # noqa: E402
from run import run_harness  # noqa: E402

HARNESS_DIR = REPO / "harness"
FIXTURES = HARNESS_DIR / "fixtures"
DEFECTS = HARNESS_DIR / "defects.yaml"
SOURCES = HARNESS_DIR / "sources"


def test_harness_end_to_end_matches_expected_outcomes(tmp_path):
    """Run the real harness; assert every defect's outcome matches expectation.

    This is the canary that flags regressions in the checks under it: if
    citation extraction stops surfacing unlinked markers, the two
    cite-* defects flip to MISS. If quote-matching starts fuzzy-passing
    the mutated quote, the quote-* defect flips to MISS. Either way the
    test tells you exactly which defect broke.
    """
    summary = run_harness(
        fixtures_dir=FIXTURES,
        defects_file=DEFECTS,
        sources_dir=SOURCES,
        out_dir=tmp_path,
        today="0000-00-00",  # deterministic path for the mutated dir
    )

    outcomes = {d["id"]: d["outcome"] for d in summary["per_defect"]}
    assert outcomes == {
        "cite-orphan-climate": "HIT",
        "cite-missing-ref-climate": "HIT",
        "quote-mutated-edu": "HIT",
        "unsupported-claim-climate": "PENDING",
        "misattr-edu": "PENDING",
    }
    assert summary["hits"] == 3
    assert summary["misses"] == 0
    assert summary["pending"] == 2
    assert summary["runnable_total"] == 3

    # The recall report file was written and mentions the top-line number.
    report_text = summary["report_path"].read_text()
    assert "Recall (deterministic tier): 3/3" in report_text
    assert "cite-orphan-climate" in report_text


def test_injector_missing_original_is_hard_error(tmp_path):
    """A defect whose `original` text isn't in the fixture must fail loudly.

    A silently unplanted defect would count as MISS forever and drag recall
    for a reason unrelated to check quality — hence the hard error.
    """
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    (fixtures / "sample.md").write_text("hello world\n")

    defects = [
        {
            "id": "phantom",
            "file": "sample.md",
            "original": "text that does not exist",
            "mutated": "replacement",
        }
    ]
    with pytest.raises(ValueError, match="original text not found"):
        inject(fixtures, defects, tmp_path / "mutated")


def test_injector_missing_file_is_hard_error(tmp_path):
    """A defect that names a file not in fixtures is also a hard error."""
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    (fixtures / "real.md").write_text("hi\n")

    defects = [
        {
            "id": "wrong-file",
            "file": "missing.md",
            "original": "hi",
            "mutated": "bye",
        }
    ]
    with pytest.raises(ValueError, match="not in fixtures dir"):
        inject(fixtures, defects, tmp_path / "mutated")


def test_injector_deletion_via_empty_mutated(tmp_path):
    """`mutated: ""` deletes the `original` span; used by cite-missing-ref-*."""
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    (fixtures / "doc.md").write_text("keep this. DELETE THIS. keep this too.\n")

    manifest = inject(
        fixtures,
        [{"id": "d1", "file": "doc.md", "original": "DELETE THIS. ", "mutated": ""}],
        tmp_path / "mutated",
    )
    assert manifest[0]["line"] == 1
    result = (tmp_path / "mutated" / "doc.md").read_text()
    assert result == "keep this. keep this too.\n"
