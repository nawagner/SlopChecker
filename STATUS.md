# STATUS

Append-only. Newest entry on top. One line per entry:
`- HH:MM <name> — did X / next Y / blocked on Z`

## Log

- 13:21 Dan (fable) — #37 design conversation, no code: brainstormed retry-ladder shape, concluded it's post-MVP (Pangram already has an inline loop; no chat-model check exists yet to hit the refusal problem); captured two shape decisions as a comment on #37 (check-invoked `LadderExecutor`, `Finding.evidence["rung"]` for provenance) so the fork is settled when someone picks it up post-#13; ticket parked / next: return to happy-path work (probably #13 or another demo-path item) / blocked on nothing.

- 12:55 Emerson (claude-code) — real web layer landed on `web.py` (#27): `POST /check` = upload → ingest → run_checks → rendered HTML report (`?format=json` for raw report.json); Railway build now installs pdf/docx extras so uploaded PDFs actually ingest in production; frontend surfaces the pipeline's own 422 reason instead of faking "offline" / next: verify live loop on slop-checker.com after Railway deploy, then demo scenario #25 / blocked on nothing

- 12:50 Dan (fable) — #58 done on `danparshall/58-ingest-cli` after #63 landed: deleted the temporary `_load_document` seam + `_TEXT_SUFFIXES`/`UnsupportedFormat`, inlined `ingest.ingest()` in the `run()` loop, mapped `IngestResult.status != "ok"` to the existing degrade path (batch → yellow-skip + row, single-file → red + exit 1), widened the batch-dir filter from `_TEXT_SUFFIXES` to `ingest.LOADERS`; new CLI tests: PDF end-to-end (fabricated via pymupdf), corrupt-PDF, unsupported-suffix (.rst), batch-with-gaps; two existing tests rewritten around a `scratch_registry` fake check (empty-markdown fixture no longer reaches checks — #4 now errors it at ingest, which is the intended shape); 139 passed / 2 skipped locally / next: open PR / blocked on nothing.

- 12:41 Dan (fable) — CORRECTION to 12:32: #6's CLI never reached main — PR #56 was stacked on the #53 branch and, because #53 merged without branch-deletion, GitHub didn't retarget it; the #56 squash landed on `danparshall/5-runner-cli` instead (caught by another of Dan's sessions reading the actual diff — thanks). Re-landing now from `danparshall/6-cli` merged with current main, 126 tests green; #58 stays blocked until it merges / next: verify `slopcheck run` on origin/main after merge / blocked on nothing.
- 12:35 Nick (claude-code) — did create R2 bucket `slopchecker-docs` in the
  Learning Journey AI CF account + mirror the `unimelb_data` Drive folder
  into it (4 files, 5.0 MB, byte-for-byte verified; `.DS_Store` skipped) /
  docs/data-storage.md documents contents + access / next: Nick mints a
  **bucket-scoped** R2 API token in the dashboard and shares it out-of-band
  — deliberately not minted in-session, since transcripts land in a public
  dir / note: the dataset carries applicant-shaped demographic fields
  (birth year, birth country, home language, per-investigator); confirmed
  synthetic, but retention/third-party rules belong in #23 / blocked on
  nothing.

- 12:37 Dan (air) — #12 Pangram integration landed in `src/slopchecker/detect/`: `Detector` protocol + `PangramDetector` behind it; per-window `Finding`s with `Span`s quote-anchored against `FlattenedDoc.text`, doc-level `LedgerRow(check="pangram_document", result=fraction_ai)` in its own visual lane (never a verdict); skipped/errored are first-class ledger rows; 429/5xx retry with exponential backoff, 4xx surfaces immediately; on-disk content-hash cache (opt-in via `cache_dir`); `estimate_cost()` for #6's `--dry-run`. Pangram windows the text itself — we don't chunk. Added `detect/` row to ownership table. 10 new tests, 60 total green, ruff+mypy clean / next: open PR, coordinate with #23 (data-handling review before we send any real applicant text) and #37 (retry-ladder consolidation will replace the local loop) / blocked on nothing.

- 12:32 Dan (fable) — all three lanes landed: #55 ingestion (#4: PDF/DOCX/MD/HTML→FlattenedDoc+sections+ref-region, scanned-PDF→errored), #53+#56 registry/tiered-runner + `slopcheck run` CLI (#5, #6: one-file-one-decorator checks, gap rows for skip/error/timeout, dry-run/batch), #59 citations+quotecheck (#7, #10: APA/Chicago/IEEE extraction P/R=1.0 on small clean fixtures, quote-match engine, retrieval stubbed behind SourceFetcher) / filed #58 (wire CLI seam to ingest — small, high-value), scoping comments on #15/#23/#24 for fresh sessions / next: #29 harness once assigned / blocked on nothing.

- 12:31 Emerson (claude-code) — skipped/errored checks now render as gray coverage-gap chips (#19, Dan's #45 flag): SKIPPED/ERROR + reason in ledger and cards, not-run rows excluded from tallies (they were silently counted as scores), "could not run — reported as coverage gaps, not passes" line in the verdict / next: regenerate demo-report.html from the updated fixture / blocked on nothing

- 12:25 Emerson (claude-code) — slop-checker.com landing page landed (#27): annotated-specimen hero, upload flow with honest sample-report fallback, live API status strip via the Worker proxy; auto-deploys on merge per Nick's Git integration / next: skipped-check chip in the report renderer (Dan's #45 flag), then wire upload to the real pipeline endpoint / blocked on nothing

- 12:14 Dan (fable) — merged the model spine: #45 `models.py` + `docs/DATA_MODEL.md` (#3 — read that doc for the schema + which tests cover what), #46 claims lens + loader (#13), #49 CI fix (PDF tests deadlocked CI on every run since #40: snap chromium hang + crashpad pipe deadlock; test job now ~25s), #44 handle typo; filed #43 (Nick's Claude flipped it — CI is now a required check) / next: three parallel agent lanes in flight — #4 ingestion, #5+#6 runner+CLI, #7+#10 citations — then #29 harness / blocked on nothing.

- 16:05 Nick (claude-code) — did flip `test` on as a required status check
  on main via the `mainsaver` ruleset (#43, last box of #2) — it was a
  ruleset, not classic branch protection, per Dan's hunch / found CI was
  red on main at the time (since #40, Chromium PDF render timing out) so
  the required check blocked every PR briefly — filed #47 with a
  (wrong — see #47's later comments) `/dev/shm` diagnosis; #49 landed the
  real fix (crashpad pipe deadlock) minutes later and #47 is closed / #2's
  last box is genuinely done now: required + green / blocked on nothing.

- 15:31 Dan (claude-code) — added GH-handle → name map to CLAUDE.md, PR #41 (3 of 5 team members named — Alex + Dominique's handles later); also opened #37 (retry ladder + cross-provider failover, pattern from tls-review-shared) / next: continuing tls-review-shared reference review, planning pat-helper harness port for #29 / blocked on nothing.

- 11:39 Nick — did put slop-checker.com live on the Worker (custom domain
  route, already a Cloudflare zone with clean DNS, no registrar step
  needed) / did connect Cloudflare's native Git integration to the existing
  slopchecker-web Worker (root directory worker/, main → production,
  other branches → preview deploys) instead of a bespoke GitHub Actions
  pipeline — avoids ever handling a Cloudflare API token as a secret,
  Cloudflare's GitHub App generates its own scoped token / next: nothing
  blocking, `*.workers.dev` still occasionally 404s per Cloudflare's own
  "shared infra, not for production" guidance — cosmetic, the real domain
  is solid / blocked on nothing.
- 11:20 Emerson (claude-code) — PDF output landed (`slopcheck render --pdf`, headless Chrome/Edge print, no new deps); took over `report/` module ownership (Alex not tracking it — confirmed in person), further iteration hands to Dominique / next: demo scenario #25 / blocked on nothing

- 11:17 Nick — did deploy the Cloudflare Worker for real
  (slopchecker-web.nwagner.workers.dev), proxy to Railway verified on all
  routes / found + fixed a real bug: `/config` reloaded `.env` per-request
  instead of once at startup, which silently defeated a test's monkeypatched
  "key unset" scenario once real keys landed locally / next: Wrangler route
  + slop-checker.com DNS once it's on Cloudflare / blocked on nothing.
- 11:00 Emerson (claude-code) — #19 report.json → HTML renderer landed as `src/slopchecker/report/` + `slopcheck render`, tests green / next: PDF step (Alex), wire to models.py when #3 lands / blocked on nothing
- 10:57 Nick — did first real Railway deploy of the #27 stub, hit a
  Nixpacks/hatchling readme-timing build failure, fixed by dropping
  `readme=` from pyproject.toml / live at
  slopchecker-production.up.railway.app, `/health` + `/config` verified /
  next: Wrangler login (needs a browser, can't run headless) + real secret
  values, both mine to do, not the assistant's / blocked on nothing.
- 10:50 Nick — did Railway deploy target (FastAPI health/config stub) +
  Cloudflare Worker scaffold, PR #34 / did rebase onto module-ownership +
  git-discipline CLAUDE.md update / next real secret values go in via
  `railway variables set`, run directly, not through an AI session / blocked
  on nothing.
