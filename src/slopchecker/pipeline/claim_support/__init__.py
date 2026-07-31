"""#11 claim-support LLM check.

The highest-risk check in the tree: for each (claim, citation) pair with a
retrievable source, ask an LLM whether the source supports the claim, then
ask a second LLM turn to refute the judgment. Every emitted Finding carries
a passage the LLM claimed *and* mechanically verified via ``match_quote``.

Behind ``--tier llm``, off by default; bias hard toward silence — only
``overstated``/``unsupported``/``contradicted`` verdicts that survive the
refuter reach the report as concerns. See ``check.py`` for the entry
point and ``llm.py`` for the transport layer.
"""

from __future__ import annotations

# Importing `check` registers the ``claim_supported`` check via @register.
from slopchecker.pipeline.claim_support import check as _check  # noqa: F401
from slopchecker.pipeline.claim_support.check import ClaimSupportCheck, ClaimSupportConfig

__all__ = ["ClaimSupportCheck", "ClaimSupportConfig"]
