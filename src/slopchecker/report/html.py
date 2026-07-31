"""Render a report.json into the self-contained HTML evidence report (#19).

Pure function of the report dict: no checks are re-run, no network, no LLM.
The page is the mock (mockups/evidence-report-mock.html) generated from data.
Check results are strictly bool | number; all human-readable framing lives
here in the renderer, per the #3 strawman.
"""

from __future__ import annotations

import json
import re
from html import escape
from importlib import resources
from pathlib import Path

SCHEMA_VERSION = "0.1"

# Human labels for known check names. Fallback: underscores to spaces.
CHECK_LABELS = {
    "doi_resolves": ("DOI resolves", "resolves"),
    "metadata_match": ("Metadata match", "metadata"),
    "openalex_found": ("Found in OpenAlex", "OpenAlex"),
    "quote_in_source": ("Quote found in source", "quote found"),
    "number_in_source": ("Number found in source", "number found"),
    "pangram_span": ("Span score", "span"),
    "pangram_document": ("Document score", "doc"),
}

_LANE_RANK = {"no": 0, "score": 1, "yes": 2}  # strongest wins on overlap


def _check_label(name: str, short: bool = False) -> str:
    if name in CHECK_LABELS:
        return CHECK_LABELS[name][1 if short else 0]
    return name.replace("_", " ")


def _result_class(result: object) -> str:
    if isinstance(result, bool):
        return "yes" if result else "no"
    return "score"


def _result_text(result: object) -> str:
    if isinstance(result, bool):
        return "YES" if result else "NO"
    return f"{result:g}" if isinstance(result, float) else str(result)


def _finding_lane(finding: dict) -> str:
    results = [c.get("result") for c in finding.get("checks", [])]
    if any(r is False for r in results):
        return "no"
    if any(not isinstance(r, bool) for r in results):
        return "score"
    return "yes"


def _anchor_spans(text: str, findings: list[dict]) -> list[tuple[int, int, dict]]:
    """Locate each finding's anchor quote in the flattened text.

    Quotes that don't occur in the text produce no span; their card still
    renders (the JS parks it at the top of the rail).
    """
    spans = []
    for f in findings:
        quote = (f.get("anchor") or {}).get("quote", "")
        if not quote:
            continue
        start = text.find(quote)
        if start < 0:
            continue
        spans.append((start, start + len(quote), f))
    return spans


def _mark_paragraph(par: str, offset: int, spans: list[tuple[int, int, dict]]) -> str:
    """Render one paragraph, wrapping annotated segments in <mark> tags.

    Overlapping and adjacent spans are handled by splitting the text at every
    span boundary; a segment covered by several findings carries all their ids
    in data-anno and takes the strongest lane for its color.
    """
    end = offset + len(par)
    local = [
        (max(s, offset) - offset, min(e, end) - offset, f)
        for s, e, f in spans
        if s < end and e > offset
    ]
    if not local:
        return escape(par)

    bounds = sorted({0, len(par), *(b for s, e, _ in local for b in (s, e))})
    out = []
    for seg_start, seg_end in zip(bounds, bounds[1:], strict=False):
        chunk = escape(par[seg_start:seg_end])
        covering = [f for s, e, f in local if s <= seg_start and e >= seg_end]
        if not covering:
            out.append(chunk)
            continue
        lane = min((_finding_lane(f) for f in covering), key=_LANE_RANK.__getitem__)
        ids = " ".join(str(f.get("id", "")).lower() for f in covering)
        out.append(f'<mark class="{lane}" data-anno="{escape(ids)}">{chunk}</mark>')
    return "".join(out)


_REF_RE = re.compile(r"^\[\d+\]")


def _render_document(doc: dict, findings: list[dict]) -> str:
    text = doc.get("text", "")
    spans = _anchor_spans(text, findings)

    body: list[str] = []
    refs: list[str] = []
    offset = 0
    for par in text.split("\n\n"):
        html = f"<p>{_mark_paragraph(par, offset, spans)}</p>"
        (refs if _REF_RE.match(par) else body).append(html)
        offset += len(par) + 2

    parts = ['<div class="doc">']
    if doc.get("title"):
        parts.append(f"<h3>{escape(doc['title'])}</h3>")
    if doc.get("byline"):
        parts.append(f'<p class="byline">{escape(doc["byline"])}</p>')
    parts.extend(body)
    if refs:
        parts.append('<div class="refs">')
        parts.extend(refs)
        parts.append("</div>")
    parts.append("</div>")
    return "\n".join(parts)


def _render_card(finding: dict) -> str:
    fid = str(finding.get("id", ""))
    lane = _finding_lane(finding)
    label = finding.get("label") or finding.get("target") or fid
    checks = finding.get("checks", [])

    summary = " · ".join(
        f"{escape(_check_label(c.get('name', ''), short=True))} "
        f'<span class="v-{_result_class(c.get("result"))}">{_result_text(c.get("result"))}</span>'
        for c in checks
    )
    rows = "\n".join(
        f"      <tr><td>{escape(_check_label(c.get('name', '')))}</td>"
        f'<td class="v-{_result_class(c.get("result"))}">{_result_text(c.get("result"))}</td></tr>'
        for c in checks
    )
    note = ""
    if finding.get("note"):
        note = f'\n    <p class="a-note">{escape(finding["note"])}</p>'

    head = (
        f'<span class="a-id {lane}">{escape(fid)}</span><span class="a-name">{escape(label)}</span>'
    )
    return f"""  <div class="anno" id="anno-{escape(fid.lower())}">
    <div class="a-head">{head}</div>
    <div class="a-sum">{summary}</div>
    <table class="kv">
{rows}
    </table>{note}
  </div>"""


def _render_ledger(ledger: list[dict]) -> str:
    rows = "\n".join(
        f"    <tr><td>{escape(row.get('label') or _check_label(row.get('check', '')))}</td>"
        f'<td class="r {_result_class(row.get("result"))}">{_result_text(row.get("result"))}</td>'
        f'<td class="d">{escape(str(row.get("detail", "")))}</td></tr>'
        for row in ledger
    )
    return f"""<div class="ledgerwrap">
<table class="ledger">
  <thead><tr><th>Check</th><th>Result</th><th>Detail</th></tr></thead>
  <tbody>
{rows}
  </tbody>
</table>
</div>"""


def _render_summary(ledger: list[dict], summary: dict) -> str:
    results = [row.get("result") for row in ledger]
    failed = sum(1 for r in results if r is False)
    passed = sum(1 for r in results if r is True)
    scores = sum(1 for r in results if not isinstance(r, bool))

    def _failed_line(row: dict) -> str:
        label = row.get("label") or _check_label(row.get("check", ""))
        return f"{label} ({row['detail']})" if row.get("detail") else label

    if failed:
        cls = ""
        plural = "s" if failed != 1 else ""
        headline = f"{failed} check{plural} failed — flag for human review"
        failed_lines = "; ".join(_failed_line(row) for row in ledger if row.get("result") is False)
        detail = f"Failed: {failed_lines}."
    else:
        cls, headline = " ok", "No checks failed"
        detail = "All boolean checks passed."
    detail += " Detector and similarity scores are context, not grounds."

    return f"""<div class="verdict{cls}">
  <p class="headline">{escape(headline)}</p>
  <p>{escape(detail)}</p>
  <p class="counts">NO ×{failed} · YES ×{passed} · scores ×{scores}</p>
</div>"""


def _header_facts(report: dict) -> str:
    run = report.get("run", {})
    facts = [
        report.get("solicitation"),
        run.get("date"),
        f"{len(report.get('ledger', []))} checks",
        f"{run['seconds']}s" if run.get("seconds") is not None else None,
    ]
    return " · ".join(str(f) for f in facts if f)


def render_report(report: dict) -> str:
    """Render a report dict to a single self-contained HTML page."""
    css = resources.files("slopchecker.report").joinpath("assets/report.css").read_text("utf-8")
    js = resources.files("slopchecker.report").joinpath("assets/report.js").read_text("utf-8")

    doc = report.get("document", {})
    findings = report.get("findings", [])
    ledger = report.get("ledger", [])

    docid_bits = [doc.get("file", "document")]
    if doc.get("title"):
        docid_bits.append(f"“{doc['title']}”")
    if doc.get("submitter"):
        docid_bits.append(f"({doc['submitter']})")
    docid = " — ".join(docid_bits[:2]) + (f" {docid_bits[2]}" if len(docid_bits) > 2 else "")

    cards = "\n\n".join(_render_card(f) for f in findings)
    report_json = escape(json.dumps(report, indent=2, ensure_ascii=False))
    hint = (
        "Checks appear beside the passages they refer to — click a card or highlight "
        "to expand/collapse. Red = failed a check · green = passed · purple = detector score."
    )
    schema_note = (
        '<span class="c">// results are true | false | number. '
        "No prose required from the checker.</span>"
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SlopChecker — Evidence Report — {escape(doc.get("file", "document"))}</title>
<style>
{css}</style>
</head>
<body>
<div class="wrap">

<header>
  <span class="name">SlopChecker</span>
  <span class="docid">{escape(docid)}</span>
  <span class="facts">{escape(_header_facts(report))}</span>
</header>
<p class="hint">{hint}</p>

<div class="layout">
{_render_document(doc, findings)}

<div class="rail">
{cards}
</div>
</div>

<h2>All checks</h2>
{_render_ledger(ledger)}

<h2>Summary</h2>
{_render_summary(ledger, report.get("summary", {}))}

<h2>report.json (this page is a render of this)</h2>
<div class="schema">{report_json}
{schema_note}</div>

<p class="foot">Screening aid, not a determination. Boolean findings are independently
verifiable. Scores are probabilistic and never sufficient on their own.</p>

</div>

<script>
{js}</script>
</body>
</html>
"""


def render_file(report_path: Path, out_path: Path | None = None) -> Path:
    """Render a report.json file to an HTML sibling (or explicit out path)."""
    report = json.loads(Path(report_path).read_text("utf-8"))
    out = Path(out_path) if out_path else Path(report_path).with_suffix(".html")
    out.write_text(render_report(report), encoding="utf-8")
    return out
