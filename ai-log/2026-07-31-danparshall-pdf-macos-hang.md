# 2026-07-31 — danparshall — pdf-macos-hang (e2e smoke session)

Session goal: gap-analysis of open issues vs the team ideation doc, plus an
end-to-end smoke test of the pipeline as a precursor to formal integration
testing. The smoke test found and fixed a real bug; this log covers both.

## What ran

Full chain on a fabricated 1-page proposal PDF (pymupdf-generated, fake
authors/DOI per the fixtures rule):

    slopcheck run fixture.pdf --format json,html   # ingest → checks → reports
    slopcheck render report.json --pdf             # HTML → paginated PDF

Everything upstream of the PDF leg worked first try on the #67 seam
(merged mid-session). The PDF leg was broken on macOS — twice over.

## The bug (report/pdf.py)

1. **`find_browser()` had no macOS candidates.** Chrome/Edge app bundles
   live under `/Applications/...` and are never on PATH, so every Mac got
   `None`. Consequence: both PDF tests **silently skipped** on every Mac
   in the team (`pytest -q` showed "2 skipped" and nobody noticed), and
   `render --pdf` errored out. Demo day artifact is a PDF; all team demo
   laptops are affected.
2. **Chrome ≥132 "new headless" never exits after `--print-to-pdf` on
   macOS.** Verified on Chrome 150.0.7871.187: PDF written at 2.0s, main +
   gpu/utility helpers still parked at 150s. Flags tried and rejected:
   `--disable-crash-reporter/breakpad`, `--disable-component-update`,
   `--disable-background-networking`, `--disable-features=ChromeUpdater`,
   `--virtual-time-budget`, `--timeout`. None make it exit. So even with
   `CHROMIUM` set, the old `subprocess.run(..., timeout=60)` hung the full
   60s and died in `TimeoutExpired`.

## The fix

- `_MACOS_CANDIDATES` (Chrome, Edge, Chromium app-bundle paths) appended
  to the candidate scan.
- `html_to_pdf` no longer trusts the browser to exit: poll for a
  size-stable non-empty PDF (0.25s interval), then reap the browser
  (terminate → wait 5s → kill). Linux happy-path unchanged — there Chrome
  exits first and the poll loop just observes it.
- stderr goes to a **file, not a pipe** — kills the whole
  children-inherit-the-pipe deadlock class (same family as the #49
  crashpad CI fix, which this session's bug rhymed with). Tail of the file
  is included in the error message when no PDF appears.

Evidence: the two formerly-skipped PDF tests now run and pass on macOS in
~4.5s; suite went 136 passed/2 skipped → 156 passed/0 skipped (count grew
mid-session as other lanes merged); `render --pdf` completes in ~2s.

## Dead ends (so you don't repeat them)

- Hunting for a Chrome flag that makes new-headless exit after print on
  macOS. There isn't one as of 150.x. Don't burn time there; artifact-poll
  + reap is the pattern.
- `capture_output=True` with any Chromium-family subprocess is a footgun
  whenever *any* child outlives the main process (crashpad on Linux,
  updater on macOS). File-redirect is strictly safer.

## Also this session (not in this PR)

- Gap analysis of open issues vs the ideation doc — posted in session,
  headline: #8/#9 (deterministic citation tier) are the biggest untouched
  p0s vs the ideation doc's own headline metric; #16 solicitation
  compliance untouched; #37 explicitly NOT a blocker for demo day (its
  consumers degrade to gaps by design).
- Handoff prompt for a fresh agent to build the formal e2e/integration
  harness (see #25/#29 context) — delivered to Dan in-session.

## What's left

- A formal integration test (marked, opt-in) that runs the full
  PDF→report→PDF chain in CI and on dev machines, so this never goes dark
  silently again. Handed off.
- `%PDF-`/`%%EOF` validation instead of size-stability polling was
  considered and skipped (Chrome writes the PDF in one burst post-render);
  revisit only if a truncated PDF ever shows up.
