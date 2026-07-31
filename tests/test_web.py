from __future__ import annotations

from fastapi.testclient import TestClient

from slopchecker import __version__
from slopchecker.web import app

client = TestClient(app)

PROPOSAL = b"This proposal will revolutionize grantmaking with seven words."

# Deliberately minimal, and deliberately not the real fixtures: enough to make
# rubric_budget_ceiling fire (a cap phrase on the rubric side, a "total" line
# on the proposal side) with no citations or DOIs, so no check in the run wants
# the network. The real fixtures are exercised by tests/test_checks_rubric.py.
BUDGET_PROPOSAL = b"# Budget request\n\n| Line item | Amount |\n| Total | $90,000 |\n"
RUBRIC = b"# Aldergrove climate RFP\n\n- Maximum award: $75,000 total costs\n"


def _rubric_run(fmt: str = "json", rubric: bytes | None = RUBRIC):
    files = {"file": ("proposal.md", BUDGET_PROPOSAL, "text/markdown")}
    if rubric is not None:
        files["rubric"] = ("aldergrove-rfp.md", rubric, "text/markdown")
    return client.post("/check", params={"format": fmt}, files=files)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "version": __version__}


def test_config_reports_booleans_not_values(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-never-appear-in-response")
    monkeypatch.delenv("PANGRAM_API_KEY", raising=False)

    resp = client.get("/config")
    assert resp.status_code == 200
    body = resp.json()

    assert "sk-ant-should-never-appear-in-response" not in resp.text

    by_var = {c["env_var"]: c for c in body["credentials"]}
    assert by_var["ANTHROPIC_API_KEY"]["set"] is True
    assert by_var["PANGRAM_API_KEY"]["set"] is False
    # Only "set" is a bool; nothing else on the record could carry a value fragment.
    assert set(by_var["ANTHROPIC_API_KEY"].keys()) == {"env_var", "purpose", "set"}


def test_check_renders_html_report():
    resp = client.post("/check", files={"file": ("proposal.txt", PROPOSAL, "text/plain")})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "SlopChecker — Evidence Report — proposal.txt" in resp.text
    # The built-in checks actually ran against the uploaded text.
    assert "Document has extractable text" in resp.text
    assert "Word count" in resp.text


def test_check_json_format_returns_report_dict():
    resp = client.post(
        "/check",
        params={"format": "json"},
        files={"file": ("proposal.md", b"# Title\n\nSome body text.", "text/markdown")},
    )
    assert resp.status_code == 200
    report = resp.json()
    assert report["schema_version"] == "0.1"
    assert report["document"]["file"] == "proposal.md"
    checks_run = {row["check"] for row in report["ledger"]}
    assert {"has_text", "word_count"} <= checks_run


def test_check_unsupported_format_is_422_with_reason():
    resp = client.post("/check", files={"file": ("virus.exe", b"MZ", "application/x-msdownload")})
    assert resp.status_code == 422
    assert "unsupported format" in resp.json()["detail"]
    assert ".pdf" in resp.json()["detail"]  # the reason is actionable


def test_check_empty_upload_is_422():
    resp = client.post("/check", files={"file": ("empty.txt", b"", "text/plain")})
    assert resp.status_code == 422


def test_check_with_rubric_runs_rubric_checks():
    report = _rubric_run().json()
    rows = {row["check"]: row for row in report["ledger"]}
    row = rows["rubric_budget_ceiling"]
    # The check ran (not a coverage gap) and caught the ceiling breach.
    assert row.get("status", "ok") == "ok"
    assert row["result"] is False
    # The upload is stamped with what it was measured against.
    assert report["solicitation"] == "aldergrove-rfp.md"
    evidence = next(
        f["evidence"] for f in report["findings"] if f["id"] == "rubric-budget-ceiling-exceeded"
    )
    assert evidence["ceiling_usd"] == 75000
    assert evidence["budget_total_usd"] == 90000
    assert evidence["rubric_file"] == "aldergrove-rfp.md"


def test_check_with_rubric_renders_the_two_quote_pair():
    html = _rubric_run(fmt="html").text
    assert "Checked against: aldergrove-rfp.md" in html
    assert "The solicitation requires" in html
    assert "<blockquote>- Maximum award: $75,000 total costs</blockquote>" in html
    assert "<blockquote>| Total | $90,000 |</blockquote>" in html


def test_check_without_rubric_reports_a_gap_not_a_pass():
    report = _rubric_run(rubric=None).json()
    row = next(r for r in report["ledger"] if r["check"] == "rubric_budget_ceiling")
    assert row["status"] == "skipped"
    assert row["reason"] == "no solicitation or rubric supplied — compliance not checked"
    assert "result" not in row  # a gap is not a pass
    assert report.get("solicitation") is None


def test_bad_rubric_is_422_naming_the_rubric():
    resp = client.post(
        "/check",
        files={
            "file": ("proposal.md", BUDGET_PROPOSAL, "text/markdown"),
            "rubric": ("rules.exe", b"MZ", "application/x-msdownload"),
        },
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    # Which file to swap, plus the pipeline's own reason.
    assert detail.startswith("rubric: ")
    assert "unsupported format" in detail


def test_empty_rubric_is_422_and_the_proposal_is_not_blamed():
    resp = client.post(
        "/check",
        files={
            "file": ("proposal.md", BUDGET_PROPOSAL, "text/markdown"),
            "rubric": ("empty.md", b"", "text/markdown"),
        },
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "rubric: empty upload"


def test_hostile_rubric_filename_is_flattened():
    report = client.post(
        "/check",
        params={"format": "json"},
        files={
            "file": ("proposal.md", BUDGET_PROPOSAL, "text/markdown"),
            "rubric": ("../../etc/rfp oops.md", RUBRIC, "text/markdown"),
        },
    ).json()
    assert report["solicitation"] == "rfp_oops.md"


def test_check_hostile_filename_is_flattened():
    resp = client.post(
        "/check",
        params={"format": "json"},
        files={"file": ("../../etc/passwd oops.txt", PROPOSAL, "text/plain")},
    )
    assert resp.status_code == 200
    # Basename only, unsafe characters flattened — no traversal into the header.
    assert resp.json()["document"]["file"] == "passwd_oops.txt"
