"""Budget-feasibility LLM check (#17) — orchestrator + registration.

Wires the ``budget_feasibility`` lens (extraction + pairing) to the
Python evaluator that applies US benchmarks:

1. Load ``lenses/budget_feasibility.md`` and assemble the system + user
   prompt with the lens's one-shot example.
2. Call the LLM through ``Transport.complete_json`` under the
   ``LENS_OUTPUT_SCHEMA`` — Anthropic validates the shape server-side.
3. Parse the payload into ``LensOutput`` dataclasses. A malformed shape
   is a coverage gap, never an uncaught exception.
4. Run quotecheck against ``doc.text``: any personnel line, non-
   personnel line, or scope commitment whose ``quote`` isn't
   verbatim-in-doc is dropped, along with any pairings that reference
   the dropped id. Nothing hallucinated ever reaches the evaluator.
5. Call ``evaluate_lens_output`` on the verified lens output. The
   evaluator emits ``Finding`` records with the benchmark assumption
   printed in ``evidence`` (so reviewers can override without re-running).

Registered under ``tier="llm"`` and off by default — the runner only
runs it when ``--tier`` selects it.

All LLM plumbing (transport, retries, prompt assembly) is private to
this subpackage per the #37 design comment; the shared ``LadderExecutor``
is a follow-up once #11 and #17 land.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from slopchecker import config as _config
from slopchecker.lenses import load_lens
from slopchecker.models import CheckStatus, FlattenedDoc, LedgerRow
from slopchecker.pipeline.budget_feasibility.benchmarks_us import US_2026
from slopchecker.pipeline.budget_feasibility.evaluate import (
    DEFAULT_SHORTFALL_THRESHOLD,
    LensOutput,
    NonPersonnelLine,
    Pairing,
    PersonnelLine,
    ProjectInfo,
    RoleAllocation,
    ScopeCommitment,
    evaluate_lens_output,
)
from slopchecker.pipeline.budget_feasibility.llm import (
    AnthropicTransport,
    Transport,
    TransportAuthError,
    TransportClientError,
    TransportError,
    TransportRateLimit,
    TransportRefusal,
    TransportServerError,
)
from slopchecker.pipeline.budget_feasibility.prompts import (
    LENS_OUTPUT_SCHEMA,
    build_budget_feasibility_prompt,
)
from slopchecker.pipeline.quotes import QuoteStatus, match_quote
from slopchecker.pipeline.registry import CheckContext, CheckOutput, register

CHECK_ID = "budget_feasibility"
LENS_NAME = "budget_feasibility"
_CHECK_LABEL = "Budget feasibility (LLM lens + US benchmarks)"


@dataclass(frozen=True)
class BudgetFeasibilityConfig:
    """Knobs for the budget-feasibility check.

    Defaults are conservative: one low-effort structured-output call per
    document; the standard three-attempt retry policy shared with
    ``claim_support`` and ``detect/pangram``.
    """

    model: str = "claude-opus-5"
    # Retry policy for 429/5xx (mirrors detect/pangram.py + claim_support).
    max_attempts: int = 3
    initial_backoff_seconds: float = 0.5
    # Threshold pass-through so callers can dial the false-positive rate
    # without editing the evaluator.
    shortfall_flag_threshold: float = DEFAULT_SHORTFALL_THRESHOLD


class BudgetFeasibilityCheck:
    """Public entry point.

    Instances are built by the registered wrapper below (which supplies
    the real ``AnthropicTransport``), or directly by tests with a
    scripted ``FakeTransport``.
    """

    name = CHECK_ID

    def __init__(
        self,
        *,
        config: BudgetFeasibilityConfig,
        transport: Transport | None = None,
    ) -> None:
        self._conf = config
        self._transport = transport  # lazily built when a real call is needed

    # ---- Public entry point ---------------------------------------------

    def run(self, doc: FlattenedDoc, ctx: CheckContext) -> CheckOutput:
        # Credentials: skipped ledger row on missing key, matching pangram's
        # degrade-to-gap contract.
        try:
            api_key = _config.require("ANTHROPIC_API_KEY")
        except _config.MissingCredential as exc:
            return CheckOutput(ledger=[_gap_row("skipped", f"missing {exc.env_var}")])

        lens = load_lens(LENS_NAME)
        system, user = build_budget_feasibility_prompt(lens=lens, doc_text=doc.text)
        transport = self._get_transport(api_key)

        # Stage 1: LLM extraction.
        try:
            payload = self._call_with_retry(
                transport,
                system=system,
                user=user,
                schema=LENS_OUTPUT_SCHEMA,
                model=self._conf.model,
                role="lens",
            )
        except TransportRefusal as exc:
            return CheckOutput(ledger=[_gap_row("errored", f"llm refusal: {exc}")])
        except TransportError as exc:
            return CheckOutput(ledger=[_gap_row("errored", f"llm transport error: {exc}")])

        # Stage 2: parse into the evaluator's dataclasses. Malformed shape
        # = coverage gap, never a stack trace (CLAUDE.md: degrade to gaps).
        try:
            raw_lens_out = _parse_lens_output(payload)
        except (KeyError, ValueError, TypeError) as exc:
            return CheckOutput(ledger=[_gap_row("errored", f"lens payload malformed: {exc}")])

        # Stage 3: quotecheck — drop items whose quote isn't in doc.text.
        verified_lens_out, dropped_ids = _quotecheck_lens_output(raw_lens_out, doc.text)

        # Stage 4: run the evaluator.
        findings = evaluate_lens_output(
            verified_lens_out,
            benchmarks=US_2026,
            shortfall_flag_threshold=self._conf.shortfall_flag_threshold,
        )

        # Ledger: single ok row with the finding count as the numeric
        # result. Detail surfaces any drops so the reader sees the gap
        # without a second row shape.
        detail_bits = [f"{len(findings)} finding(s)"]
        if dropped_ids:
            detail_bits.append(
                f"{len(dropped_ids)} extracted item(s) dropped: quote not verbatim in document"
            )
        detail = "; ".join(detail_bits) or None
        return CheckOutput(
            findings=findings,
            ledger=[_ok_row(result=len(findings), detail=detail)],
        )

    # ---- Retry loop -----------------------------------------------------

    def _call_with_retry(
        self,
        transport: Transport,
        *,
        system: str,
        user: str,
        schema: dict,
        model: str,
        role: str,
    ) -> dict[str, Any]:
        """Retry 429/5xx with exponential backoff; surface auth/client immediately.

        Kept private and inline per the #37 design comment — the shared
        Ladder is a follow-up refactor once #11 and #17 land. Same shape
        as ``claim_support/check.py`` and ``detect/pangram.py``.
        """
        last_transient: TransportError | None = None
        for attempt in range(self._conf.max_attempts):
            try:
                return transport.complete_json(
                    system=system, user=user, schema=schema, model=model, role=role
                )
            except (TransportRateLimit, TransportServerError) as exc:
                last_transient = exc
                if attempt < self._conf.max_attempts - 1:
                    time.sleep(self._conf.initial_backoff_seconds * (2**attempt))
            except (TransportAuthError, TransportClientError, TransportRefusal):
                raise  # permanent — surface immediately
        assert last_transient is not None
        raise last_transient

    def _get_transport(self, api_key: str) -> Transport:
        if self._transport is None:
            self._transport = AnthropicTransport(api_key=api_key)
        return self._transport


# --- Payload parsing -------------------------------------------------------


def _parse_lens_output(payload: dict[str, Any]) -> LensOutput:
    """Convert LLM-validated JSON payload into evaluator dataclasses.

    Every field access is unconditional: a missing key is a bug in the
    schema-validated response and gets surfaced as an errored ledger row
    by the caller. Optional-null fields use ``.get()`` so an explicit
    ``null`` in the payload passes through unchanged.
    """
    project_p = payload["project"]
    project = ProjectInfo(
        stated_total_usd=project_p.get("stated_total_usd"),
        duration_yrs=project_p.get("duration_yrs"),
    )
    personnel_lines = [
        PersonnelLine(
            id=str(pl["id"]),
            page=int(pl["page"]),
            quote=str(pl["quote"]),
            amount_usd=float(pl["amount_usd"]),
            period_yrs=pl.get("period_yrs"),
            fringe_rate=pl.get("fringe_rate"),
            indirect_rate=pl.get("indirect_rate"),
            roles_named=[
                RoleAllocation(
                    role=str(r["role"]),
                    count=int(r["count"]),
                    fte_fraction=float(r["fte_fraction"]),
                )
                for r in pl.get("roles_named", [])
            ],
        )
        for pl in payload.get("personnel_lines", [])
    ]
    non_personnel_lines = [
        NonPersonnelLine(
            id=str(nl["id"]),
            page=int(nl["page"]),
            quote=str(nl["quote"]),
            amount_usd=float(nl["amount_usd"]),
            category=str(nl["category"]),
        )
        for nl in payload.get("non_personnel_lines", [])
    ]
    scope_commitments = [
        ScopeCommitment(
            id=str(sc["id"]),
            page=int(sc["page"]),
            quote=str(sc["quote"]),
            quantity=float(sc["quantity"]),
            unit=str(sc["unit"]),
            timeframe_yrs=sc.get("timeframe_yrs"),
        )
        for sc in payload.get("scope_commitments", [])
    ]
    pairings = [
        Pairing(scope_id=str(p["scope_id"]), budget_id=str(p["budget_id"]))
        for p in payload.get("pairings", [])
    ]
    _validate_roles(personnel_lines)
    _validate_categories(non_personnel_lines)
    return LensOutput(
        project=project,
        personnel_lines=personnel_lines,
        non_personnel_lines=non_personnel_lines,
        scope_commitments=scope_commitments,
        pairings=pairings,
    )


# Duplicated from prompts.LENS_OUTPUT_SCHEMA for the client-side belt.
# ``output_config.format`` enforces these server-side, but a schema-slip
# through a fake or a misconfigured provider must land as a ledger gap,
# not a stack trace deep in the evaluator (CLAUDE.md degrade-to-gaps rule).
_VALID_ROLES = frozenset(
    {
        "pi",
        "co_pi",
        "senior_scientist",
        "postdoc",
        "grad_student",
        "research_assistant",
        "admin",
        "technician",
        "consultant",
        "other",
    }
)
_VALID_CATEGORIES = frozenset(
    {"equipment", "travel", "supplies", "indirect", "subcontract", "other"}
)


def _validate_roles(personnel_lines: list[PersonnelLine]) -> None:
    for pl in personnel_lines:
        for r in pl.roles_named:
            if r.role not in _VALID_ROLES:
                raise ValueError(f"personnel line {pl.id!r} has out-of-enum role {r.role!r}")


def _validate_categories(non_personnel_lines: list[NonPersonnelLine]) -> None:
    for nl in non_personnel_lines:
        if nl.category not in _VALID_CATEGORIES:
            raise ValueError(
                f"non-personnel line {nl.id!r} has out-of-enum category {nl.category!r}"
            )


# --- Quote check -----------------------------------------------------------


def _quote_present(quote: str, doc_text: str) -> bool:
    """True when ``quote`` matches somewhere in ``doc_text``.

    Uses ``match_quote`` for the same reason ``claim_support`` does:
    verbatim-or-minor-variation matching (normalized whitespace and
    unicode punctuation) tolerates the small jitter PDF text extraction
    introduces without weakening the invariant that the passage exists.
    A ``not_found`` here means the model invented text — drop it.
    """
    match = match_quote(quote, doc_text)
    return match.status in (QuoteStatus.found_verbatim, QuoteStatus.found_minor_variation)


def _quotecheck_lens_output(lens_out: LensOutput, doc_text: str) -> tuple[LensOutput, set[str]]:
    """Filter items whose quote isn't present in ``doc_text``.

    Returns ``(verified_lens_out, dropped_ids)``. Pairings referencing a
    dropped id are also removed — a scope-to-budget link where either
    end has no anchor in the document is unsafe to evaluate.
    """
    dropped: set[str] = set()

    def keep(item_id: str, quote: str) -> bool:
        if _quote_present(quote, doc_text):
            return True
        dropped.add(item_id)
        return False

    kept_pl = [pl for pl in lens_out.personnel_lines if keep(pl.id, pl.quote)]
    kept_nl = [nl for nl in lens_out.non_personnel_lines if keep(nl.id, nl.quote)]
    kept_sc = [sc for sc in lens_out.scope_commitments if keep(sc.id, sc.quote)]
    kept_pairs = [
        p for p in lens_out.pairings if p.budget_id not in dropped and p.scope_id not in dropped
    ]
    return (
        LensOutput(
            project=lens_out.project,
            personnel_lines=kept_pl,
            non_personnel_lines=kept_nl,
            scope_commitments=kept_sc,
            pairings=kept_pairs,
        ),
        dropped,
    )


# --- Ledger helpers --------------------------------------------------------


def _ok_row(*, result: int, detail: str | None) -> LedgerRow:
    return LedgerRow(
        check=CHECK_ID,
        label=_CHECK_LABEL,
        result=result,
        detail=detail,
        status="ok",
    )


def _gap_row(status: CheckStatus, reason: str) -> LedgerRow:
    return LedgerRow(
        check=CHECK_ID,
        label=_CHECK_LABEL,
        status=status,
        reason=reason,
    )


# --- Registration ---------------------------------------------------------


@register(
    id=CHECK_ID,
    name=_CHECK_LABEL,
    tier="llm",
    est_cost_usd=0.03,  # rough per-doc ceiling — one structured-output call.
    needs_network=True,
    timeout_s=180.0,
)
def _run_budget_feasibility(doc: FlattenedDoc, ctx: CheckContext) -> CheckOutput:
    """Registered wrapper — the runner-facing seam.

    Stateless per call: builds a fresh check + transport each time. Real
    LLM transport plugs in behind the ``Transport`` protocol; tests
    inject a scripted fake.
    """
    check = BudgetFeasibilityCheck(config=BudgetFeasibilityConfig())
    return check.run(doc, ctx)
