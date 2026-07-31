"""Environment-backed credentials.

Nothing here is required at import time. A check that needs a key calls
`require()` and gets `MissingCredential` if it isn't set; the runner turns that
into a `skipped: missing PANGRAM_API_KEY` entry in the report rather than
killing the run (#5). That keeps a no-keys checkout useful — the deterministic
tier still runs and the report says plainly what was skipped and why.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_LLM_MODEL = "claude-opus-5"


@dataclass(frozen=True)
class Credential:
    env_var: str
    purpose: str
    secret: bool = True


CREDENTIALS: tuple[Credential, ...] = (
    Credential("ANTHROPIC_API_KEY", "LLM tier: claims, citation support, budget review"),
    Credential("PANGRAM_API_KEY", "AI-generated text detection"),
    # Crossref's REST API needs no auth at all — this is a courtesy header,
    # not a credential. #8's DOI resolution must work with this unset; never
    # gate that check behind config.require("CROSSREF_MAILTO").
    Credential(
        "CROSSREF_MAILTO",
        "Contact email for Crossref's polite pool (optional, no auth needed)",
        secret=False,
    ),
    Credential("CANDID_API_KEY", "Prior-funding lookups against the Candid grants dataset"),
)


class MissingCredential(RuntimeError):
    """Raised by `require()`. Caught by the runner and recorded as `skipped`."""

    def __init__(self, env_var: str) -> None:
        self.env_var = env_var
        super().__init__(f"missing {env_var}")


def load(env_file: Path | None = None) -> None:
    """Read `.env` into the environment. Real environment variables win, so CI
    secrets and shell exports are never shadowed by a stale local file."""
    load_dotenv(dotenv_path=env_file, override=False)


def get(env_var: str) -> str | None:
    """Value of `env_var`, or None if unset or blank. A key left empty in
    `.env.example` reads as absent rather than as an empty-string key."""
    return os.environ.get(env_var, "").strip() or None


def require(env_var: str) -> str:
    value = get(env_var)
    if value is None:
        raise MissingCredential(env_var)
    return value


def llm_model() -> str:
    return get("SLOPCHECK_LLM_MODEL") or DEFAULT_LLM_MODEL


def mask(value: str) -> str:
    """Last 4 characters only — enough to tell two keys apart in a terminal
    without putting a usable secret on screen or into a screenshot."""
    return f"…{value[-4:]}" if len(value) > 4 else "…"


def status() -> list[tuple[Credential, str | None]]:
    """Every credential paired with its display value (masked if secret)."""
    out = []
    for cred in CREDENTIALS:
        value = get(cred.env_var)
        if value is None:
            out.append((cred, None))
        else:
            out.append((cred, mask(value) if cred.secret else value))
    return out
