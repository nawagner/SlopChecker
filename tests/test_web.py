from __future__ import annotations

from fastapi.testclient import TestClient

from slopchecker import __version__
from slopchecker.web import app

client = TestClient(app)


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
