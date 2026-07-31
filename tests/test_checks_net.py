"""The HTTP layer's decisions (#8), offline — no request is made in this file.

Classification is where the module's wording discipline is actually enforced,
so it gets tested without a network in the way.
"""

from __future__ import annotations

import pytest

from slopchecker.checks.net import Outcome, Resolution, classify, user_agent


@pytest.mark.parametrize(
    "status,expected",
    [
        (200, Outcome.resolves),
        (204, Outcome.resolves),
        (302, Outcome.resolves),  # redirects are followed before we classify
        (404, Outcome.not_found),
        (410, Outcome.not_found),
        # Paywalls, bot walls, and rate limits are not evidence of a fake source.
        (401, Outcome.blocked),
        (403, Outcome.blocked),
        (429, Outcome.blocked),
        (451, Outcome.blocked),
        (418, Outcome.blocked),
        # Server-side breakage is our inability to check, not their absence.
        (500, Outcome.unreachable),
        (503, Outcome.unreachable),
    ],
)
def test_classify(status: int, expected: Outcome) -> None:
    assert classify(status) is expected


def test_only_404_style_answers_count_against_a_document() -> None:
    """The rule the ledger boolean depends on, stated as a test."""
    against = {s for s in (200, 403, 404, 410, 429, 500) if classify(s) is Outcome.not_found}
    assert against == {404, 410}


def test_user_agent_identifies_the_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CROSSREF_MAILTO", raising=False)
    agent = user_agent()
    assert agent.startswith("SlopChecker/")
    assert "github.com/nawagner/SlopChecker" in agent
    assert "mailto" not in agent


def test_user_agent_joins_the_polite_pool_when_a_mailto_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CROSSREF_MAILTO is a courtesy, never a credential — unset must work too."""
    monkeypatch.setenv("CROSSREF_MAILTO", "team@example.org")
    assert "mailto:team@example.org" in user_agent()


def test_transport_failure_is_flagged_separately() -> None:
    """ "We have no network" must never look like "the citation is bad"."""
    resolution = Resolution(
        url="https://example.invalid/x",
        outcome=Outcome.unreachable,
        error="ConnectError: name resolution failed",
        transport_error=True,
    )
    assert not resolution.ok
    assert resolution.transport_error
    assert resolution.as_evidence()["outcome"] == "unreachable"


def test_evidence_omits_absent_fields() -> None:
    evidence = Resolution(url="https://example.org", outcome=Outcome.resolves, http_status=200)
    assert evidence.as_evidence() == {
        "outcome": "resolves",
        "requested": "https://example.org",
        "http_status": 200,
    }
