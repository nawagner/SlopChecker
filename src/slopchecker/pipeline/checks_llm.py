"""LLM-tier checks registered against the pipeline (#13).

The ``claims`` check binds ``lenses/claims.md`` to ``lens_runtime.run_lens``
and maps each *flagged* quote-anchored claim to a ``Finding`` following the
mapping table in ``lenses/claims.md``; unflagged claims stay out of the
report. Kept as its own module so the parallel
#11 (claim-support) session can build its check in a sibling file
without stepping on this one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from slopchecker import config as _config
from slopchecker.checks.cache import CONTENT_HASH_TTL_S, remote_cache
from slopchecker.lenses import load_lens
from slopchecker.models import Anchor, CheckResult, Finding, FlattenedDoc, LedgerRow
from slopchecker.pipeline.lens_runtime import LensRunConfig, run_lens
from slopchecker.pipeline.registry import CheckContext, CheckOutput, register

_LENS_ID = "claims"


def _lens_config(no_cache: bool = False) -> LensRunConfig:
    """Cache policy for the lens call. Two tiers, both opt-in.

    The shared KV cache (#119) wins when configured: it survives the ephemeral
    Railway filesystem and is shared across runs, so a repeat of the demo
    document costs nothing. Payloads are span-encoded on the way in, since lens
    quotes are verbatim document text — see ``lens_runtime._encode_payload``.

    Otherwise the on-disk cache, opt-in via ``SLOPCHECK_LENS_CACHE_DIR``. Off by
    default so the check has no filesystem side-effects on a fresh checkout.
    """
    if no_cache:
        return LensRunConfig()
    cache = remote_cache(ttl_s=CONTENT_HASH_TTL_S)
    if cache is not None:
        return LensRunConfig(cache=cache)
    cache_env = _config.get("SLOPCHECK_LENS_CACHE_DIR")
    cache_dir = Path(cache_env) / _LENS_ID if cache_env else None
    return LensRunConfig(cache_dir=cache_dir)


def _map_claim_to_finding(
    claim: dict[str, Any], provider: str, model: str | None
) -> Finding | None:
    """One *flagged* claim → one quote-anchored Finding, per lenses/claims.md.

    Unflagged claims return None and never reach the report. The first
    version emitted every claim with three descriptive booleans
    (quantitative? cited?), and since at least one of the three is False
    for every possible claim, the renderer painted all ten claims on the
    demo document as red failures — indistinguishable from fabricated
    DOIs. Attributes are not checks. A claim that raises no flag is
    silent, same policy as claim_support's ``supported`` verdict.
    """
    quantitative = bool(claim.get("quantitative", False))
    citation = claim.get("citation")
    if not quantitative or citation is not None:
        return None
    claim_type = claim.get("type", "unknown")
    return Finding(
        id=str(claim["id"]),
        target="claim",
        label="Unsourced quantitative claim",
        anchor=Anchor(page=claim.get("page"), quote=claim["quote"]),
        # False = the flag, so the renderer's failing lane reads correctly:
        # "quant_claim_sourced: NO".
        checks=[CheckResult(name="quant_claim_sourced", result=False)],
        evidence={
            "provider": provider,
            "model": model,
            "type": claim_type,
        },
    )


@register(
    id=_LENS_ID,
    name="Load-bearing claims extraction",
    tier="llm",
    est_cost_usd=0.05,
    needs_network=True,
    timeout_s=60.0,
)
def claims(doc: FlattenedDoc, ctx: CheckContext) -> CheckOutput:
    """Extract load-bearing claims via the ``claims`` lens.

    Runtime handles credentials, retries, JSON parsing, and mechanical
    quote-anchoring; this check just turns the parsed payload into
    quote-anchored Findings plus the document-level unsourced-quantitative
    summary count (the report-summary number named in #13's acceptance
    criteria).
    """
    lens = load_lens(_LENS_ID)
    result = run_lens(lens, doc, _lens_config(no_cache=ctx.no_cache))

    if result.status != "ok":
        return CheckOutput(
            ledger=[
                LedgerRow(
                    check=_LENS_ID,
                    label="Load-bearing claims extraction",
                    status=result.status,
                    reason=result.reason,
                )
            ]
        )

    claims = (result.payload or {}).get("claims", [])
    findings = [f for c in claims if (f := _map_claim_to_finding(c, result.provider, result.model))]
    return CheckOutput(
        findings=findings,
        ledger=[
            LedgerRow(
                check=_LENS_ID,
                label="Load-bearing claims extraction",
                result=True,
                detail=f"{len(claims)} claims extracted",
            ),
            LedgerRow(
                check="claims_quant_unsourced",
                label="Unsourced quantitative claims",
                result=len(findings),
                detail=f"{len(findings)} of {len(claims)} claims",
            ),
        ],
    )
