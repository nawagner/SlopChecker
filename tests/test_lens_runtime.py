"""Tests for the lens runtime (#13, runtime half).

Boundary the tests care about:

    (Lens, FlattenedDoc, config, fake LLMClient) → LensRunResult

The LLM is a `Transport`-style injection point (mirroring
``detect/pangram.py``); every test drives the runtime with an in-memory
fake and asserts on the runtime's own observable outputs — not on how
many times a mock was called.
"""

# ruff: noqa: E501 — fixture JSON and the load-bearing test quote run past 100 chars.

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from slopchecker.lenses import Lens
from slopchecker.models import FlattenedDoc
from slopchecker.pipeline.lens_runtime import (
    LensRunConfig,
    LensRunResult,
    TransportAuthError,
    TransportClientError,
    TransportRateLimit,
    TransportServerError,
    assemble_messages,
    run_lens,
)

# --- Test doubles ---------------------------------------------------------


@dataclass
class FakeClient:
    """In-memory LLMClient. Feed it a script of responses/exceptions to
    replay in order; every ``complete()`` pops the next entry."""

    script: list[str | Exception] = field(default_factory=list)
    calls: list[tuple[str, str, str]] = field(default_factory=list)

    def complete(self, system: str, user: str, *, model: str, max_tokens: int) -> str:
        self.calls.append((system, user, model))
        if not self.script:
            raise AssertionError("FakeClient exhausted")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


# --- Fixtures -------------------------------------------------------------


CLAIMS_LENS_TEXT = """---
id: claims
version: 0.1
output: json
---

# Claims lens

## System prompt

Extract load-bearing claims. Each `quote` must be a verbatim substring.

## Output format

```json
{"claims": [{"id": "CL1", "type": "outcome", "page": 1, "quote": "...", "quantitative": true, "citation": null}]}
```

## Example

### Input

```text
Meridian will deliver twelve regional trainings within the first grant year.
```

### Output

```json
{"claims": [{"id": "CL1", "type": "outcome", "page": 1, "quote": "Meridian will deliver twelve regional trainings within the first grant year", "quantitative": true, "citation": null}]}
```
"""


@pytest.fixture
def claims_lens(tmp_path: Path) -> Lens:
    """A minimal but real Lens parsed from a temp claims-shaped pack."""
    from slopchecker.lenses import load_lens

    path = tmp_path / "claims.md"
    path.write_text(CLAIMS_LENS_TEXT, encoding="utf-8")
    return load_lens("claims", directory=tmp_path)


@pytest.fixture
def sample_doc() -> FlattenedDoc:
    text = (
        "Meridian will deliver twelve regional trainings within the first grant year. "
        "The information environment has degraded rapidly."
    )
    return FlattenedDoc(file="fake.pdf", text=text)


@pytest.fixture
def sample_doc_with_pages() -> FlattenedDoc:
    text = "First page content.\nSecond page content.\nThird page content."
    # Page 1 starts at 0; page 2 at 20 (after "First page content.\n"); page 3 at 40.
    return FlattenedDoc(
        file="fake.pdf",
        text=text,
        page_offsets=[0, 20, 40],
        pages=3,
    )


# --- assemble_messages ----------------------------------------------------


def test_assemble_messages_puts_lens_system_prompt_in_system(claims_lens, sample_doc):
    system, user = assemble_messages(claims_lens, sample_doc)
    assert "Extract load-bearing claims" in system
    # Output-format spec is included so the model has the JSON contract.
    assert '"claims"' in system


def test_assemble_messages_puts_doc_text_in_user(claims_lens, sample_doc):
    _, user = assemble_messages(claims_lens, sample_doc)
    assert sample_doc.text in user


def test_assemble_messages_inserts_page_markers_when_offsets_known(
    claims_lens, sample_doc_with_pages
):
    _, user = assemble_messages(claims_lens, sample_doc_with_pages)
    # All three markers present, in order.
    assert user.index("[[page 1]]") < user.index("[[page 2]]") < user.index("[[page 3]]")
    # Marker sits immediately before its page's first line.
    assert "[[page 2]]" in user
    assert user.index("Second page content") > user.index("[[page 2]]")


def test_assemble_messages_omits_page_markers_when_no_offsets(claims_lens, sample_doc):
    _, user = assemble_messages(claims_lens, sample_doc)
    assert "[[page " not in user


# --- Happy path -----------------------------------------------------------


def test_run_lens_parses_valid_json_response(claims_lens, sample_doc):
    payload = {
        "claims": [
            {
                "id": "CL1",
                "type": "outcome",
                "page": 1,
                "quote": "Meridian will deliver twelve regional trainings",
                "quantitative": True,
                "citation": None,
            }
        ]
    }
    client = FakeClient(script=[json.dumps(payload)])
    result = run_lens(claims_lens, sample_doc, LensRunConfig(model="claude-test"), client=client)
    assert result.status == "ok"
    assert result.payload == payload
    assert result.model == "claude-test"
    assert result.provider == "anthropic"


def test_run_lens_tolerates_markdown_fenced_json(claims_lens, sample_doc):
    payload = {"claims": []}
    fenced = f"```json\n{json.dumps(payload)}\n```"
    client = FakeClient(script=[fenced])
    result = run_lens(claims_lens, sample_doc, LensRunConfig(), client=client)
    assert result.status == "ok"
    assert result.payload == payload


# --- Quote-anchoring: drop hallucinated claims ---------------------------


def test_run_lens_drops_claims_whose_quote_is_not_verbatim_substring(claims_lens, sample_doc):
    payload = {
        "claims": [
            {
                "id": "CL1",
                "type": "outcome",
                "page": 1,
                # Real substring of sample_doc.text
                "quote": "Meridian will deliver twelve regional trainings",
                "quantitative": True,
                "citation": None,
            },
            {
                "id": "CL2",
                "type": "impact",
                "page": 1,
                # NOT in sample_doc.text — hallucinated
                "quote": "the project will end world hunger by 2027",
                "quantitative": False,
                "citation": None,
            },
        ]
    }
    client = FakeClient(script=[json.dumps(payload)])
    result = run_lens(claims_lens, sample_doc, LensRunConfig(), client=client)
    assert result.status == "ok"
    kept = result.payload["claims"]
    assert len(kept) == 1
    assert kept[0]["id"] == "CL1"


def test_run_lens_keeps_all_claims_when_all_quotes_are_verbatim(claims_lens, sample_doc):
    payload = {
        "claims": [
            {
                "id": "CL1",
                "type": "outcome",
                "page": 1,
                "quote": "Meridian will deliver twelve regional trainings",
                "quantitative": True,
                "citation": None,
            },
            {
                "id": "CL2",
                "type": "prior-work",
                "page": 1,
                "quote": "The information environment has degraded rapidly",
                "quantitative": False,
                "citation": None,
            },
        ]
    }
    client = FakeClient(script=[json.dumps(payload)])
    result = run_lens(claims_lens, sample_doc, LensRunConfig(), client=client)
    assert result.status == "ok"
    assert len(result.payload["claims"]) == 2


# --- Retry loop -----------------------------------------------------------


def test_run_lens_retries_transport_rate_limit(claims_lens, sample_doc):
    payload = {"claims": []}
    client = FakeClient(
        script=[
            TransportRateLimit("429 slow down"),
            TransportRateLimit("429 slow down"),
            json.dumps(payload),
        ]
    )
    config = LensRunConfig(max_attempts=3, initial_backoff_seconds=0.0)
    result = run_lens(claims_lens, sample_doc, config, client=client)
    assert result.status == "ok"
    assert len(client.calls) == 3


def test_run_lens_retries_transport_server_error(claims_lens, sample_doc):
    payload = {"claims": []}
    client = FakeClient(
        script=[
            TransportServerError(503, "upstream unavailable"),
            json.dumps(payload),
        ]
    )
    config = LensRunConfig(max_attempts=3, initial_backoff_seconds=0.0)
    result = run_lens(claims_lens, sample_doc, config, client=client)
    assert result.status == "ok"


def test_run_lens_does_not_retry_auth_errors(claims_lens, sample_doc):
    """401/402 is permanent — surface immediately as errored, one attempt only."""
    client = FakeClient(script=[TransportAuthError(401, "bad key")])
    config = LensRunConfig(max_attempts=3, initial_backoff_seconds=0.0)
    result = run_lens(claims_lens, sample_doc, config, client=client)
    assert result.status == "errored"
    assert "401" in result.reason
    assert len(client.calls) == 1


def test_run_lens_does_not_retry_client_errors(claims_lens, sample_doc):
    """400/413/422 won't be fixed by a retry."""
    client = FakeClient(script=[TransportClientError(400, "invalid request")])
    config = LensRunConfig(max_attempts=3, initial_backoff_seconds=0.0)
    result = run_lens(claims_lens, sample_doc, config, client=client)
    assert result.status == "errored"
    assert len(client.calls) == 1


def test_run_lens_errors_after_retry_ceiling(claims_lens, sample_doc):
    client = FakeClient(
        script=[
            TransportRateLimit("429"),
            TransportRateLimit("429"),
            TransportRateLimit("429"),
        ]
    )
    config = LensRunConfig(max_attempts=3, initial_backoff_seconds=0.0)
    result = run_lens(claims_lens, sample_doc, config, client=client)
    assert result.status == "errored"
    assert "429" in result.reason
    assert len(client.calls) == 3


# --- Missing credential ---------------------------------------------------


def test_run_lens_without_client_and_missing_key_is_skipped(claims_lens, sample_doc, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = run_lens(claims_lens, sample_doc, LensRunConfig(), client=None)
    assert result.status == "skipped"
    assert "ANTHROPIC_API_KEY" in result.reason


# --- Cache ----------------------------------------------------------------


def test_run_lens_writes_and_reads_cache(claims_lens, sample_doc, tmp_path):
    payload = {"claims": []}
    client = FakeClient(script=[json.dumps(payload)])
    config = LensRunConfig(cache_dir=tmp_path, model="claude-test")

    first = run_lens(claims_lens, sample_doc, config, client=client)
    second = run_lens(claims_lens, sample_doc, config, client=client)

    assert first.status == "ok"
    assert second.status == "ok"
    # Same payload both times.
    assert first.payload == second.payload
    # Client called only once — second call hit cache (script would raise otherwise).
    assert len(client.calls) == 1


def test_cache_key_changes_when_model_changes(claims_lens, sample_doc, tmp_path):
    payload_v1 = {
        "claims": [
            {
                "id": "CL1",
                "type": "outcome",
                "page": 1,
                "quote": "Meridian will deliver twelve regional trainings",
                "quantitative": True,
                "citation": None,
            }
        ]
    }
    payload_v2 = {"claims": []}
    client = FakeClient(script=[json.dumps(payload_v1), json.dumps(payload_v2)])

    r1 = run_lens(
        claims_lens, sample_doc, LensRunConfig(cache_dir=tmp_path, model="m1"), client=client
    )
    r2 = run_lens(
        claims_lens, sample_doc, LensRunConfig(cache_dir=tmp_path, model="m2"), client=client
    )

    assert r1.payload == payload_v1
    assert r2.payload == payload_v2
    assert len(client.calls) == 2  # Both were real calls; different cache keys.


def test_cache_key_changes_when_lens_changes(sample_doc, tmp_path):
    """Two different lenses on the same doc must not share a cache slot."""
    from slopchecker.lenses import load_lens

    (tmp_path / "a.md").write_text(CLAIMS_LENS_TEXT, encoding="utf-8")
    b_text = CLAIMS_LENS_TEXT.replace("id: claims", "id: other")
    (tmp_path / "b.md").write_text(b_text, encoding="utf-8")
    lens_a = load_lens("a", directory=tmp_path)
    lens_b = load_lens("b", directory=tmp_path)

    cache = tmp_path / "cache"
    client = FakeClient(script=[json.dumps({"claims": []}), json.dumps({"claims": []})])
    run_lens(lens_a, sample_doc, LensRunConfig(cache_dir=cache), client=client)
    run_lens(lens_b, sample_doc, LensRunConfig(cache_dir=cache), client=client)
    assert len(client.calls) == 2  # Not de-duplicated across lenses.


def test_cache_key_changes_when_prompt_changes(sample_doc, tmp_path):
    """Editing a lens's prompt must invalidate its cache slot (#144).

    Same lens id, same doc, same model — but a tuned system prompt. Serving
    the pre-tune payload would make prompt tuning invisible until TTL expiry.
    """
    from slopchecker.lenses import load_lens

    (tmp_path / "v1").mkdir()
    (tmp_path / "v2").mkdir()
    (tmp_path / "v1" / "claims.md").write_text(CLAIMS_LENS_TEXT, encoding="utf-8")
    tuned = CLAIMS_LENS_TEXT.replace(
        "Extract load-bearing claims", "Extract only specific, checkable load-bearing claims"
    )
    assert tuned != CLAIMS_LENS_TEXT  # guard: the marker sentence must exist
    (tmp_path / "v2" / "claims.md").write_text(tuned, encoding="utf-8")
    lens_v1 = load_lens("claims", directory=tmp_path / "v1")
    lens_v2 = load_lens("claims", directory=tmp_path / "v2")

    cache = tmp_path / "cache"
    client = FakeClient(script=[json.dumps({"claims": []}), json.dumps({"claims": []})])
    run_lens(lens_v1, sample_doc, LensRunConfig(cache_dir=cache), client=client)
    run_lens(lens_v2, sample_doc, LensRunConfig(cache_dir=cache), client=client)
    assert len(client.calls) == 2  # Prompt change → cache miss, real second call.


def test_cache_does_not_write_on_error(claims_lens, sample_doc, tmp_path):
    """Errored runs must not be cached — a retry with a real key should retry the LLM."""
    err_client = FakeClient(script=[TransportAuthError(401, "bad key")])
    ok_client = FakeClient(script=[json.dumps({"claims": []})])
    config = LensRunConfig(cache_dir=tmp_path, model="claude-test")

    r1 = run_lens(claims_lens, sample_doc, config, client=err_client)
    r2 = run_lens(claims_lens, sample_doc, config, client=ok_client)

    assert r1.status == "errored"
    assert r2.status == "ok"


# --- Malformed JSON -------------------------------------------------------


def test_run_lens_errors_on_unparseable_json(claims_lens, sample_doc):
    client = FakeClient(script=["not json at all"])
    result = run_lens(claims_lens, sample_doc, LensRunConfig(), client=client)
    assert result.status == "errored"
    assert "json" in result.reason.lower()


def test_run_lens_errors_on_json_missing_claims_key(claims_lens, sample_doc):
    client = FakeClient(script=[json.dumps({"unexpected": []})])
    result = run_lens(claims_lens, sample_doc, LensRunConfig(), client=client)
    assert result.status == "errored"


# --- Result shape ---------------------------------------------------------


def test_lens_run_result_carries_provider_and_model(claims_lens, sample_doc):
    """Downstream (#37) needs these keys already present in Finding.evidence."""
    client = FakeClient(script=[json.dumps({"claims": []})])
    result = run_lens(claims_lens, sample_doc, LensRunConfig(model="claude-x"), client=client)
    assert isinstance(result, LensRunResult)
    assert result.provider == "anthropic"
    assert result.model == "claude-x"
