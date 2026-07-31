"""Check registry (#5): decorator-based, no central list.

Adding a check is one new file plus one decorator:

    from slopchecker.pipeline import CheckContext, CheckOutput, register

    @register(id="doi_resolves", name="All DOIs resolve", tier="deterministic",
              needs_network=True)
    def doi_resolves(doc: FlattenedDoc, ctx: CheckContext) -> CheckOutput:
        ...
        return CheckOutput(ledger=[LedgerRow(check="doi_resolves", result=True)])

Metadata reuses ``models.Check`` (the registry-entry model from #3), so the
orchestrator can budget (``est_cost_usd``) and gate (``tier``,
``needs_network``) without importing check code. ``discover()`` imports every
module in the known check packages so registration happens as a side effect —
no central list to edit and conflict over.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from slopchecker.models import Check, Finding, FlattenedDoc, LedgerRow, Tier

DEFAULT_TIMEOUT_S = 30.0

# Packages scanned by discover(). pipeline/checks_builtin.py holds the trivial
# built-ins; slopchecker.checks is Nick's deterministic-tier package (#8 etc.)
# and is picked up automatically once it exists; pipeline/checks_llm.py + the
# pipeline/claim_support package are #11's LLM check (tier="llm");
# pipeline/checks_similarity.py is the batch-aware near-dup check (#14) — kept
# in pipeline/ because it wraps the Dan-owned similarity/ engine.
CHECK_PACKAGES: tuple[str, ...] = (
    "slopchecker.pipeline.checks_builtin",
    "slopchecker.pipeline.checks_citations",
    "slopchecker.pipeline.checks_detect",
    "slopchecker.pipeline.checks_rubric",
    "slopchecker.pipeline.checks_llm",
    "slopchecker.pipeline.checks_similarity",
    "slopchecker.pipeline.checks_topics",
    "slopchecker.pipeline.claim_support",
    "slopchecker.checks",
)

TIER_ORDER: tuple[Tier, ...] = ("deterministic", "api", "llm")


@dataclass
class CheckContext:
    """What the runner hands every check besides the document itself.

    ``batch`` / ``similarity_index`` (#14) let corpus-level checks (near-dup,
    template-cluster) see peers in the same run. Both are empty/None by default
    so single-doc callers and existing tests keep working unchanged. Use
    ``pipeline.build_context(docs, ...)`` to populate them.
    """

    solicitation: str | None = None
    # Rubric (#90): the funder reference doc (solicitation/RFP, criteria)
    # this submission is checked against, pre-ingested by the caller.
    # None = not supplied; rubric-dependent checks must emit a skipped
    # gap row, never crash.
    rubric: FlattenedDoc | None = None
    workdir: Path | None = None
    # Run-level cache policy for checks that hit the network (#8). Additive
    # and optional: a check that doesn't cache ignores both fields.
    no_cache: bool = False
    cache_dir: Path | None = None
    batch: Sequence[FlattenedDoc] = ()
    # `Any` avoids importing SimilarityIndex here (would pull `datasketch` in as
    # a hard dependency of every session that instantiates a CheckContext).
    # The concrete type is `slopchecker.similarity.index.SimilarityIndex | None`.
    similarity_index: Any = None


@dataclass
class CheckOutput:
    """What a check returns: ledger rows and/or findings, plus actual spend.

    A check with a document-level outcome emits a ``LedgerRow``; quote-anchored
    evidence goes in ``findings``. ``cost_usd`` is what the run actually spent
    (API checks), summed into ``RunInfo.cost_usd``.
    """

    ledger: list[LedgerRow] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    cost_usd: float = 0.0


CheckFn = Callable[[FlattenedDoc, CheckContext], CheckOutput]
AppliesTo = Callable[[FlattenedDoc], bool]


@dataclass(frozen=True)
class RegisteredCheck:
    """A registry entry: the metadata model plus the callable and run policy."""

    meta: Check
    fn: CheckFn
    timeout_s: float = DEFAULT_TIMEOUT_S
    applies_to: AppliesTo | None = None


_REGISTRY: dict[str, RegisteredCheck] = {}


def register(
    *,
    id: str,
    name: str,
    tier: Tier,
    est_cost_usd: float = 0.0,
    needs_network: bool = False,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    applies_to: AppliesTo | None = None,
) -> Callable[[CheckFn], CheckFn]:
    """Register a check function under a stable id.

    ``id`` must match the ``LedgerRow.check`` / ``CheckResult.name`` the check
    emits, so report rows trace back to registry entries.
    """
    meta = Check(
        id=id, name=name, tier=tier, est_cost_usd=est_cost_usd, needs_network=needs_network
    )

    def decorate(fn: CheckFn) -> CheckFn:
        if id in _REGISTRY:
            raise ValueError(f"check id '{id}' already registered ({_REGISTRY[id].fn!r})")
        _REGISTRY[id] = RegisteredCheck(
            meta=meta, fn=fn, timeout_s=timeout_s, applies_to=applies_to
        )
        return fn

    return decorate


def discover() -> None:
    """Import every module in CHECK_PACKAGES so their decorators run.

    A package that doesn't exist yet (e.g. ``slopchecker.checks`` before #8
    lands) is fine; a check module whose *own* import fails is not — that
    error surfaces loudly instead of the check silently vanishing.
    """
    for pkg_name in CHECK_PACKAGES:
        try:
            module = importlib.import_module(pkg_name)
        except ModuleNotFoundError as exc:
            if exc.name == pkg_name:
                continue
            raise
        if hasattr(module, "__path__"):  # a package: import each submodule
            for info in pkgutil.iter_modules(module.__path__, prefix=f"{pkg_name}."):
                importlib.import_module(info.name)


def all_checks() -> list[RegisteredCheck]:
    """Every registered check, tier-ordered then id-ordered (deterministic)."""
    return sorted(_REGISTRY.values(), key=lambda rc: (TIER_ORDER.index(rc.meta.tier), rc.meta.id))


def select_checks(
    checks: Iterable[RegisteredCheck],
    *,
    tier: str = "all",
    only: Iterable[str] = (),
    skip: Iterable[str] = (),
) -> list[RegisteredCheck]:
    """Apply --tier / --only / --skip. Unknown ids in only/skip raise
    ValueError — a typo'd check id is a tool failure, not an empty run."""
    checks = list(checks)
    known = {rc.meta.id for rc in checks}
    only_set, skip_set = set(only), set(skip)
    if tier != "all" and tier not in TIER_ORDER:
        raise ValueError(f"unknown tier '{tier}' (expected deterministic|api|llm|all)")
    for label, wanted in (("--only", only_set), ("--skip", skip_set)):
        unknown = wanted - known
        if unknown:
            raise ValueError(f"{label}: unknown check id(s): {', '.join(sorted(unknown))}")

    selected = [rc for rc in checks if tier == "all" or rc.meta.tier == tier]
    if only_set:
        selected = [rc for rc in selected if rc.meta.id in only_set]
    return [rc for rc in selected if rc.meta.id not in skip_set]
