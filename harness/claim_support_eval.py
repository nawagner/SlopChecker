"""#104 — evaluation harness for the claim-support judge (ClaimSupportCheck, #11).

WHAT THIS SCORES, AND WHY THE JUDGE STAGE
-----------------------------------------
The shipped check (`ClaimSupportCheck.run`) is deliberately binary: it emits a
Finding only for `overstated`/`unsupported`/`contradicted` verdicts that clear
the confidence floor, carry a verbatim passage, and survive the refuter. The
`supported` and `unverifiable` outcomes are silent by design (#11: "bias hard
toward silence"). So the full check can never produce a five-way signal — the
five verdict categories only exist at the *judge* stage, before silencing.

A per-category confusion matrix (AC #3) and an evidence-based `min_confidence`
(AC #5) therefore have to score the judge's raw verdict. This harness reaches
into `ClaimSupportCheck._judge` on purpose: it exercises the real prompt,
schema, transport, retry, and payload-parsing code path rather than a copy, and
reads the verdict + confidence *before* run() collapses them to silence.

To confirm the end-to-end silencing still behaves, the harness also runs the
full `ClaimSupportCheck.run` over a small fabricated proposal whose claims are
all `supported`/`unverifiable`, and asserts that zero findings surface.

Every input is fabricated (see claim_support_corpus.yaml + CLAUDE.md). This
script makes real Anthropic API calls: one judge call per corpus triple, plus
up to 2N calls for the end-to-end pass. With the default corpus that is ~20-28
low-effort calls.

Usage:
    python harness/claim_support_eval.py                 # full run
    python harness/claim_support_eval.py --limit 3       # smoke test (3 triples)
    python harness/claim_support_eval.py --no-e2e        # skip the silence pass
    python harness/claim_support_eval.py --markdown out.md --json out.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

from slopchecker import config as _config
from slopchecker.models import FlattenedDoc, Verdict
from slopchecker.pipeline.claim_support import ClaimSupportCheck, ClaimSupportConfig
from slopchecker.pipeline.claim_support.check import _select_excerpt
from slopchecker.pipeline.claim_support.llm import (
    AnthropicTransport,
    TransportError,
    TransportRefusal,
)
from slopchecker.pipeline.quotes import LocalFileFetcher
from slopchecker.pipeline.quotes.matching import QuoteStatus, match_quote
from slopchecker.pipeline.registry import CheckContext

HERE = Path(__file__).parent
CORPUS_PATH = HERE / "claim_support_corpus.yaml"
FIXTURES_DIR = HERE / "claim_support_fixtures"
SILENCE_DOC = FIXTURES_DIR / "silence_proposal.txt"
SILENCE_SOURCES = FIXTURES_DIR / "sources"

# Canonical verdict order for the confusion matrix (matches the enum).
VERDICT_ORDER = [
    Verdict.supported,
    Verdict.overstated,
    Verdict.unsupported,
    Verdict.contradicted,
    Verdict.unverifiable,
]
VERDICTS = [v.value for v in VERDICT_ORDER]
CONCERNS = {Verdict.overstated.value, Verdict.unsupported.value, Verdict.contradicted.value}
# Clean = a claim that should never be flagged: flagging one is the costly
# false accusation CLAUDE.md warns about.
CLEAN = {Verdict.supported.value, Verdict.unverifiable.value}
_VERIFIED = {QuoteStatus.found_verbatim, QuoteStatus.found_minor_variation}


@dataclass
class Prediction:
    id: str
    gt: str
    pred: str | None  # None => judge errored or refused
    confidence: float
    passage_verified: bool  # concern verdicts need a passage that clears quotecheck
    error: str | None


# --- Corpus + judging -------------------------------------------------------


def load_corpus(path: Path) -> list[dict]:
    triples = yaml.safe_load(path.read_text()) or []
    bad = [t for t in triples if t.get("verdict") not in VERDICTS]
    if bad:
        ids = ", ".join(t.get("id", "?") for t in bad)
        raise SystemExit(f"corpus has triples with an unknown ground-truth verdict: {ids}")
    return triples


def judge_triples(
    triples: list[dict], check: ClaimSupportCheck, transport, max_source_chars: int
) -> list[Prediction]:
    preds: list[Prediction] = []
    for i, t in enumerate(triples, start=1):
        tid, gt = t["id"], t["verdict"]
        excerpt = _select_excerpt(t["source"].strip(), max_source_chars)
        try:
            jv = check._judge(
                claim=t["claim"].strip(),
                citation_marker=t.get("citation_marker", ""),
                source=excerpt,
                transport=transport,
            )
        except TransportRefusal as exc:
            preds.append(Prediction(tid, gt, None, 0.0, False, f"refused: {exc}"))
            print(f"  [{i:>2}/{len(triples)}] {tid:<8} gt={gt:<12} -> REFUSED", file=sys.stderr)
            continue
        except TransportError as exc:
            preds.append(Prediction(tid, gt, None, 0.0, False, f"transport error: {exc}"))
            print(f"  [{i:>2}/{len(triples)}] {tid:<8} gt={gt:<12} -> ERROR {exc}", file=sys.stderr)
            continue

        pred = jv.verdict.value
        verified = bool(jv.passage.strip()) and (
            match_quote(jv.passage, excerpt).status in _VERIFIED
        )
        mark = "ok " if pred == gt else "XX "
        print(
            f"  [{i:>2}/{len(triples)}] {tid:<8} gt={gt:<12} pred={pred:<12} "
            f"conf={jv.confidence:.2f} {mark}",
            file=sys.stderr,
        )
        preds.append(Prediction(tid, gt, pred, round(jv.confidence, 3), verified, None))
    return preds


# --- Metrics ----------------------------------------------------------------


def confusion_matrix(preds: list[Prediction]) -> dict[str, Counter]:
    matrix = {gt: Counter() for gt in VERDICTS}
    for p in preds:
        if p.pred is None:
            matrix[p.gt]["<error>"] += 1
        else:
            matrix[p.gt][p.pred] += 1
    return matrix


def per_category_scores(preds: list[Prediction]) -> dict[str, dict[str, float]]:
    scored = [p for p in preds if p.pred is not None]
    out: dict[str, dict[str, float]] = {}
    for c in VERDICTS:
        tp = sum(1 for p in scored if p.gt == c and p.pred == c)
        gt_total = sum(1 for p in scored if p.gt == c)
        pred_total = sum(1 for p in scored if p.pred == c)
        recall = tp / gt_total if gt_total else float("nan")
        precision = tp / pred_total if pred_total else float("nan")
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision and recall and not (precision != precision or recall != recall)
            else float("nan")
        )
        out[c] = {
            "support": gt_total,
            "predicted": pred_total,
            "tp": tp,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }
    return out


def threshold_sweep(preds: list[Prediction]) -> list[dict]:
    """For each candidate min_confidence, how concern predictions are gated.

    The knob only affects concern verdicts (run() drops concern verdicts below
    it). We split concern predictions into:
      - good flag:  ground truth is itself a concern (flagging is warranted).
      - false alarm: ground truth is clean (supported/unverifiable) -> a false
        accusation, the expensive error.
    We want the lowest threshold that retains no false alarms while keeping the
    most good flags. `exact` counts good flags whose concern label also matches.
    """
    concern_preds = [p for p in preds if p.pred in CONCERNS]
    good = [p for p in concern_preds if p.gt in CONCERNS]
    false_alarms = [p for p in concern_preds if p.gt in CLEAN]
    rows = []
    for t in [round(x / 100, 2) for x in range(50, 100, 5)]:
        retained_good = [p for p in good if p.confidence >= t]
        retained_false = [p for p in false_alarms if p.confidence >= t]
        rows.append(
            {
                "threshold": t,
                "good_flags_retained": len(retained_good),
                "good_flags_total": len(good),
                "false_alarms_retained": len(retained_false),
                "false_alarms_total": len(false_alarms),
                "exact_label_retained": sum(1 for p in retained_good if p.pred == p.gt),
            }
        )
    return rows


def recommend_threshold(sweep: list[dict], default: float) -> tuple[float, str]:
    have_false = any(r["false_alarms_total"] for r in sweep)
    if not have_false:
        return (
            default,
            "no false alarms at any threshold in this corpus — the judge did not "
            "flag a single clean claim as a concern. Keep the current default and "
            "re-evaluate on a larger corpus; this run gives no evidence to raise it.",
        )
    # Lowest threshold that fully suppresses false alarms while keeping the most good flags.
    clean_rows = [r for r in sweep if r["false_alarms_retained"] == 0]
    if not clean_rows:
        top = max(sweep, key=lambda r: r["threshold"])
        return (
            top["threshold"],
            "even the highest tested threshold leaves false alarms — the judge "
            "produced confident false accusations. min_confidence alone cannot fix "
            "this; inspect those triples before trusting concern findings.",
        )
    best = min(clean_rows, key=lambda r: r["threshold"])
    return (
        best["threshold"],
        f"lowest threshold that drops all false alarms; retains "
        f"{best['good_flags_retained']}/{best['good_flags_total']} warranted flags "
        f"({best['exact_label_retained']} with the exact concern label).",
    )


# --- End-to-end silence pass ------------------------------------------------


@dataclass
class SilenceResult:
    ran: bool
    findings: int
    detail: str


def run_silence_check(transport, config: ClaimSupportConfig) -> SilenceResult:
    if not SILENCE_DOC.is_file():
        return SilenceResult(False, -1, f"missing fixture {SILENCE_DOC}")
    doc = FlattenedDoc(file=SILENCE_DOC.name, text=SILENCE_DOC.read_text())
    fetcher = LocalFileFetcher(SILENCE_SOURCES)
    check = ClaimSupportCheck(config=config, fetcher=fetcher, transport=transport)
    out = check.run(doc, CheckContext(workdir=FIXTURES_DIR))
    n = len(out.findings)
    if n == 0:
        detail = "PASS — all supported/unverifiable claims stayed silent."
    else:
        flagged = ", ".join(f"{f.target}:{f.verdict}" for f in out.findings)
        detail = f"FAIL — {n} finding(s) surfaced on clean claims: {flagged}"
    return SilenceResult(True, n, detail)


# --- Rendering --------------------------------------------------------------


def _fmt(x: float) -> str:
    return "  n/a" if x != x else f"{x:5.2f}"


def render_report(
    preds: list[Prediction],
    matrix: dict[str, Counter],
    scores: dict[str, dict[str, float]],
    sweep: list[dict],
    rec: tuple[float, str],
    default_min_conf: float,
    silence: SilenceResult | None,
) -> str:
    scored = [p for p in preds if p.pred is not None]
    errored = [p for p in preds if p.pred is None]
    overall_acc = sum(1 for p in scored if p.pred == p.gt) / len(scored) if scored else float("nan")

    lines: list[str] = []
    lines.append("# Claim-support judge evaluation (#104)")
    lines.append("")
    lines.append(
        f"Corpus: {len(preds)} fabricated triples "
        f"({len(scored)} judged, {len(errored)} errored/refused). "
        f"Overall judge accuracy: **{overall_acc:.0%}**."
    )
    lines.append("")

    # Confusion matrix.
    lines.append("## Confusion matrix (rows = ground truth, cols = judge verdict)")
    lines.append("")
    header_cols = VERDICTS + (["<error>"] if errored else [])
    short = {v: v[:5] for v in VERDICTS}
    short["<error>"] = "err"
    head = "| gt \\ pred | " + " | ".join(short[c] for c in header_cols) + " | total |"
    sep = "|" + "---|" * (len(header_cols) + 2)
    lines.append(head)
    lines.append(sep)
    for gt in VERDICTS:
        row = matrix[gt]
        cells = [str(row.get(c, 0)) for c in header_cols]
        total = sum(row.values())
        diag = row.get(gt, 0)
        marker = " ✓" if diag == total and total else ""
        lines.append(f"| **{gt}** | " + " | ".join(cells) + f" | {total}{marker} |")
    lines.append("")

    # Per-category table.
    lines.append("## Per-category precision / recall")
    lines.append("")
    lines.append("| verdict | support | precision | recall | f1 |")
    lines.append("|---|---|---|---|---|")
    for c in VERDICTS:
        s = scores[c]
        lines.append(
            f"| {c} | {s['support']} | {_fmt(s['precision'])} | "
            f"{_fmt(s['recall'])} | {_fmt(s['f1'])} |"
        )
    lines.append("")

    # Passage verification among concern predictions.
    concern_preds = [p for p in scored if p.pred in CONCERNS]
    if concern_preds:
        verified = sum(1 for p in concern_preds if p.passage_verified)
        lines.append(
            f"**Passage quotecheck:** {verified}/{len(concern_preds)} concern verdicts "
            f"carried a passage that clears `match_quote` (the gate before a finding "
            f"reaches the report)."
        )
        lines.append("")

    # Threshold sweep.
    lines.append("## `min_confidence` threshold sweep (concern verdicts only)")
    lines.append("")
    lines.append(
        "The knob drops concern verdicts below the threshold. *Good flags* have a "
        "concern ground truth; *false alarms* flag a clean (supported/unverifiable) "
        "claim — the costly error."
    )
    lines.append("")
    lines.append("| threshold | good flags kept | false alarms kept | exact-label kept |")
    lines.append("|---|---|---|---|")
    for r in sweep:
        lines.append(
            f"| {r['threshold']:.2f} | {r['good_flags_retained']}/{r['good_flags_total']} "
            f"| {r['false_alarms_retained']}/{r['false_alarms_total']} "
            f"| {r['exact_label_retained']} |"
        )
    lines.append("")
    rec_t, rec_why = rec
    lines.append(
        f"**Recommended `min_confidence`: {rec_t:.2f}** (current default "
        f"{default_min_conf:.2f}). {rec_why}"
    )
    lines.append("")

    # Silence pass.
    if silence is not None:
        lines.append("## End-to-end silence check")
        lines.append("")
        if silence.ran:
            lines.append(silence.detail)
        else:
            lines.append(f"skipped — {silence.detail}")
        lines.append("")

    # Misclassification detail.
    misses = [p for p in scored if p.pred != p.gt]
    if misses:
        lines.append("## Misclassifications")
        lines.append("")
        for p in misses:
            lines.append(
                f"- `{p.id}`: ground truth **{p.gt}** -> judge **{p.pred}** "
                f"(conf {p.confidence:.2f})"
            )
        lines.append("")

    lines.append(
        "_Small-n caveat: this is a ~20-item fabricated corpus. Treat the numbers as "
        "directional smoke-tests of judge behavior, not production accuracy claims._"
    )
    return "\n".join(lines)


# --- CLI --------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Evaluate the claim-support judge (#104).")
    ap.add_argument("--limit", type=int, default=0, help="judge only the first N triples")
    ap.add_argument("--no-e2e", action="store_true", help="skip the end-to-end silence pass")
    ap.add_argument("--markdown", type=Path, help="write the report to this markdown file")
    ap.add_argument("--json", type=Path, help="write raw predictions + metrics to this JSON file")
    ap.add_argument("--model", help="override judge/refuter model (default: config default)")
    args = ap.parse_args(argv)

    try:
        api_key = _config.require("ANTHROPIC_API_KEY")
    except _config.MissingCredential as exc:
        print(
            f"error: {exc}. Set ANTHROPIC_API_KEY in your environment or a .env file "
            f"before running the eval (it makes real API calls).",
            file=sys.stderr,
        )
        return 2

    overrides = {}
    if args.model:
        overrides = {"judge_model": args.model, "refuter_model": args.model}
    config = ClaimSupportConfig(**overrides)
    transport = AnthropicTransport(api_key=api_key)
    check = ClaimSupportCheck(config=config, fetcher=None, transport=transport)

    triples = load_corpus(CORPUS_PATH)
    if args.limit:
        triples = triples[: args.limit]
    print(f"Judging {len(triples)} triple(s) with {config.judge_model}...", file=sys.stderr)
    preds = judge_triples(triples, check, transport, config.max_source_chars)

    matrix = confusion_matrix(preds)
    scores = per_category_scores(preds)
    sweep = threshold_sweep(preds)
    rec = recommend_threshold(sweep, config.min_confidence)

    silence: SilenceResult | None = None
    if not args.no_e2e:
        print("Running end-to-end silence check...", file=sys.stderr)
        silence = run_silence_check(transport, config)

    report = render_report(preds, matrix, scores, sweep, rec, config.min_confidence, silence)
    print("\n" + report)

    if args.markdown:
        args.markdown.write_text(report + "\n")
        print(f"\n[wrote markdown report -> {args.markdown}]", file=sys.stderr)
    if args.json:
        payload = {
            "predictions": [asdict(p) for p in preds],
            "confusion_matrix": {gt: dict(c) for gt, c in matrix.items()},
            "per_category": scores,
            "threshold_sweep": sweep,
            "recommended_min_confidence": rec[0],
            "recommendation_rationale": rec[1],
            "silence_findings": silence.findings if silence else None,
        }
        args.json.write_text(json.dumps(payload, indent=2))
        print(f"[wrote json -> {args.json}]", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
