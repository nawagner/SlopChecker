from __future__ import annotations

import pytest

from slopchecker import config


def test_blank_env_var_reads_as_absent(monkeypatch):
    """`.env.example` ships keys with empty values; copying it to `.env`
    unedited must not look like a set-but-empty key."""
    monkeypatch.setenv("PANGRAM_API_KEY", "   ")
    assert config.get("PANGRAM_API_KEY") is None


def test_require_raises_named_missing_credential(monkeypatch):
    monkeypatch.delenv("PANGRAM_API_KEY", raising=False)
    with pytest.raises(config.MissingCredential) as excinfo:
        config.require("PANGRAM_API_KEY")
    assert excinfo.value.env_var == "PANGRAM_API_KEY"


def test_llm_model_defaults(monkeypatch):
    monkeypatch.delenv("SLOPCHECK_LLM_MODEL", raising=False)
    assert config.llm_model() == config.DEFAULT_LLM_MODEL


def test_llm_model_override(monkeypatch):
    monkeypatch.setenv("SLOPCHECK_LLM_MODEL", "claude-sonnet-5")
    assert config.llm_model() == "claude-sonnet-5"


def test_mask_hides_all_but_last_four():
    masked = config.mask("sk-ant-secret-value-1234")
    assert masked == "…1234"
    assert "secret" not in masked


def test_status_never_returns_a_raw_secret(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-supersecret")
    monkeypatch.setenv("CROSSREF_MAILTO", "team@example.org")
    by_var = {cred.env_var: display for cred, display in config.status()}
    assert by_var["ANTHROPIC_API_KEY"] == "…cret"
    # Non-secret values are shown in full — a contact email is meant to be read.
    assert by_var["CROSSREF_MAILTO"] == "team@example.org"
