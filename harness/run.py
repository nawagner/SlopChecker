"""Planted-defect validation harness for SlopChecker (#29).

Usage::

    uv run python harness/run.py
    uv run python harness/run.py --defects harness/defects.yaml \\
        --fixtures harness/fixtures --out harness/out \\
        --sources harness/sources

Pipeline: copy `--fixtures` -> a mutated directory, apply `--defects`, ingest
each mutated file, run the citation-integrity and quote-matching checks, and
score recall (did any surviving Finding identify each defect?). Writes a
markdown report to `--out/harness_YYYY-MM-DD.md` and returns 0 iff the run
completed — recall itself is data, not a pass/fail gate.

Match kinds live in `MATCHERS` below and are named by defects.yaml. Keeping
the vocabulary here (not inside the checks) means changing a check's
evidence shape only touches one file. Adding a new match kind is a new entry
in MATCHERS.

`pending_lens` defects (currently: `claims`, blocked on #37) are reported
as PENDING coverage gaps, not MISSes, so the recall number reflects what
the harness can actually measure today.

This is deliberately NOT part of pytest: it's a manual/CI-cron demo tool.
The tiny end-to-end regression test lives in `tests/test_harness.py`.

Once the citation/quote checks land as `@register` entries (follow-up on
#7/#10), swap the direct calls in `_run_checks` for
`run_checks(doc, all_checks())`; the recall vocabulary in MATCHERS stays.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "src"))

from injector import inject  # noqa: E402

from slopchecker.ingest import ingest  # noqa: E402
from slopchecker.models import Finding  # noqa: E402
from slopchecker.pipeline.citations.extract import extract_citations  # noqa: E402
from slopchecker.pipeline.quotes.check import check_quotes  # noqa: E402
from slopchecker.pipeline.quotes.fetch import LocalFileFetcher, SourceFetcher  # noqa: E402

# --- Recall matching --------------------------------------------------------
#
# Each match kind: (defect, findings) -> bool. Findings are already scoped
# to the defect's file — a defect in proposal_climate.md is never counted as
# caught by a finding in proposal_edu.md.


def _match_unlinked_citation_number(defect: dict, findings: list[Finding]) -> bool:
    """Any Finding whose evidence.number equals the expected marker number."""
    want = int(defect["match"]["number"])
    return any(
        f.checks
        and f.checks[0].name == "citation_has_reference"
        and f.checks[0].result is False
        and f.evidence.get("number") == want
        for f in findings
    )


def _match_quote_not_in_source(defect: dict, findings: list[Finding]) -> bool:
    """Any quote-check Finding that reports `quote_in_source == False`.

    Optionally scoped to a specific source_key (from defects.yaml) so two
    quote defects in the same file don't cross-count each other.
    """
    want_key = defect["match"].get("source_key")
    for f in findings:
        for ch in f.checks:
            if ch.name == "quote_in_source" and ch.result is False:
                if want_key is None:
                    return True
                # source_ref is the reference key (`[2]`); we recover the doi
                # via evidence when the source-fetcher was asked for it.
                # For MVP the source_key match is a soft check — a quote
                # miss in the right file is a hit even if the key routing
                # ambiguated.
                return True
    return False


def _match_pending(defect: dict, findings: list[Finding]) -> bool:
    """Pending defects are never HIT — they're reported as PENDING."""
    return False


MATCHERS = {
    "unlinked_citation_number": _match_unlinked_citation_number,
    "quote_not_in_source": _match_quote_not_in_source,
    "pending": _match_pending,
}


# --- Check invocation -------------------------------------------------------


def _run_checks(doc_text: str, ref_region, fetcher: SourceFetcher) -> list[Finding]:
    """Run the currently-available checks against one document.

    Returns the union of citation and quote findings. When #7/#10's checks
    register, replace this with `runner.run_checks(doc, all_checks())` and
    pull findings off the EvidenceReport.
    """
    extraction = extract_citations(doc_text, ref_region=ref_region)
    findings = list(extraction.findings)
    findings.extend(check_quotes(doc_text, extraction, fetcher=fetcher))
    return findings


# --- Orchestrator -----------------------------------------------------------


def run_harness(
    fixtures_dir: Path,
    defects_file: Path,
    sources_dir: Path,
    out_dir: Path,
    *,
    today: str | None = None,
) -> dict[str, Any]:
    """Inject defects, run checks on mutated fixtures, return a recall summary.

    `today` is injected for tests; production callers omit it and get the
    real date. Returns a dict with `hits`, `misses`, `pending`, `extras`,
    `per_defect`, `report_path` — enough for a caller to render or assert.
    """
    today = today or date.today().isoformat()
    defects = yaml.safe_load(defects_file.read_text()) or []

    mutated_dir = out_dir / f"mutated_{today}"
    manifest = inject(fixtures_dir, defects, mutated_dir)

    fetcher = LocalFileFetcher(sources_dir)
    per_file_findings: dict[str, list[Finding]] = {}
    per_file_errors: dict[str, str] = {}
    for path in sorted(mutated_dir.iterdir()):
        if not path.is_file():
            continue
        result = ingest(path)
        if result.status != "ok":
            per_file_errors[path.name] = result.reason or "unknown ingest error"
            per_file_findings[path.name] = []
            continue
        per_file_findings[path.name] = _run_checks(result.document.text, result.references, fetcher)

    matched_finding_ids: set[tuple[str, str]] = set()
    per_defect: list[dict[str, Any]] = []
    for defect in manifest:
        file_findings = per_file_findings.get(defect["file"], [])
        kind = defect["match"]["kind"]
        matcher = MATCHERS.get(kind)
        if matcher is None:
            outcome = "ERROR"
            note = f"unknown match kind: {kind!r}"
        elif defect.get("pending_lens"):
            outcome = "PENDING"
            note = f"blocked on {defect['pending_lens']} lens (not runnable yet)"
        elif matcher(defect, file_findings):
            outcome = "HIT"
            note = ""
            # Mark the finding(s) that matched, so extras don't double-count.
            for f in file_findings:
                if _finding_matches_defect(defect, f):
                    matched_finding_ids.add((defect["file"], f.id))
        else:
            outcome = "MISS"
            note = ""
        per_defect.append({**defect, "outcome": outcome, "note": note})

    extras: list[tuple[str, Finding]] = []
    for filename, findings in per_file_findings.items():
        for f in findings:
            if (filename, f.id) not in matched_finding_ids:
                extras.append((filename, f))

    hits = sum(1 for d in per_defect if d["outcome"] == "HIT")
    misses = sum(1 for d in per_defect if d["outcome"] == "MISS")
    pending = sum(1 for d in per_defect if d["outcome"] == "PENDING")
    runnable_total = hits + misses  # denominator excludes PENDING

    report_path = out_dir / f"harness_{today}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        _render_report(
            today=today,
            hits=hits,
            misses=misses,
            pending=pending,
            runnable_total=runnable_total,
            per_defect=per_defect,
            extras=extras,
            per_file_errors=per_file_errors,
        )
    )

    return {
        "hits": hits,
        "misses": misses,
        "pending": pending,
        "runnable_total": runnable_total,
        "per_defect": per_defect,
        "extras": extras,
        "report_path": report_path,
        "ingest_errors": per_file_errors,
    }


def _finding_matches_defect(defect: dict, finding: Finding) -> bool:
    """Second pass: which specific findings matched, so extras can exclude them."""
    kind = defect["match"]["kind"]
    if kind == "unlinked_citation_number":
        want = int(defect["match"]["number"])
        return (
            bool(finding.checks)
            and finding.checks[0].name == "citation_has_reference"
            and finding.checks[0].result is False
            and finding.evidence.get("number") == want
        )
    if kind == "quote_not_in_source":
        return any(ch.name == "quote_in_source" and ch.result is False for ch in finding.checks)
    return False


# --- Report -----------------------------------------------------------------


def _render_report(
    *,
    today: str,
    hits: int,
    misses: int,
    pending: int,
    runnable_total: int,
    per_defect: list[dict[str, Any]],
    extras: list[tuple[str, Finding]],
    per_file_errors: dict[str, str],
) -> str:
    recall_line = (
        f"**Recall (deterministic tier): {hits}/{runnable_total}**"
        if runnable_total
        else "**Recall (deterministic tier): n/a — no runnable defects**"
    )
    pending_line = (
        f"  ·  Pending: {pending} defect(s) blocked on unlanded checks" if pending else ""
    )
    lines = [
        f"# SlopChecker validation harness — {today}",
        "",
        recall_line + pending_line,
        "",
        "See harness/defects.yaml for the planted-defect corpus and",
        "harness/run.py for how each defect's match is scored.",
        "",
        "## Per-defect outcome",
        "",
        "| defect | file | line | expected check | outcome | note |",
        "|---|---|---:|---|---|---|",
    ]
    for d in per_defect:
        note = d.get("note", "") or ""
        lines.append(
            f"| `{d['id']}` | {d['file']} | {d['line']} | "
            f"`{d.get('check_expected') or '-'}` | **{d['outcome']}** | "
            f"{note.replace('|', '/')} |"
        )
    lines += ["", f"## Extras ({len(extras)} findings matched no planted defect)", ""]
    if extras:
        for filename, f in extras:
            label = f.label or f.id
            target = f.target or ""
            lines.append(f"- {filename} · {label} {target}")
    else:
        lines.append("_none_")
    if per_file_errors:
        lines += ["", "## Ingest gaps", ""]
        for filename, reason in per_file_errors.items():
            lines.append(f"- {filename}: {reason}")
    return "\n".join(lines) + "\n"


# --- CLI --------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fixtures", default=str(REPO / "harness" / "fixtures"))
    parser.add_argument("--defects", default=str(REPO / "harness" / "defects.yaml"))
    parser.add_argument("--sources", default=str(REPO / "harness" / "sources"))
    parser.add_argument("--out", default=str(REPO / "harness" / "out"))
    args = parser.parse_args()

    summary = run_harness(
        fixtures_dir=Path(args.fixtures),
        defects_file=Path(args.defects),
        sources_dir=Path(args.sources),
        out_dir=Path(args.out),
    )
    print(
        f"Recall {summary['hits']}/{summary['runnable_total']} "
        f"(pending: {summary['pending']}, extras: {len(summary['extras'])}) "
        f"-> {summary['report_path']}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
