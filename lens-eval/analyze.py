"""Summarize lens-eval results: per-version counts, scope split, must-catch."""

import json
import sys
from collections import defaultdict
from pathlib import Path

VERSIONS = sys.argv[1:] or ["v0.1r2", "v0.3r2"]

ROWS = [
    json.loads(line)
    for line in (Path(__file__).parent / "results.jsonl").read_text().splitlines()
    if line.strip()
]

MUST_CATCH = {
    "proposal_climate+unsupported-claim": "65%",
    "proposal_edu+misattr": "causal driver of college completion",
}

by_doc = defaultdict(lambda: defaultdict(list))
for row in ROWS:
    if row["version"] in VERSIONS:
        by_doc[row["doc_id"]][row["version"]].append(row)


def cell(runs):
    """n_claims per run; v0.3 shows specific+background split."""
    out = []
    for r in sorted(runs, key=lambda r: r["run"]):
        spec = sum(1 for c in r["claims"] if c.get("scope") != "background")
        bg = sum(1 for c in r["claims"] if c.get("scope") == "background")
        text = f"{spec}+{bg}b" if bg else str(r["n_claims"])
        if r.get("unanchored"):
            text += f"({r['unanchored']}u)"
        out.append(text)
    return "/".join(out) if out else "-"


print(f"{'doc':45s}  {VERSIONS[0]:>10s}  {VERSIONS[1]:>14s}")
for doc_id in sorted(by_doc):
    print(
        f"{doc_id:45s}  {cell(by_doc[doc_id][VERSIONS[0]]):>10s}"
        f"  {cell(by_doc[doc_id][VERSIONS[1]]):>14s}"
    )

print("\n== must-catch (planted defect present in extracted quotes?) ==")
for doc_id, needle in MUST_CATCH.items():
    for version in VERSIONS:
        for row in sorted(by_doc[doc_id][version], key=lambda r: r["run"]):
            matches = [
                (c["type"], c.get("scope"), c["quantitative"], c["citation"])
                for c in row["claims"]
                if needle in (c.get("quote") or "")
            ]
            verdict = "CAUGHT" if matches else "MISSED"
            print(f"  {version} {doc_id} run{row['run']}: {verdict} {matches}")

print("\n== claim detail: docs of interest ==")
for doc_id in ("blog_post__overclaims", "blog_post__ai_clean_pdf"):
    for version in VERSIONS:
        for row in sorted(by_doc[doc_id][version], key=lambda r: r["run"]):
            print(f"  {version} {doc_id} run{row['run']} (n={row['n_claims']}):")
            for c in row["claims"]:
                print(
                    f"    [{c['type']}/{c.get('scope', '?')}] quant={c['quantitative']}"
                    f" cite={c['citation']} :: {(c['quote'] or '')[:80]}"
                )
