# STATUS

Append-only. Newest entry on top. One line per entry:
`- HH:MM <name> — did X / next Y / blocked on Z`

## Log

- 17:39 Dan (fable) — #10 fetchers landed on `danparshall/10-fetchers`: real `SourceFetcher` implementations for arXiv (HTML then PDF-via-pymupdf), PMC-OA (DOI→PMCID→EFetch JATS body), DOAJ (OA gate — indexed DOIs only, then follow `bibjson.link[type=fulltext]`), and plain URL (gray literature); `ChainFetcher` + `build_default_fetcher()` route by `applies_to` with first-hit-wins (arXiv → PMC → DOAJ → URL). Every failure path — 4xx, 5xx, transport error, unparseable JSON, non-OA PMC, missing pymupdf — returns `None` and the check layer maps that to `source_unavailable` (skipped, mandatory reason); an uncheckable quote can never look like a `not_found`. Retries deliberately absent: #37's retry ladder wraps this layer rather than duplicating logic in each fetcher. 30 new tests via `httpx.MockTransport` (suite stays offline). Stayed out of `src/slopchecker/checks/` — Nick's #80 has its own net/cache; consolidation is later work. Full suite: 204 passed, 4 skipped, 9 deselected (integration), 0 failures / next: open PR, wire `build_default_fetcher()` into CLI as a small follow-up / blocked on nothing.

- 13:02 Alex (claude-code) — #22 fixtures: added the `wrong_paper` defect — a
  citation with a real, *resolving* DOI attributed to the wrong paper
  (`metadata_match=false`, new `has_mismatched_citations` ground truth). It's the
  useful one: DOI-resolution alone passes it (naive demo recall 0.0 on it vs 1.0
  on fabricated), only a metadata/quote check catches it → `verdict`
  overstated/unsupported. Corpus + 15×4 rendered files regenerated. Stacked branch
  `alex/22-wrong-paper` on #68 / next: near-dup pairs / blocked on nothing.

- 12:52 Alex (claude-code) — #22 fixtures: rendered a representative subset into
  real files (`.md`/`.html`/`.docx`/`.pdf`, `scripts/synth/render_fixtures.py`,
  12 docs × 4 formats in `tests/fixtures/synthetic/files/`) so ingestion (#4) and
  checks run on actual documents. Round-tripped all four through `ingest()`:
  status=ok, DOIs preserved; PDF keeps text but loses heading structure (0
  sections) — a real gap to test for. PDF is a local browser build step, never
  CI. Stacked branch `alex/22-fixture-files` on top of #54 / next: "valid DOI →
  wrong paper" case / blocked on nothing.

- 13:42 Emerson (fable) — "rubrics" named and scoped as the term for funder reference docs, filed + claimed #90 (arrival/storage/ingest; #16 keeps spec + compliance checks); 3 fabricated rubric fixtures landed in `fixtures/rubrics/` (Aldergrove RFP + scoring rubric pairing proposal_climate, Hartwell RFP pairing proposal_edu; 5 planted, verified compliance violations documented in the README) and mirrored md+pdf to R2 `rubrics/synthetic/`; ingest verified on all six files — md gives full section structure, PDF text layer intact but sections=0 (PDF loader does no heading detection — noted on #90 for the spec-drafting path) / next: `--rubric` CLI plumbing, web slot with #27 / blocked on nothing

- 13:21 Dan (fable) — #37 design conversation, no code: brainstormed retry-ladder shape, concluded it's post-MVP (Pangram already has an inline loop; no chat-model check exists yet to hit the refusal problem); captured two shape decisions as a comment on #37 (check-invoked `LadderExecutor`, `Finding.evidence["rung"]` for provenance) so the fork is settled when someone picks it up post-#13; also posted correction on #13 resolving a mutual-block loop (Dan's earlier "LLM client lives with #37" was wrong under new scoping); ticket parked / next: return to happy-path work / blocked on nothing.

- 13:27 Emerson (claude-code) — PDF text rendering fixed (#19): renderer split paragraphs on `\n\n`, which PDF extraction never emits — a real 120-page NIH R01 rendered as ONE `<p>` wall; now `\f`/blank-line boundaries with offset-exact anchor math, one block per page + `p. N` dividers, pre-wrap line structure / needs a Railway redeploy after merge (Nick) to reach the live site / next: demo scenario #25 / blocked on nothing

- 13:29 Dan (fable) — #81 integration tests landed: `tests/test_integration_e2e.py`,
  9 subprocess-driven tests of the full chain (fabricated PDF → `run` →
  report.json/HTML validating `EvidenceReport` → `render --pdf` → real PDF),
  degrade-to-gaps singles + mixed-folder batch, and a loud-fail browser gate
  (macOS/CI missing-browser = FAILURE, not skip — closes the silent-skip trap
  behind #78); `integration` marker deselected by default (unit run stays ~5s),
  CI gains an explicit `pytest -m integration` step / next: PR review + merge /
  blocked on nothing.

- 13:26 Dominique (claude-code) — picked up #74 (landing/index design-copy-UX lane, handed off from Emerson's #27 first pass); audited slop-checker.com and landed the two structural fixes: hero `mark` had a `nowrap`/`normal` pair fighting each other so a wrapped highlight painted its underline once and split mid-phrase (fixed with `box-decoration-break: clone`), and the page had no `h1` at all — the specimen sentence is now the `h1`, computed styles identical. Measured 4 WCAG AA contrast failures on the shared tokens (worst: white-on-`--accent` at 2.50:1 for the primary CTA in dark mode) and found the `data-theme` blocks in `report.css` are dead — nothing sets the attribute; both written up in the ai-log / next: contrast + focus pass across `index.html` and `report.css` together, then a decision on the theme toggle / blocked on nothing

- 13:20 Dan (fable) — #29 harness landed: pat-helper pattern ported to SlopChecker's data model, MVP corpus of 3 catchable + 2 pending_lens:claims defects, current recall 3/3 on runnable tier, ~0.15s canary test in pytest; direct calls to `extract_citations` / `check_quotes` until #7/#10's registry wiring lands (MATCHERS vocabulary stays either way); DOI-resolution defects deferred to Nick's #8; also filed #71 (post-ingest mutation + Task Exp real-fixture path — the follow-up B path) and landed #72 (Alex → `990991A` in team map) / next: nothing critical, could wire DOI defects once #8 lands / blocked on nothing.

- 13:19 Nick (claude-code) — did diagnose + close out #27's last gap: Railway
  service had no GitHub source connected (`railway status --json` showed
  `"source": null`), so it was only ever deployed via manual `railway up`
  from a stale local checkout — explains why `/check` 404'd 15+ min after
  #70 merged (deployed build predated the route + the pdf/docx extras).
  Nick connected the Railway GitHub App to `nawagner/SlopChecker` in the
  dashboard (OAuth grant, had to be done interactively — not automatable);
  that alone triggered a fresh deploy off current `main`. Verified live:
  `/health` 200, `/check` end-to-end with a real PDF → full report.json
  (`recommendation: human_review`). Railway now auto-deploys `main` same
  as the Cloudflare Worker does / next: nothing outstanding on #27's
  deploy-connection gap; CROSSREF_MAILTO + CANDID_API_KEY still unset
  (pre-existing, non-blocking coverage gap) / blocked on nothing.

- 13:15 Dan (fable) — e2e smoke of the full chain (PDF → `slopcheck run` →
  report.json/HTML → `render --pdf`) works, but found the PDF leg was dark
  on every Mac: `find_browser()` had no macOS paths (PDF tests silently
  skipped) AND Chrome ≥132 new-headless never exits after `--print-to-pdf`
  on macOS (PDF written at 2s, browser parked at 150s+; no flag fixes it).
  Fixed in report/pdf.py: macOS candidates + judge completion by
  size-stable artifact then reap the browser; stderr to file not pipe
  (same deadlock family as #49). 156 passed, 0 skipped / next: handoff for
  formal e2e integration harness / blocked on nothing.
- 18:06 Nick (claude-code) — CORRECTION to 17:52 on the #7 CRLF bug: I called
  it high-impact ("all four checks report no reference list on anything
  authored on Windows") and that was wrong — `ingest.normalize()` strips CRLF
  and all five loaders call it, so the CLI and web paths were never affected;
  verified a CRLF file end-to-end through `ingest()` parses fine. Real defect
  is narrower: `extract_citations()` returns zero references silently for raw
  CRLF text, which is a trap for a direct caller, not a live product bug. I
  checked the loaders after filing rather than before. Fixed it on the #80
  branch anyway with Dan's module in mind — `\r` added to the trailing
  classes in `_HEADING_RE` and the paragraph-split patterns, deliberately NOT
  normalizing inside the parser since that would shift offsets out from under
  the caller's spans; `intext.py` needed nothing; tests in test_citations.py,
  322 green / next: still needs a human to kick CI on #80 / blocked on that.

- 17:52 Nick (claude-code) — ran an independent red-green pass over #8/#9
  before merge: four subagents given only the acceptance criteria + CLAUDE.md
  invariants (not my implementation's reasoning) wrote failing tests from the
  spec. Found 8 real defects in code I'd already called done — worst was a
  **vacuous pass** (five paywalled DOIs → `result=True` "All DOIs resolve"
  beside a detail reading "0 / 5 resolved"; one 403 among four network
  failures suppressed the `errored` path), plus anchor spans sliding on
  indented bibliographies, a valid ISBN reported malformed when a year
  followed it, a malformed arXiv id silently rewritten into a *different real
  paper's* id, coverage gaps cached as fact, negated titles ("…Is Not All You
  Need") grading as clean matches, and "van der Berg" cited as "Berg" reading
  as a different author. All fixed, 25 regression tests (17 verified failing
  pre-fix), 320 green / two cross-module bugs flagged not fixed: #7's
  `_HEADING_RE` misses CRLF documents so all four of my checks report "no
  reference list" on anything authored on Windows; #15's tagging emits ledger
  rows whose `check` ids aren't its registered id / next: PR #80 has no CI run
  at all — agent-pushed branches don't seem to trigger it, needs a human kick
  before the required `test` check can pass / blocked on that.

- 17:05 Nick (claude-code) — did the deterministic tier, first code in
  `src/slopchecker/checks/` (#8 + #9): four registered checks —
  `citation_identifiers_valid` (offline: DOI/arXiv/ISBN/URL well-formedness),
  `all_dois_resolve` (doi.org, all registries not just Crossref),
  `all_urls_resolve`, `metadata_match` (Crossref → OpenAlex → arXiv behind one
  interface, fuzzy title/author/year/venue grading, reverse title lookup that
  separates "wrong DOI" from "no such paper") / key call: only a 404/410 flips
  a row false — paywalls, timeouts and 5xx are per-item coverage gaps, and a
  run where nothing answered is `errored`, never "the citations are fake" /
  ledger ids match the mock so Emerson's renderer needed no change / small
  cross-module edits flagged on #8: `--no-cache`/`--cache-dir` on
  `slopcheck run` plus two optional `CheckContext` fields (Alex's #15 had
  already loosened the over-specified CLI ledger assertion we both hit —
  took theirs on rebase) / 261 tests green; `test_checks_live.py` really hits
  doi.org/Crossref/OpenAlex/arXiv per Nick's call — flagging that a provider
  outage can redden required CI for everyone, escape hatch documented in the
  file / next: dedup (#14) is deliberately NOT in this PR / blocked on nothing.

- 13:08 Nick — did mint a bucket-scoped R2 API token for `slopchecker-docs`
  (Object Read & Write, scoped to that bucket only, not account-wide) and
  shared it with the team via secure DM / access to shared data storage is
  now live, see docs/data-storage.md for setup / next: nothing / blocked
  on nothing.

- 13:08 Emerson (claude-code) — landing page + index refinement handed to Dominique as #74 (scoped: `worker/public/` statics only; `worker/src/` + deploy config stay with Emerson under #27, which a parallel session is actively working); ownership table updated / next: Dominique picks up #74 / blocked on nothing

- 12:55 Emerson (claude-code) — real web layer landed on `web.py` (#27): `POST /check` = upload → ingest → run_checks → rendered HTML report (`?format=json` for raw report.json); Railway build now installs pdf/docx extras so uploaded PDFs actually ingest in production; frontend surfaces the pipeline's own 422 reason instead of faking "offline" / next: verify live loop on slop-checker.com after Railway deploy, then demo scenario #25 / blocked on nothing

- 12:52 Alex (claude-code) — tagging check landed on branch for PR (#15): pure `detect_doc_type`/`infer_submitter_type`/`tag_topics` + one registered deterministic check, no LLM/no network. Categorical tags ride in quote-anchored `Finding.evidence` (LedgerRow.result is bool|int|float only — no model change to #3); rollups (doc-type conf, submitter conf, topic count) go to the ledger. Configurable taxonomy via stdlib `tomllib` + `$SLOPCHECKER_TAXONOMY` (see taxonomy.example.toml); default is a Python literal so no packaged-data-file risk. `detect_doc_type` is the `applies_to` seam for doc-type-driven check selection. Seeded `src/slopchecker/checks/` (Nick's pkg per ownership table — heads-up on #15). Fixed an over-specified assertion in test_cli_run.py that pinned the exact deterministic ledger. Full suite green (137 passed) / next: merge once reviewed; #29 harness can consume these tags as ground truth / blocked on nothing.

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

- 12:19 Alex (claude-code) — #22 fixtures: added a `document_type` dimension to
  the synth generator — blog posts + think-tank reports alongside grant
  applications, with type-gated defects (budget/methods stay grant-only).
  Regenerated the committed corpus (120 docs, all 3 types). On a stacked branch
  `alex/22-fixtures-doctypes` (draft PR on top of #48) / next: PDF/DOCX rendering
  + the "valid DOI → wrong paper" case / blocked on nothing (schema Q still open
  on #22 for #3 owner).

- 12:02 Alex (claude-code) — #22 synthetic proposal fixtures: dimension-covered
  generator (`scripts/synth/synth_proposals.py`, template + anthropic backends,
  tier-stratified NIH pulls) + eval harness (`score.py`) + committed 60-doc
  `--offline` corpus in `tests/fixtures/synthetic/`; draft PR up. Finding: naive
  checks score ~1.0 on templates but drop to 0.0 recall on model-backed slop /
  next: doc-type coverage (blog/report), PDF/DOCX rendering / blocked on the
  report.json schema question left on #22 (for #3 owner).

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
