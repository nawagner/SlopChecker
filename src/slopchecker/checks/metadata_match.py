"""Check: does the cited metadata match the real source? (#9)

The subtle failure: the DOI resolves fine, but it points at a different paper
than the bibliography describes. Real identifier plus invented title is the
classic artifact, and resolution alone will never catch it.

Two things this check is careful about:

- **Sloppiness is not fabrication.** Abbreviated venues, initials, dropped
  subtitles, ±1 year — all graded *minor*, none of them flip the ledger row.
- **A missing record is our gap, not the applicant's defect.** Books and gray
  literature are largely absent from Crossref/OpenAlex/arXiv. Those report as
  "not covered by our metadata providers" and are excluded from the tally.

The reverse lookup is the payoff (#9): when an identifier has no record, we
search by title and author anyway. Finding the paper under a *different* DOI
means the citation is wrong, not invented — a distinction that matters enormously
to whoever reads this report.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import httpx

from slopchecker.checks.cache import cache_for
from slopchecker.checks.compare import Grade, MetadataMatch, compare, title_similarity
from slopchecker.checks.identifiers import Identifier, valid
from slopchecker.checks.net import http_client
from slopchecker.checks.providers import ProviderChain, SourceRecord
from slopchecker.checks.refs import (
    anchor_for,
    identifiers_for,
    no_references_row,
    nothing_to_check_row,
    references_for,
)
from slopchecker.models import CheckResult, Finding, FlattenedDoc, LedgerRow
from slopchecker.pipeline.citations import ReferenceEntry, first_surname
from slopchecker.pipeline.registry import CheckContext, CheckOutput, register

CHECK_ID = "metadata_match"
LABEL = "Citation metadata match"

# Identifiers a metadata provider can actually answer for.
_LOOKUP_KINDS = ("doi", "arxiv")
# A reverse-lookup hit below this isn't the same paper; saying "found it
# elsewhere" on a weak match would be worse than saying nothing.
_REVERSE_MIN_SIMILARITY = 0.80
_MAX_WORKERS = 4


@register(
    id=CHECK_ID,
    name=LABEL,
    tier="deterministic",
    needs_network=True,
    timeout_s=120.0,
)
def metadata_match(doc: FlattenedDoc, ctx: CheckContext) -> CheckOutput:
    """Compare each cited reference against the canonical record for its DOI."""
    if not references_for(doc):
        return CheckOutput(ledger=[no_references_row(CHECK_ID, LABEL, doc)])

    targets = [
        (ref, ident)
        for ref, idents in identifiers_for(doc)
        for ident in idents
        # Malformed identifiers belong to citation_identifiers_valid. Looking
        # one up here would report the same typo a second time, as a coverage
        # gap, which reads like two independent problems.
        if ident.kind in _LOOKUP_KINDS and valid(ident.kind, ident.value)
    ]
    if not targets:
        return CheckOutput(
            ledger=[nothing_to_check_row(CHECK_ID, LABEL, "DOIs or arXiv ids to look up")]
        )

    chain = ProviderChain(cache=cache_for(no_cache=ctx.no_cache, cache_dir=ctx.cache_dir))
    with http_client() as client:
        with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(targets))) as pool:
            outcomes = list(
                pool.map(lambda pair: _examine(client, chain, pair[0], pair[1]), targets)
            )

    return _build_output(doc, targets, outcomes)


def _examine(
    client: httpx.Client, chain: ProviderChain, ref: ReferenceEntry, ident: Identifier
) -> tuple[MetadataMatch, SourceRecord | None]:
    """Canonical record for one identifier, plus the reverse-lookup fallback.

    Returns the comparison and, when the identifier had no record, whatever
    the title search turned up (None if nothing did).
    """
    canonical = chain.lookup(client, ident)
    if canonical is not None:
        return compare(ref, canonical), None

    if not ref.title:
        return compare(ref, None), None
    candidate = chain.search(client, title=ref.title, surname=first_surname(ref), year=ref.year)
    if candidate is not None and title_similarity(ref.title, candidate.title) >= (
        _REVERSE_MIN_SIMILARITY
    ):
        return compare(ref, None), candidate
    return compare(ref, None), None


def _build_output(
    doc: FlattenedDoc,
    targets: list[tuple[ReferenceEntry, Identifier]],
    outcomes: list[tuple[MetadataMatch, SourceRecord | None]],
) -> CheckOutput:
    tally = {grade: 0 for grade in Grade}
    wrong_identifier = 0
    findings: list[Finding] = []
    for (ref, ident), (match, elsewhere) in zip(targets, outcomes, strict=True):
        tally[match.grade] += 1
        if match.grade is Grade.unknown and elsewhere is not None:
            wrong_identifier += 1
        if match.grade is Grade.matches:
            continue
        findings.append(_finding(doc, ref, ident, match, elsewhere, n=len(findings) + 1))

    compared = tally[Grade.matches] + tally[Grade.minor] + tally[Grade.different]
    not_covered = tally[Grade.unknown] - wrong_identifier

    if compared == 0 and wrong_identifier == 0:
        # Every identifier was outside provider coverage: our gap, reported
        # as one, rather than a vacuous pass over nothing.
        return CheckOutput(
            ledger=[
                LedgerRow(
                    check=CHECK_ID,
                    label=LABEL,
                    status="skipped",
                    reason=(
                        f"no canonical record for any of {len(targets)} identifier(s) — "
                        "outside our metadata providers' coverage"
                    ),
                )
            ],
            findings=findings,
        )

    return CheckOutput(
        ledger=[
            LedgerRow(
                check=CHECK_ID,
                label=LABEL,
                result=tally[Grade.different] == 0 and wrong_identifier == 0,
                detail=_detail(tally, compared, wrong_identifier, not_covered),
            )
        ],
        findings=findings,
    )


def _detail(tally: dict[Grade, int], compared: int, wrong_identifier: int, not_covered: int) -> str:
    parts = []
    if tally[Grade.minor]:
        parts.append(f"{tally[Grade.minor]} minor discrepancy")
    if tally[Grade.different]:
        parts.append(f"{tally[Grade.different]} different work")
    if wrong_identifier:
        parts.append(f"{wrong_identifier} identifier points elsewhere")
    if not_covered:
        parts.append(f"{not_covered} not covered")
    detail = f"{tally[Grade.matches]} / {compared} matched"
    return detail + (" — " + ", ".join(parts) if parts else "")


def _finding(
    doc: FlattenedDoc,
    ref: ReferenceEntry,
    ident: Identifier,
    match: MetadataMatch,
    elsewhere: SourceRecord | None,
    *,
    n: int,
) -> Finding:
    """One reference whose metadata didn't cleanly match its identifier."""
    evidence = {"kind": ident.kind, "as_written": ident.raw, **match.as_evidence()}
    note = match.summary()

    if match.grade is Grade.unknown:
        # No canonical record. Say which of the two "unknowns" this is.
        if elsewhere is not None:
            evidence["found_under"] = elsewhere.as_evidence()
            check = CheckResult(name=CHECK_ID, result=False)
            label = "Identifier points elsewhere than the cited work"
            under = f" (DOI {elsewhere.doi})" if elsewhere.doi else ""
            note = (
                f"No record for this {ident.kind.upper()}, but a work with this "
                f"title exists{under} — the identifier looks wrong."
            )
        else:
            check = CheckResult(
                name=CHECK_ID,
                status="skipped",
                reason="no canonical record from Crossref, OpenAlex, or arXiv",
            )
            # "Citation" up front: without it this read as a statement about
            # the *document's* metadata (it confused the first real reviewer).
            label = "Citation metadata could not be checked"
            note = (
                "This citation was not found in our metadata providers — expected "
                "for books and gray literature, and reported as a coverage gap."
            )
    elif match.grade is Grade.different:
        check = CheckResult(name=CHECK_ID, result=False)
        label = "Cited metadata describes a different work"
    else:
        check = CheckResult(name=CHECK_ID, result=True)
        label = "Minor metadata discrepancy"

    return Finding(
        id=f"MD{n}",
        target=ident.target,
        label=label,
        anchor=anchor_for(doc, ref),
        checks=[check],
        evidence=evidence,
        note=note,
    )
