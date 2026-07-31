#!/usr/bin/env python3
"""Score a SlopChecker checker against the synthetic corpus ground truth.

Reads `manifest.csv` (the ground-truth labels emitted by synth_proposals.py) and
a set of predictions, then reports precision / recall / F1 / accuracy per defect
type. This is the eval loop: a checker either recovers the planted defects or it
doesn't, measurably.

Predictions come from one of:
    --predictions FILE   JSONL or CSV with an `id` field plus any boolean
                         prediction fields (ai_generated, has_fabricated_citations,
                         overclaims, budget_inflated, missing_methods).
    --demo               run the built-in naive-baseline checker over corpus.jsonl
                         so you can see the harness end to end with no real checker.

Examples
--------
    python3 score.py --corpus ./demo_anthropic2 --demo
    python3 score.py --corpus ./demo_anthropic2 --predictions my_checker_out.jsonl
"""

import argparse
import csv
import json
import os

FIELDS = [
    "ai_generated",
    "has_fabricated_citations",
    "overclaims",
    "budget_inflated",
    "missing_methods",
]

OVERCLAIM_MARKERS = [
    "definitively cure",
    "guaranteed to outperform",
    "success is certain",
    "no meaningful risks",
    "transform practice nationwide",
    "no risks or limitations",
]
BUDGET_INFLATED_THRESHOLD = 3_000_000


def _to_bool(v):
    return str(v).strip().lower() in ("true", "1", "yes")


def load_manifest(corpus_dir):
    path = os.path.join(corpus_dir, "manifest.csv")
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    truth = {}
    for r in rows:
        truth[r["id"]] = {k: _to_bool(r[k]) for k in FIELDS}
    return truth


def load_predictions(path):
    preds = {}
    if path.endswith(".jsonl"):
        for line in open(path):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            preds[r["id"]] = {k: bool(r.get(k, False)) for k in FIELDS}
    else:
        with open(path, newline="") as f:
            for r in csv.DictReader(f):
                preds[r["id"]] = {k: _to_bool(r.get(k, "False")) for k in FIELDS}
    return preds


# --------------------------------------------------------------------------- #
# Naive baseline checker (demo only -- deliberately simple, not a real checker)
# --------------------------------------------------------------------------- #
def demo_checker(corpus_dir):
    preds = {}
    for line in open(os.path.join(corpus_dir, "corpus.jsonl")):
        r = json.loads(line)
        text = r["text"].lower()
        budget = r["meta"].get("requested_budget_usd") or 0
        n_unresolvable = r["meta"].get("n_unresolvable_citations", 0)
        preds[r["id"]] = {
            "ai_generated": ("**" in r["text"] or "specific aims" in text),  # toy format tell
            "has_fabricated_citations": n_unresolvable > 0,  # a real deterministic check
            "overclaims": any(m in text for m in OVERCLAIM_MARKERS),
            "budget_inflated": budget > BUDGET_INFLATED_THRESHOLD,
            "missing_methods": "appropriate methods to achieve the aims" in text,
        }
    return preds


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #
def score_field(truth, preds, field):
    tp = fp = fn = tn = 0
    for id_, t in truth.items():
        if id_ not in preds:
            continue
        actual, pred = t[field], preds[id_][field]
        if pred and actual:
            tp += 1
        elif pred and not actual:
            fp += 1
        elif not pred and actual:
            fn += 1
        else:
            tn += 1
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    f1 = 2 * precision * recall / (precision + recall) if precision and recall else None
    accuracy = (tp + tn) / (tp + fp + fn + tn) if (tp + fp + fn + tn) else None
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "support": tp + fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "accuracy": accuracy,
    }


def _fmt(x):
    return "  n/a" if x is None else f"{x:5.2f}"


def main():
    ap = argparse.ArgumentParser(
        description="Score a checker against synthetic corpus ground truth."
    )
    ap.add_argument(
        "--corpus", default="./synthetic_proposals", help="dir with manifest.csv + corpus.jsonl"
    )
    ap.add_argument("--predictions", help="JSONL/CSV of predictions (id + boolean fields)")
    ap.add_argument("--demo", action="store_true", help="run the built-in naive baseline instead")
    args = ap.parse_args()

    truth = load_manifest(args.corpus)
    if args.demo:
        preds = demo_checker(args.corpus)
        source = "built-in naive baseline"
    elif args.predictions:
        preds = load_predictions(args.predictions)
        source = args.predictions
    else:
        ap.error("pass --predictions FILE or --demo")

    scored = {id_ for id_ in truth if id_ in preds}
    print(f"Corpus:      {args.corpus}  ({len(truth)} docs)")
    print(f"Predictions: {source}  ({len(scored)} scored)\n")
    header = f"{'defect':<26}{'prec':>7}{'recall':>8}{'f1':>7}{'acc':>7}{'support':>9}"
    print(header)
    print("-" * len(header))
    for field in FIELDS:
        m = score_field(truth, preds, field)
        print(
            f"{field:<26}{_fmt(m['precision']):>7}{_fmt(m['recall']):>8}"
            f"{_fmt(m['f1']):>7}{_fmt(m['accuracy']):>7}{m['support']:>9}"
        )
    print("\nsupport = number of docs where the defect is actually present (positives).")
    print("prec/recall n/a = no positive predictions or labels for that field.")


if __name__ == "__main__":
    main()
