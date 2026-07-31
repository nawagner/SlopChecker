"""Check: do the plain URLs in the reference list resolve? (#8)

Separate from the DOI check on purpose. Gray literature — think tank reports,
government pages, NGO PDFs — is cited by URL, and link rot there is ordinary
and constant. Mixing dead URLs into the DOI number would inflate the headline
figure with something much less damning than a DOI that was never registered.
"""

from __future__ import annotations

from slopchecker.checks.resolution import run_resolution_check
from slopchecker.models import FlattenedDoc
from slopchecker.pipeline.registry import CheckContext, CheckOutput, register

CHECK_ID = "all_urls_resolve"
LABEL = "All reference URLs resolve"


@register(
    id=CHECK_ID,
    name=LABEL,
    tier="deterministic",
    needs_network=True,
    timeout_s=120.0,
)
def all_urls_resolve(doc: FlattenedDoc, ctx: CheckContext) -> CheckOutput:
    """Resolve every well-formed non-DOI URL cited in the reference list."""
    return run_resolution_check(
        doc, ctx, check_id=CHECK_ID, label=LABEL, kind="url", noun="URL", prefix="URL"
    )
