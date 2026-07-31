"""Check registry + tiered runner (#5). See registry.py for how to add a check.

Subpackages: ``citations`` (extraction, #7) and ``quotes`` (quote checking,
#10) — import those directly.
"""

from collections.abc import Sequence

from slopchecker.models import FlattenedDoc
from slopchecker.pipeline.registry import (
    TIER_ORDER,
    CheckContext,
    CheckOutput,
    RegisteredCheck,
    all_checks,
    discover,
    register,
    select_checks,
)
from slopchecker.pipeline.runner import run_checks


def build_context(
    docs: Sequence[FlattenedDoc],
    *,
    solicitation: str | None = None,
) -> CheckContext:
    """Build a ``CheckContext`` for a batch run (#14).

    Populates ``batch`` with the docs and, when ``len(docs) >= 2``, builds a
    ``SimilarityIndex`` over them so corpus-level checks (near-dup, cluster)
    can query for peers. Single-doc batches leave ``similarity_index`` as
    ``None`` — the similarity check then emits a ``skipped`` ledger row with a
    clear reason rather than pretending to compare a doc against itself.

    The import is inside the function so ``pipeline`` stays usable without
    ``slopchecker[similarity]`` installed; only callers that actually build a
    context of size >= 2 pull in ``datasketch``.
    """
    similarity_index = None
    if len(docs) >= 2:
        from slopchecker.similarity.index import SimilarityIndex

        similarity_index = SimilarityIndex(list(docs))
    return CheckContext(
        solicitation=solicitation,
        batch=tuple(docs),
        similarity_index=similarity_index,
    )


__all__ = [
    "TIER_ORDER",
    "CheckContext",
    "CheckOutput",
    "RegisteredCheck",
    "all_checks",
    "build_context",
    "discover",
    "register",
    "run_checks",
    "select_checks",
]
