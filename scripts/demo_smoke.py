#!/usr/bin/env python3
"""Pre-demo smoke of the deployed pipeline (#142). Run it before walking on stage.

Uploads a fabricated fixture to the live site's ``/api/check`` (Worker →
Railway, exactly the path a funder's browser takes) and audits the returned
ledger:

* FAIL — HTTP failure; any ``errored`` row; a check registered locally that is
  missing from the deployed ledger; a demo-critical check that ``skipped``
  (``claims`` or ``pangram_document`` skipping means keys are broken on
  Railway — the #115 failure mode).
* WARN — expected single-upload coverage gaps (``similar_documents`` has no
  batch, ``claim_supported``/``metadata_match`` depend on source coverage),
  or a local-vs-deployed roster mismatch (usually: your checkout is ahead of
  the last deploy).

Usage (from the repo root, any teammate's laptop)::

    uv run python scripts/demo_smoke.py                # hits slop-checker.com
    uv run python scripts/demo_smoke.py --url http://localhost:8000 --local-api
    uv run python scripts/demo_smoke.py --lenient      # demo-critical -> warn

Exit code 0 = safe to demo, 1 = do not walk on stage yet. Real Pangram +
Anthropic calls happen server-side on every run; that is the point, but don't
loop it.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = (
    REPO_ROOT / "tests" / "fixtures" / "synthetic" / "files"
    / "grant_application__fabricated_citations.pdf"
)

# Checks that must actually RUN (status ok) on the demo fixture for the demo
# to work. `claims`/`pangram_document` skipping = keys dark on Railway (#115).
# `all_dois_resolve` skipping = reference parsing regressed on PDF (#126).
DEMO_CRITICAL = (
    "has_text",
    "word_count",
    "tagging",
    "citations_linked",
    "citation_identifiers_valid",
    "all_dois_resolve",
    "claims",
    "pangram_document",
)

# Reasoned skips we expect on a single fabricated upload; anything else
# skipping is still a warning, these are just annotated as expected.
EXPECTED_SKIPS = ("similar_documents", "claim_supported", "metadata_match", "all_urls_resolve")

GREEN, YELLOW, RED, DIM, RESET = "\x1b[32m", "\x1b[33m", "\x1b[31m", "\x1b[2m", "\x1b[0m"


def local_roster() -> set[str] | None:
    """Registered check ids in *this checkout*, or None if not importable."""
    try:
        from slopchecker.pipeline import all_checks, discover
    except ImportError:
        return None
    discover()
    return {rc.meta.id for rc in all_checks()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", default="https://slop-checker.com", help="deployment to smoke")
    ap.add_argument("--file", type=Path, default=DEFAULT_FIXTURE, help="fixture to upload")
    ap.add_argument("--timeout", type=float, default=600.0, help="seconds to wait for /check")
    ap.add_argument(
        "--local-api",
        action="store_true",
        help="target serves the FastAPI app directly (no Worker), i.e. /check not /api/check",
    )
    ap.add_argument(
        "--lenient", action="store_true", help="demo-critical skips fail as warnings instead"
    )
    ap.add_argument("--json", action="store_true", help="also dump the raw report.json to stdout")
    args = ap.parse_args()

    prefix = "" if args.local_api else "/api"
    base = args.url.rstrip("/")
    fixture: Path = args.file
    if not fixture.is_file():
        print(f"{RED}FAIL{RESET} fixture not found: {fixture}")
        return 1

    failures: list[str] = []
    warnings: list[str] = []

    with httpx.Client(timeout=args.timeout, follow_redirects=True) as client:
        # 1. health + config: is anything answering, and which keys are set?
        try:
            health = client.get(f"{base}{prefix}/health")
            health.raise_for_status()
            print(f"{GREEN}ok{RESET}   {base}{prefix}/health → {health.json()}")
        except httpx.HTTPError as exc:
            print(f"{RED}FAIL{RESET} health check: {exc}")
            return 1
        try:
            creds = client.get(f"{base}{prefix}/config").json().get("credentials", [])
            unset = [c["env_var"] for c in creds if not c.get("set")]
            print(f"{DIM}     credentials unset on server: {', '.join(unset) or 'none'}{RESET}")
        except httpx.HTTPError:
            warnings.append("/config unreachable (non-fatal)")

        # 2. the real thing: upload the fixture, get report.json back.
        print(f"     uploading {fixture.name} ({fixture.stat().st_size // 1024} KiB) …")
        t0 = time.monotonic()
        try:
            resp = client.post(
                f"{base}{prefix}/check",
                params={"format": "json"},
                files={"file": (fixture.name, fixture.read_bytes(), "application/pdf")},
            )
        except httpx.HTTPError as exc:
            waited = time.monotonic() - t0
            print(f"{RED}FAIL{RESET} /check transport error after {waited:.0f}s: {exc}")
            return 1
        elapsed = time.monotonic() - t0
        if resp.status_code != 200:
            print(f"{RED}FAIL{RESET} /check → HTTP {resp.status_code}: {resp.text[:500]}")
            return 1
        report = resp.json()

    ledger = report.get("ledger", [])
    rows = {row["check"]: row for row in ledger}
    print(f"{GREEN}ok{RESET}   /check → {len(ledger)} ledger rows, "
          f"{len(report.get('findings', []))} findings, "
          f"recommendation={report.get('summary', {}).get('recommendation')!r} ({elapsed:.0f}s)")
    print()

    # 3. per-row audit.
    for row in ledger:
        status = row.get("status", "ok")
        check = row["check"]
        detail = row.get("detail") or row.get("reason") or ""
        if status == "errored":
            print(f"{RED}ERR {RESET} {check:30s} {detail}")
            failures.append(f"{check} errored: {row.get('reason')}")
        elif status == "skipped":
            note = " (expected on single upload)" if check in EXPECTED_SKIPS else ""
            colour = DIM if check in EXPECTED_SKIPS else YELLOW
            print(f"{colour}skip{RESET} {check:30s} {row.get('reason')}{note}")
            if check in DEMO_CRITICAL:
                msg = f"demo-critical check '{check}' skipped: {row.get('reason')}"
                (warnings if args.lenient else failures).append(msg)
            elif check not in EXPECTED_SKIPS:
                warnings.append(f"unexpected skip: {check}: {row.get('reason')}")
        else:
            result = row.get("result")
            print(f"{GREEN}ok  {RESET} {check:30s} result={result!r} {DIM}{detail}{RESET}")

    # 4. roster comparison: deployed ledger vs this checkout's registry.
    roster = local_roster()
    if roster is None:
        warnings.append("slopchecker not importable here — roster comparison skipped")
    else:
        missing = roster - rows.keys()
        if missing:
            msg = (f"registered locally but absent from deployed ledger: {sorted(missing)} "
                   f"(deploy behind your checkout?)")
            # Missing demo-critical checks fail (unless --lenient); others warn.
            critical = any(c in DEMO_CRITICAL for c in missing)
            (failures if critical and not args.lenient else warnings).append(msg)

    print()
    for w in warnings:
        print(f"{YELLOW}warn{RESET} {w}")
    for f in failures:
        print(f"{RED}FAIL{RESET} {f}")
    if args.json:
        print(json.dumps(report, indent=2))

    if failures:
        print(f"\n{RED}NOT demo-ready{RESET} — {len(failures)} failure(s), "
              f"{len(warnings)} warning(s)")
        return 1
    print(f"\n{GREEN}Demo-ready{RESET} — 0 failures, {len(warnings)} warning(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
