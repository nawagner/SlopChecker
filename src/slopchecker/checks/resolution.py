"""The resolution engine shared by the DOI and URL checks (#8). Registers nothing.

One place decides what a resolution *means*, so "DOI 404" and "URL 404" can
never drift into different wordings, and one place enforces the rule that
matters most in this whole module:

    A dead link is evidence of a dead link.

So the ledger boolean is "no identifier positively failed to exist". Blocked
(paywall, bot wall, rate limit) and unreachable (timeout, DNS, 5xx) are
recorded as per-item coverage gaps, never as failures — we didn't learn the
source is missing, we learned we couldn't look. And a run where *nothing*
resolved because the network was down reports as ``errored``, which is #8's
second acceptance criterion and the difference between an honest tool and a
tool that calls a train ride "fabricated citations".
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import httpx

from slopchecker.checks.cache import Cache, cache_for
from slopchecker.checks.identifiers import Identifier, IdentifierKind, valid
from slopchecker.checks.net import DOI_RESOLVER, Outcome, Resolution, fetch_status, http_client
from slopchecker.checks.refs import (
    anchor_for,
    identifiers_for,
    no_references_row,
    nothing_to_check_row,
    references_for,
)
from slopchecker.models import CheckResult, Finding, FlattenedDoc, LedgerRow
from slopchecker.pipeline.citations import ReferenceEntry
from slopchecker.pipeline.registry import CheckContext, CheckOutput

# Politeness over speed: a handful of hosts, a handful of connections.
_MAX_WORKERS = 4

# The only two outcomes that tell us something about the *source*. Everything
# else tells us about our own reach, which is why blocked and unreachable are
# neither cached nor counted as evidence that anything was verified.
_CONCLUSIVE = (Outcome.resolves, Outcome.not_found)


def url_for(ident: Identifier) -> str:
    """The URL that answers "does this exist?" for an identifier."""
    if ident.kind == "doi":
        return DOI_RESOLVER + ident.value
    if ident.kind == "arxiv":
        return f"https://arxiv.org/abs/{ident.value}"
    return ident.value


def resolve_one(client: httpx.Client, cache: Cache, ident: Identifier) -> Resolution:
    """Resolve one identifier, through the cache (#8: don't re-hammer endpoints)."""
    key = f"{ident.kind}:{ident.value}"
    cached = cache.get("resolve", key)
    if isinstance(cached, dict):
        try:
            return Resolution(
                url=cached["url"],
                outcome=Outcome(cached["outcome"]),
                http_status=cached.get("http_status"),
                final_url=cached.get("final_url"),
            )
        except (KeyError, ValueError):
            pass  # cache written by an older shape: just re-resolve

    resolution = fetch_status(client, url_for(ident))
    # Only conclusive answers are cached. A blocked or unreachable result is
    # us failing to look, and persisting a non-answer for the 7-day TTL means
    # one transient 503 gets served as fact long after the source recovered —
    # the opposite of what a coverage gap is supposed to mean.
    if resolution.outcome in _CONCLUSIVE:
        cache.set(
            "resolve",
            key,
            {
                "url": resolution.url,
                "outcome": str(resolution.outcome),
                "http_status": resolution.http_status,
                "final_url": resolution.final_url,
            },
        )
    return resolution


def run_resolution_check(
    doc: FlattenedDoc,
    ctx: CheckContext,
    *,
    check_id: str,
    label: str,
    kind: IdentifierKind,
    noun: str,
    prefix: str,
) -> CheckOutput:
    """Resolve every well-formed identifier of ``kind`` and build the rows.

    Malformed identifiers are skipped deliberately: they belong to
    ``citation_identifiers_valid``, and resolving a typo would report the
    same defect twice under two different names.
    """
    if not references_for(doc):
        return CheckOutput(ledger=[no_references_row(check_id, label, doc)])

    targets = [
        (ref, ident)
        for ref, idents in identifiers_for(doc)
        for ident in idents
        if ident.kind == kind and valid(ident.kind, ident.value)
    ]
    if not targets:
        return CheckOutput(ledger=[nothing_to_check_row(check_id, label, f"well-formed {noun}s")])

    # One network call per *distinct* identifier. A foundational paper cited
    # in both the intro and the methods is two references sharing one DOI, and
    # resolving them in parallel raced past the cache — both threads missed,
    # both fetched, neither had written yet. Findings are still per-reference:
    # each anchors to its own quote at its own place in the document.
    cache = cache_for(no_cache=ctx.no_cache, cache_dir=ctx.cache_dir)
    unique: dict[tuple[str, str], Identifier] = {}
    for _, ident in targets:
        unique.setdefault((ident.kind, ident.value.lower()), ident)

    with http_client() as client:
        with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(unique))) as pool:
            answers = list(pool.map(lambda i: resolve_one(client, cache, i), unique.values()))
    resolved = dict(zip(unique, answers, strict=True))
    resolutions = [resolved[(ident.kind, ident.value.lower())] for _, ident in targets]

    return _build_output(
        doc,
        targets,
        resolutions,
        check_id=check_id,
        label=label,
        noun=noun,
        prefix=prefix,
    )


def _build_output(
    doc: FlattenedDoc,
    targets: list[tuple[ReferenceEntry, Identifier]],
    resolutions: list[Resolution],
    *,
    check_id: str,
    label: str,
    noun: str,
    prefix: str,
) -> CheckOutput:
    counts = {outcome: 0 for outcome in Outcome}
    findings: list[Finding] = []
    for (ref, ident), resolution in zip(targets, resolutions, strict=True):
        counts[resolution.outcome] += 1
        if resolution.ok:
            continue
        findings.append(
            _finding(
                doc,
                ref,
                ident,
                resolution,
                n=len(findings) + 1,
                check_id=check_id,
                prefix=prefix,
                noun=noun,
            )
        )

    conclusive = counts[Outcome.resolves] + counts[Outcome.not_found]
    if conclusive == 0:
        # Nothing was actually verified. Counting `blocked` as conclusive here
        # produced a vacuous pass: five paywalled DOIs became result=True,
        # "All DOIs resolve", next to a detail reading "0 / 5 resolved". A
        # bot wall is not evidence that a citation is sound.
        if counts[Outcome.unreachable]:
            status, reason = (
                "errored",
                f"no {noun}s could be reached — network failure, not a citation defect",
            )
        else:
            status, reason = (
                "skipped",
                f"all {len(targets)} {noun}(s) blocked or paywalled — none could be verified",
            )
        return CheckOutput(
            ledger=[LedgerRow(check=check_id, label=label, status=status, reason=reason)],
            findings=findings,
        )

    return CheckOutput(
        ledger=[
            LedgerRow(
                check=check_id,
                label=label,
                result=counts[Outcome.not_found] == 0,
                detail=_detail(counts, len(targets), noun),
            )
        ],
        findings=findings,
    )


def _detail(counts: dict[Outcome, int], total: int, noun: str) -> str:
    """The headline number (#8): "N of M do not resolve", said carefully."""
    detail = f"{counts[Outcome.resolves]} / {total} resolved"
    parts = []
    if counts[Outcome.not_found]:
        parts.append(f"{counts[Outcome.not_found]} not found")
    gaps = counts[Outcome.blocked] + counts[Outcome.unreachable]
    if gaps:
        parts.append(f"{gaps} could not be checked")
    return detail + (" — " + ", ".join(parts) if parts else "")


def _finding(
    doc: FlattenedDoc,
    ref: ReferenceEntry,
    ident: Identifier,
    resolution: Resolution,
    *,
    n: int,
    check_id: str,
    prefix: str,
    noun: str,
) -> Finding:
    """One non-resolving identifier, worded to match what we actually know."""
    if resolution.outcome is Outcome.not_found:
        check = CheckResult(name=check_id, result=False)
        heading = f"{noun} does not resolve"
        note = f"Resolver returned {resolution.http_status} — no record for this {noun}."
    else:
        # Blocked or unreachable: a gap, first-class. Not a failed check.
        reason = _gap_reason(resolution)
        check = CheckResult(name=check_id, status="skipped", reason=reason)
        heading = f"{noun} could not be checked"
        # Not .capitalize(): that would lowercase the rest, turning a status
        # line into "Unreachable (proxyerror: 502 bad gateway)".
        note = f"{noun} {reason} — this is a coverage gap, not a finding about the source."

    return Finding(
        id=f"{prefix}{n}",
        target=ident.target,
        label=heading,
        anchor=anchor_for(doc, ref),
        checks=[check],
        evidence={"kind": ident.kind, "as_written": ident.raw, **resolution.as_evidence()},
        note=note,
    )


def _gap_reason(resolution: Resolution) -> str:
    if resolution.outcome is Outcome.blocked:
        return f"{resolution.http_status} — reachable but blocked or paywalled"
    if resolution.http_status is not None:
        return f"{resolution.http_status} — server error, could not verify"
    return f"unreachable ({resolution.error or 'no response'})"


__all__ = ["resolve_one", "run_resolution_check", "url_for"]
