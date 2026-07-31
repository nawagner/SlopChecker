"""Batch summary view (#20): many report dicts in, one triage table out.

A funder triages a stack, not a document. This module renders the static,
self-contained ``summary.html`` for a batch run: one row per document,
sortable and filterable with no backend, each row linking into that
document's full evidence report. CSV/JSON export happens client-side from
the same embedded rows the table is built from, so what you export is what
you see.

Same discipline as the single-document renderer: pure function of the
report dicts, no checks re-run, no network.
"""

from __future__ import annotations

import json
from html import escape
from importlib import resources

# Findings whose ids carry these prefixes are citation-integrity findings
# (DOI/URL resolution, in-text citations, metadata) — the triage table rolls
# them into one "citation flags" count.
_CITATION_PREFIXES = ("DOI", "URL", "CIT", "MD")

# Column order for the table and both exports. (key, label, numeric)
_COLUMNS = [
    ("file", "File", False),
    ("concerns", "Concerns", True),
    ("doc_type", "Doc type", False),
    ("pangram", "Detection", True),
    ("citation_flags", "Citation flags", True),
    ("similarity", "Similarity", False),
    ("failed", "Failed", True),
    ("passed", "Passed", True),
    ("skipped", "Skipped", True),
    ("errored", "Errored", True),
    ("findings", "Findings", True),
]


def summarize_for_batch(report: dict, link: str = "") -> dict:
    """One report dict → one flat triage row.

    Values are str/int/float only — this row goes straight into CSV/JSON.
    ``link`` is the (relative) href of the document's rendered report.
    """
    ledger = report.get("ledger", [])
    ran = [r for r in ledger if r.get("status", "ok") == "ok"]
    failed = sum(1 for r in ran if r.get("result") is False)
    passed = sum(1 for r in ran if r.get("result") is True)
    scores = sum(1 for r in ran if not isinstance(r.get("result"), bool))
    skipped = sum(1 for r in ledger if r.get("status") == "skipped")
    errored = sum(1 for r in ledger if r.get("status") == "errored")

    def row_for(check: str) -> dict | None:
        r = next((r for r in ledger if r.get("check") == check), None)
        return r if r is not None and r.get("status", "ok") == "ok" else None

    doc_type = row_for("doc_type_confidence")
    pangram = row_for("pangram_document")
    similar = row_for("similar_documents")
    citation_flags = sum(
        1
        for f in report.get("findings", [])
        if str(f.get("id", "")).upper().startswith(_CITATION_PREFIXES)
        and any(c.get("result") is False for c in f.get("checks", []))
    )

    return {
        "file": report.get("document", {}).get("file", ""),
        "concerns": failed + errored,
        "doc_type": str(doc_type.get("detail") or "").split(" — ")[0] if doc_type else "",
        "pangram": pangram.get("result", "") if pangram else "",
        "citation_flags": citation_flags,
        "similarity": str(similar.get("detail") or similar.get("result") or "") if similar else "",
        "failed": failed,
        "passed": passed,
        "scores": scores,
        "skipped": skipped,
        "errored": errored,
        "findings": len(report.get("findings", [])),
        "link": link,
    }


def _cell(row: dict, key: str) -> str:
    val = row.get(key, "")
    if key == "file":
        name = escape(str(val))
        link = row.get("link") or ""
        return f'<a href="{escape(link)}">{name}</a>' if link else name
    if key == "concerns" and "error" in row:
        return '<span class="gap">not read</span>'
    if isinstance(val, float):
        return f"{val:g}"
    return escape(str(val))


def _row_html(row: dict) -> str:
    cells = "".join(
        f'<td class="{"n" if numeric else "t"}">{_cell(row, key)}</td>'
        for key, _, numeric in _COLUMNS
    )
    title = f' title="{escape(str(row["error"]))}"' if "error" in row else ""
    return f"<tr{title}>{cells}</tr>"


_BATCH_CSS = """
.controls { display: flex; gap: .75rem; align-items: center; margin: 0 0 1rem; }
.controls input { font: inherit; padding: .35rem .6rem; border: 1px solid var(--rule);
                  border-radius: 4px; background: var(--bg); color: var(--ink); width: 18rem; }
.controls button { font: inherit; font-size: .8rem; padding: .35rem .8rem; cursor: pointer;
                   border: 1px solid var(--rule); border-radius: 4px;
                   background: var(--panel); color: var(--ink); }
.controls .count { font-family: var(--mono); font-size: .78rem; color: var(--soft);
                   margin-left: auto; }
.ledger th { cursor: pointer; user-select: none; white-space: nowrap; }
.ledger th .dir { opacity: .5; font-size: .9em; }
.ledger td.n { font-family: var(--mono); text-align: right; }
.ledger td.t { max-width: 18rem; overflow: hidden; text-overflow: ellipsis; }
.ledger a { color: var(--accent); }
.gap { color: var(--soft); font-style: italic; }
"""

_BATCH_JS = """
(function () {
  var rows = JSON.parse(document.getElementById("rows-json").textContent);
  var tbody = document.querySelector("tbody");
  var trs = Array.prototype.slice.call(tbody.querySelectorAll("tr"));
  var ths = Array.prototype.slice.call(document.querySelectorAll("th[data-key]"));
  var filter = document.getElementById("filter");
  var count = document.getElementById("count");
  var sortKey = "concerns", sortDir = -1;

  function val(i, key) {
    var v = rows[i][key];
    return v === undefined || v === null ? "" : v;
  }
  function apply() {
    var q = filter.value.toLowerCase();
    var order = trs.map(function (_, i) { return i; }).sort(function (a, b) {
      var x = val(a, sortKey), y = val(b, sortKey);
      var nx = parseFloat(x), ny = parseFloat(y);
      var c = (!isNaN(nx) && !isNaN(ny)) ? nx - ny : String(x).localeCompare(String(y));
      return sortDir * c;
    });
    var shown = 0;
    order.forEach(function (i) {
      var tr = trs[i];
      var hit = !q || tr.textContent.toLowerCase().indexOf(q) !== -1;
      tr.style.display = hit ? "" : "none";
      if (hit) shown++;
      tbody.appendChild(tr);
    });
    count.textContent = shown + " / " + trs.length + " documents";
    ths.forEach(function (th) {
      var d = th.querySelector(".dir");
      var active = th.getAttribute("data-key") === sortKey;
      d.textContent = active ? (sortDir < 0 ? "\\u25be" : "\\u25b4") : "";
    });
  }
  ths.forEach(function (th) {
    th.addEventListener("click", function () {
      var key = th.getAttribute("data-key");
      sortDir = key === sortKey ? -sortDir : (th.getAttribute("data-num") === "1" ? -1 : 1);
      sortKey = key;
      apply();
    });
  });
  filter.addEventListener("input", apply);

  function visible() {
    return trs.map(function (tr, i) { return { tr: tr, i: i }; })
      .filter(function (x) { return x.tr.style.display !== "none"; })
      .sort(function (a, b) {
        var kids = Array.prototype.slice.call(tbody.children);
        return kids.indexOf(a.tr) - kids.indexOf(b.tr);
      })
      .map(function (x) { return rows[x.i]; });
  }
  function download(name, mime, text) {
    var a = document.createElement("a");
    a.href = "data:" + mime + ";charset=utf-8," + encodeURIComponent(text);
    a.download = name;
    a.click();
  }
  var FIELDS = JSON.parse(document.getElementById("fields-json").textContent);
  document.getElementById("csv").addEventListener("click", function () {
    var esc = function (v) {
      v = v === undefined || v === null ? "" : String(v);
      return /[",\\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v;
    };
    var lines = [FIELDS.join(",")].concat(visible().map(function (r) {
      return FIELDS.map(function (f) { return esc(r[f]); }).join(",");
    }));
    download("summary.csv", "text/csv", lines.join("\\n"));
  });
  document.getElementById("json").addEventListener("click", function () {
    download("summary.json", "application/json", JSON.stringify(visible(), null, 2));
  });
  apply();
})();
"""


def render_batch(rows: list[dict], title: str = "Batch summary") -> str:
    """Render triage rows to a single self-contained, sortable HTML page.

    ``rows`` are ``summarize_for_batch`` rows, plus ingest-gap rows of the
    shape ``{"file": ..., "error": reason}`` — gaps render as "not read" and
    sort to the bottom, they never break the table.
    """
    css = resources.files("slopchecker.report").joinpath("assets/report.css").read_text("utf-8")
    fields = [key for key, _, _ in _COLUMNS] + ["link", "error"]
    heads = "".join(
        f'<th data-key="{key}" data-num="{int(numeric)}">{escape(label)} '
        f'<span class="dir"></span></th>'
        for key, label, numeric in _COLUMNS
    )
    body = "\n".join(_row_html(r) for r in rows)
    rows_json = json.dumps(rows, ensure_ascii=False).replace("</", "<\\/")
    n = len(rows)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SlopChecker — {escape(title)}</title>
<style>
{css}
{_BATCH_CSS}</style>
</head>
<body>
<div class="wrap">

<header>
  <span class="name">SlopChecker</span>
  <span class="docid">{escape(title)}</span>
  <span class="facts">{n} document(s)</span>
</header>
<p class="hint">Click a column to sort, type to filter, click a file for its full
evidence report. Exports contain exactly the rows currently shown.
Screening aid, not a determination — detection scores are context, not grounds.</p>

<div class="controls">
  <input id="filter" type="search" placeholder="Filter rows…">
  <button id="csv">Export CSV</button>
  <button id="json">Export JSON</button>
  <span class="count" id="count"></span>
</div>

<div class="ledgerwrap">
<table class="ledger">
  <thead><tr>{heads}</tr></thead>
  <tbody>
{body}
  </tbody>
</table>
</div>

<script type="application/json" id="rows-json">{rows_json}</script>
<script type="application/json" id="fields-json">{json.dumps(fields)}</script>
<script>
{_BATCH_JS}</script>
</div>
</body>
</html>
"""
