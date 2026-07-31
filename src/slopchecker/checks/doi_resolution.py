"""Check: do the cited DOIs resolve? (#8 — the flagship deterministic check)

"N of M DOIs do not resolve" is the headline number in the evidence report,
and it is not a judgment call: doi.org either has a record or it doesn't.
Resolution goes through doi.org rather than the Crossref API so DataCite,
mEDRA, and the other registries count too — a DataCite DOI is a real DOI.
"""

from __future__ import annotations

from slopchecker.checks.resolution import run_resolution_check
from slopchecker.models import FlattenedDoc
from slopchecker.pipeline.registry import CheckContext, CheckOutput, register

CHECK_ID = "all_dois_resolve"
LABEL = "All DOIs resolve"


@register(
    id=CHECK_ID,
    name=LABEL,
    tier="deterministic",
    needs_network=True,
    # Generous: a reference list of 40 DOIs, four at a time, with a retry on
    # the slow ones. The runner records a timeout as a gap, so overshooting
    # here costs nothing and undershooting loses real evidence.
    timeout_s=120.0,
)
def all_dois_resolve(doc: FlattenedDoc, ctx: CheckContext) -> CheckOutput:
    """Resolve every well-formed DOI in the reference list through doi.org."""
    return run_resolution_check(
        doc, ctx, check_id=CHECK_ID, label=LABEL, kind="doi", noun="DOI", prefix="DOI"
    )
