from __future__ import annotations

from fastapi.testclient import TestClient

from slopchecker import __version__
from slopchecker.web import app

client = TestClient(app)

PROPOSAL = b"This proposal will revolutionize grantmaking with seven words."


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


def test_check_hostile_filename_is_flattened():
    resp = client.post(
        "/check",
        params={"format": "json"},
        files={"file": ("../../etc/passwd oops.txt", PROPOSAL, "text/plain")},
    )
    assert resp.status_code == 200
    # Basename only, unsafe characters flattened — no traversal into the header.
    assert resp.json()["document"]["file"] == "passwd_oops.txt"
