"""Before/after eval of the claims lens prompt tune (#144).

Runs lens v0.1 (HEAD) and v0.2 (working tree) over the synthetic corpus
markdown fixtures plus the two harness proposals with their pending_lens:claims
defects injected, and records every extraction to a checkpointed JSONL.

Conditions recorded per row: lens version + sha256, model, doc id, run index.
Resume-safe: rows already present in results.jsonl are skipped.

Usage:  .venv/bin/python lens-eval/run_eval.py
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv

WORKTREE = Path(__file__).resolve().parent.parent
MAIN_CHECKOUT = Path("/Users/dan/code/SlopChecker")
RESULTS = Path(__file__).resolve().parent / "results.jsonl"
V01_DIR = Path(__file__).resolve().parent / "lens_v01"

# Real env vars win over the file, matching slopchecker.config.load().
load_dotenv(MAIN_CHECKOUT / ".env.local", override=False)

from slopchecker import config  # noqa: E402
from slopchecker.ingest import ingest  # noqa: E402
from slopchecker.lenses import load_lens  # noqa: E402
from slopchecker.pipeline.lens_runtime import LensRunConfig, run_lens  # noqa: E402

CORPUS = sorted((WORKTREE / "tests/fixtures/synthetic/files").glob("*.md"))
# The live-site failure (#144 screenshot) was on the PDF rendition — PDF
# extraction text (per-line \n, no headings) is the real regression case.
PDF_DOCS = [WORKTREE / "tests/fixtures/synthetic/files/blog_post__ai_clean.pdf"]

# The two harness defects the claims lens exists to catch (harness/defects.yaml,
# pending_lens: claims). Injected the same way injector.inject does: first
# occurrence, hard error if the original string is missing.
DEFECTS = [
    {
        "doc_id": "proposal_climate+unsupported-claim",
        "file": WORKTREE / "harness/fixtures/proposal_climate.md",
        "original": "We will partner with the planning departments",
        "mutated": (
            "Our approach will improve municipal heat-illness outcomes by\n"
            "approximately 65% within the first deployment season. We will partner\n"
            "with the planning departments"
        ),
        "must_catch": "65%",  # a surviving claim quote must contain this
    },
    {
        "doc_id": "proposal_edu+misattr",
        "file": WORKTREE / "harness/fixtures/proposal_edu.md",
        "original": "one of the strongest classroom-observable predictors of later algebra",
        "mutated": "the single best-established causal driver of college completion rates,",
        "must_catch": "causal driver of college completion",
    },
]

# Triple runs where variance matters most; single elsewhere.
KEY_DOCS = {
    "blog_post__ai_clean",
    "blog_post__ai_clean_pdf",
    "proposal_climate+unsupported-claim",
    "proposal_edu+misattr",
}
REPEATS = 3


def materialize_v01() -> None:
    """Write the pre-tune lens from the branch point.

    Pinned to merge-base(HEAD, origin/main), NOT HEAD: an earlier revision
    used HEAD, which silently became the *tuned* lens once the tuning
    commits landed — the round-3 rows labeled v0.1r2 actually ran v0.3
    (verifiable via their lens_sha). See lens-eval/README.md.
    """
    V01_DIR.mkdir(parents=True, exist_ok=True)
    base = subprocess.run(
        ["git", "-C", str(WORKTREE), "merge-base", "HEAD", "origin/main"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    text = subprocess.run(
        ["git", "-C", str(WORKTREE), "show", f"{base}:src/slopchecker/lenses/claims.md"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    (V01_DIR / "claims.md").write_text(text, encoding="utf-8")


def lens_sha(lens) -> str:
    payload = (lens.system_prompt + "\x00" + lens.output_format).encode()
    return hashlib.sha256(payload).hexdigest()[:12]


def build_docs() -> dict[str, object]:
    docs: dict[str, object] = {}
    for path in CORPUS:
        result = ingest(path)
        if result.status != "ok" or result.document is None:
            print(f"SKIP (ingest {result.status}): {path.name}", file=sys.stderr)
            continue
        docs[path.stem] = result.document
    for path in PDF_DOCS:
        result = ingest(path)
        assert result.status == "ok" and result.document is not None, path
        docs[path.stem + "_pdf"] = result.document
    for defect in DEFECTS:
        result = ingest(defect["file"])
        assert result.status == "ok" and result.document is not None, defect["file"]
        text = result.document.text
        if defect["original"] not in text:
            raise SystemExit(f"defect original not found in {defect['file']}")
        docs[defect["doc_id"]] = result.document.model_copy(
            update={"text": text.replace(defect["original"], defect["mutated"], 1)}
        )
    return docs


def existing_keys() -> set[tuple[str, str, int]]:
    if not RESULTS.exists():
        return set()
    keys = set()
    for line in RESULTS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            keys.add((row["version"], row["doc_id"], row["run"]))
    return keys


def one_run(version: str, lens, doc_id: str, doc, run_idx: int, model: str) -> dict:
    t0 = time.time()
    result = run_lens(lens, doc, LensRunConfig())  # no cache: every run is a real call
    claims = (result.payload or {}).get("claims", []) if result.status == "ok" else []
    return {
        "version": version,
        "lens_sha": lens_sha(lens),
        "model": model,
        "doc_id": doc_id,
        "run": run_idx,
        "status": result.status,
        "reason": result.reason,
        "n_claims": len(claims),
        "unanchored": (result.payload or {}).get("unanchored_claims", 0),
        "quant_unsourced": sum(
            1 for c in claims if c.get("quantitative") and c.get("citation") is None
        ),
        # Record claims whole — an earlier whitelist here silently dropped the
        # scope field and cost a re-run. Ironic, given the session topic.
        "claims": claims,
        "duration_s": round(time.time() - t0, 2),
    }


def main() -> None:
    if config.get("ANTHROPIC_API_KEY") is None:
        raise SystemExit("ANTHROPIC_API_KEY not loaded — check .env.local")
    materialize_v01()
    model = config.llm_model()
    # r2: tolerant anchoring + whole-claim recording. v0.1r2 runs key docs only
    # (diagnostic: does tolerant anchoring alone explain the ok-with-0 runs?).
    lenses = {
        "v0.1r3": load_lens("claims", directory=V01_DIR),
        "v0.3r2": load_lens("claims", directory=WORKTREE / "src/slopchecker/lenses"),
    }
    docs = build_docs()
    done = existing_keys()

    tasks = []
    for version, lens in lenses.items():
        for doc_id, doc in docs.items():
            if version.startswith("v0.1") and doc_id not in KEY_DOCS:
                continue
            runs = REPEATS if doc_id in KEY_DOCS else 1
            for run_idx in range(runs):
                if (version, doc_id, run_idx) not in done:
                    tasks.append((version, lens, doc_id, doc, run_idx))
    print(f"{len(tasks)} runs to do ({len(done)} already checkpointed), model={model}")

    with RESULTS.open("a", encoding="utf-8") as sink:
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {
                pool.submit(one_run, v, lens, d_id, doc, r, model): (v, d_id, r)
                for v, lens, d_id, doc, r in tasks
            }
            for future in as_completed(futures):
                version, doc_id, run_idx = futures[future]
                try:
                    row = future.result()
                except Exception as exc:  # record, never crash the sweep
                    row = {
                        "version": version,
                        "doc_id": doc_id,
                        "run": run_idx,
                        "model": model,
                        "status": "eval_error",
                        "reason": repr(exc),
                        "n_claims": None,
                        "quant_unsourced": None,
                        "claims": [],
                    }
                sink.write(json.dumps(row) + "\n")
                sink.flush()  # checkpoint per unit of work
                print(
                    f"  {version} {doc_id} run{row['run']}: "
                    f"{row['status']} n_claims={row['n_claims']}"
                )
    print(f"done -> {RESULTS}")


if __name__ == "__main__":
    main()
