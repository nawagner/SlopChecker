"""LLM-tier checks registered against the pipeline (#13).

The ``claims`` check binds ``lenses/claims.md`` to ``lens_runtime.run_lens``
and maps each quote-anchored claim to a ``Finding`` following the mapping
table in ``lenses/claims.md``. Kept as its own module so the parallel
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


def _map_claim_to_finding(claim: dict[str, Any], provider: str, model: str | None) -> Finding:
    """One claim → one quote-anchored Finding, per lenses/claims.md."""
    quantitative = bool(claim.get("quantitative", False))
    citation = claim.get("citation")
    cited = citation is not None
    quant_unsourced = quantitative and not cited
    claim_type = claim.get("type", "unknown")
    return Finding(
        id=str(claim["id"]),
        target="claim",
        label=f"Claim ({claim_type})",
        anchor=Anchor(page=claim.get("page"), quote=claim["quote"]),
        checks=[
            CheckResult(name="claim_quantitative", result=quantitative),
            CheckResult(name="claim_cited", result=cited),
            CheckResult(name="quant_unsourced", result=quant_unsourced),
        ],
        evidence={
            "provider": provider,
            "model": model,
            "type": claim_type,
            "citation": citation,
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
    findings = [_map_claim_to_finding(c, result.provider, result.model) for c in claims]
    quant_unsourced = sum(1 for c in claims if c.get("quantitative") and c.get("citation") is None)
    return CheckOutput(
        findings=findings,
        ledger=[
            LedgerRow(
                check=_LENS_ID,
                label="Load-bearing claims extraction",
                result=True,
                detail=f"{len(findings)} claims extracted",
            ),
            LedgerRow(
                check="claims_quant_unsourced",
                label="Unsourced quantitative claims",
                result=quant_unsourced,
                detail=f"{quant_unsourced} of {len(findings)} claims",
            ),
        ],
    )
