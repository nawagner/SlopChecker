# STATUS

Append-only. Newest entry on top. One line per entry:
`- HH:MM <name> — did X / next Y / blocked on Z`

## Log

- 15:04 Dominique (claude-code) — evidence report brought onto the #106 palette (#74): `report.css` token values swapped to the ones `index.html` uses (a value swap — `report.css` consumes exactly the twelve tokens the new palette already defines, no rule changes), so the sample report and the landing page stop reading as two different products. Found and fixed the same bug Emerson hit on the landing page, still live here: `.a-id` badges hardcoded `color: #fff` over `--no`/`--yes`/`--score`/`--soft` fills, which invert to light pastels in dark mode — 2.16–2.90:1, now 6.26–8.41:1 via a new `--on-strong`. Every colour in `report.css` now goes through a token. The swap also cleared both light-mode AA failures from my earlier audit (`--soft` on `--panel` 4.32→5.13, `--yes` on `--panel` 4.49→4.94, #26). Dead `data-theme` blocks deleted — #106 dropped them from `index.html`, which settles that open question; zero references left in the repo. Legend copy said "purple = detector score" and `--score` is now indigo, corrected in `html.py`. `demo-report.html` regenerated, not hand-edited. 473 passed / **note for everyone: regenerating needs Python 3.11+ (system 3.9 dies on `zip(strict=True)`) and pytest needs the `similarity` extra or `test_batch_ranks_by_concerns` fails on a missing `datasketch` and looks like a real break** / next: nothing claimed — #20 is Emerson's / blocked on nothing

- 19:14 Nick (claude-code) — #118 PDF tests off the unit critical path. The 11s was two cold headless-Chrome launches, and only one was about rendering: `test_render_pdf_default_sibling_path` started a browser to check that `r.json` -> `r.pdf`, which is our path logic, not Chrome's — and it *skipped* wherever Chrome was absent, so that logic went unverified on exactly the machines most likely to get it wrong. Now stubbed at the `html_to_pdf` seam (render_file still runs for real), plus three more plumbing assertions it enables; the single genuine render is marked `integration`. Unit run of that file 2.77s -> 0.03s locally and ~11s -> 0 on CI; proved no browser starts by running the file with subprocess.Popen/run rigged to raise, and red-greened the stub by breaking with_suffix(). Kept the real render inside the required `test` job rather than a parallel one — trading gate coverage for seconds is the mistake #114's review caught, and the PDF is the shipping artifact / next: PR / blocked on nothing.


- 19:10 Dan (air) — #18 structured lane Phase 1 stacked on the same PR (#127):
  `src/slopchecker/background/` skeleton (extract + structured/base with the
  `RegistryLookup` Protocol for the coming ProPublica/OpenAlex/ORCID clients)
  + rules-first `extract_entities(FlattenedDoc) -> list[Entity]`. Section-
  driven only (`PI` / `PI/Institution` / `Principal Investigator` / `Team` /
  `Personnel` / `Investigators` / `Co-Investigators` / `Submitted by` /
  `Applicant`) — deliberately narrow, no free-text prose extraction; the
  failure mode #18 warns against is exactly guessing at named-person
  claims. Department-marker filter (`Department|School|College|...`) drops
  middle comma-parts so `Dr. Alice, Department of X, Riverbend Inst.`
  yields `affiliation="Riverbend Inst."`, not `"Department of X"`. Every
  Entity carries an Anchor whose quote is a verbatim substring of
  FlattenedDoc.text (same discipline as the rest of the model). 10 new
  tests (single-PI, multi-personnel bullets, no-PI-section → empty,
  blog-post → empty, anchor-in-text, span-matches-quote, id uniqueness,
  determinism, end-to-end on harness/fixtures/proposal_climate.md); full
  suite 462 passed, ruff + mypy clean. Bundled into the Phase 0 PR because
  Phase 1 introduces no new coordination surface (no shared-model change,
  no checks/, no renderer) / next: Phase 2 (ProPublica client, cassette-
  tested) once #127 merges or gets a thumbs-up; still not touching
  checks/ until Phase 4 / blocked on nothing.

- 18:55 Dan (air) — #18 structured lane Phase 0 up on `danparshall/18-structured-lookups`
  (fresh branch off origin/main, not stacked on `danparshall/18-background-report` per
  the split-plan). Added six new types + two StrEnums to `models.py`: `Entity`,
  `BackgroundFinding` (`source_url` structurally required), `EntityNotFound`
  (records the query URL that returned nothing — first-class, distinct from
  a Gap and from silence), `BackgroundGap` (per-entity or whole-registry, with
  a mandatory `reason`), `BackgroundReport` (model validator enforces referential
  integrity across findings/not_found/gaps and rejects `confidence="unverified"`
  findings — the plan's "produced and enumerated; filtered before assembly"
  rule) plus `EntityKind` and `BackgroundConfidence`. Added
  `EvidenceReport.background: BackgroundReport | None = None` — optional +
  default None so `to_report_dict(exclude_none=True)` leaves existing D1
  storage paths untouched (D1 schema tests still green). 19 new tests, full
  suite 450 passed / 9 deselected, ruff + mypy clean. Design comments on #3
  (shape proposal) + #18 (claim + phase order). Common-name disambiguation
  kept as a lookup-site invariant, not a model rule — different registries
  have different "corroboration" fields; documented for the client PRs to
  cover / next: open the Phase 0 PR; then Phase 1 (rules-based entity
  extraction from FlattenedDoc); will flag Nick on #8 before Phase 4 (checks/)
  / blocked on nothing.

- 15:08 Nick (claude-code) — #74 dropped the API status strip from the
  landing page (`API live · v0.1.0 · 2/4 credentialed checks armed`). Two
  problems: the denominator is `len(config.CREDENTIALS)`, which counts
  `CROSSREF_MAILTO` (not a credential — Crossref needs no auth, and
  `checks/net.py` forbids gating DOI resolution on it) and `CANDID_API_KEY`
  (no check uses it yet), so "2/4" undersold a fully-armed pipeline; and
  "armed" is combat framing on a signals-not-verdicts page. Markup, CSS,
  and the `/api/health` → `/api/config` fetch all deleted — 20 lines, no
  other change. `/api/config` still answers server-side for debugging.
  `worker/public/` is Dominique's module, so this is noted on #74. Next:
  nothing / blocked on nothing.

- 19:04 Dan (fable) — #71 post-ingest mutation path landed on `danparshall/71-post-ingest-mutation`: new `harness/post_ingest.py::mutate_ingest_result()` sibling of `injector.inject()` — mutates `FlattenedDoc.text` *after* the loader runs, so recall is measured against text that flowed through the real PDF/DOCX/HTML loader instead of hand-authored markdown. Same discipline as injector (missing-original hard-error, deletion via empty `mutated`, sequential apply, first-occurrence match) plus mechanical span shifting for `references`/`sections`/`page_offsets`: entirely-before → unchanged, entirely-after → shift by delta, mutation entirely inside → extend `.end`, partial overlap → hard-error (recall would be meaningless). `run_harness()` extended: `substrate:` defects → post-ingest path, `file:` defects → existing pre-ingest path, both merge back to the same `per_file_findings` map so `MATCHERS` is unchanged; new `--substrates` CLI flag. Ships one demo defect (`cite-orphan-real-pdf`, `[99]` inserted into `Aim 1:` of a real grant PDF symlinked from `tests/fixtures/synthetic/files/`); manual harness now 4/4 recall (was 3/3). 13 new tests, `test_harness.py` canary updated, full suite 523 green (post-rebase over #14 similarity + #119 KV + #74 landing + #19 PDF reflow), ruff+mypy clean on new code. Item 2 of #71 (Task Exposure paper) is a small follow-up now unblocked via route (b) — compile `.tex` → PDF, symlink into `harness/substrates/`, add defects; no new loader needed. / next: open PR / blocked on nothing.

- 14:53 Nick (claude-code) — #119 shared KV cache landed on
  `nick/119-kv-cache`. Motivation was a comment in `checks_detect.py`: *"no
  `cache_dir` — the server filesystem is ephemeral"* — **Pangram was entirely
  uncached in production**, so every run of the demo doc was a fresh paid call;
  same for lenses. Worker gets the `CACHE` binding and a bearer-gated
  `/api/cache` (`routes/cache.ts`); Python gets `HTTPCache` + `TieredCache`
  (disk L1, KV L2, write-through) in `checks/cache.py`. No Cloudflare API token
  anywhere — same reasoning as the D1 block in `wrangler.toml` (#23/#65), just
  one shared secret. Additive in Dan's modules: optional `cache` field on
  `PangramConfig` / `LensRunConfig`, `cache_dir` untouched. **Derived values
  only** — Pangram responses pass a field whitelist (so a future
  `windows[].text` can't leak), lens quotes are stored as `[start, end]` and
  re-sliced from `doc.text` on read (exact, because a hit means the text hashed
  to the same key); the 1 MiB cap is a privacy guard rail, not a perf one.
  Cache keys are hashed too — which DOIs a proposal cites is information about
  the proposal, and it fixes a real bug where httpx re-normalizes `%2F` to `/`
  so a URL key lost its query string and collided. Every remote failure is a
  miss, never a run failure. 33 new Python tests (492 passed after rebasing on
  #110/#106, ruff clean), 18 new Worker tests (91 passed, tsc clean).
  `docs/kv-cache.md` + PRIVACY.md updated / next: PR, then Nick sets the secret
  on the Worker and Railway — until then it's inert and every run behaves
  exactly as before / blocked on nothing. Heads-up for anyone whose suite is
  erroring on collection: the shared `.venv` was missing two *declared* extras,
  `datasketch` (`[similarity]`, #14) and `python-multipart` (`[web]`) — install
  them and `test_similarity_*` / `test_web` collect fine; nothing was broken.

- 14:41 Dominique (claude-code) — **correction to my 14:02 line**: I said only `has_text`/`word_count`/`tagging` were registered so citation checks weren't live. Wrong — grep artifact, those modules register with `id=CHECK_ID` constants not string literals. Eight checks are live (`all_dois_resolve`, `all_urls_resolve`, `citation_identifiers_valid`, `metadata_match`, `claim_supported`, `has_text`, `word_count`, `tagging`), so #8/#9/#11 have landed; still missing are #10 (Dan's unmerged branch), Pangram-as-a-registered-check (#12 — no `@register` in `detect/pangram.py`, no ledger row on a live run), #14, #16, #17, #18. Verified against the live API, not the source. Also, from running the #22 corpus through `slop-checker.com/api/check` to build sample reports, four things for other owners: (1) **PDF and Markdown uploads skip every citation check** — "no reference list found in the document"; DOCX/HTML find 9 identifiers in the same doc, so the format funders will actually upload yields zero citation findings (#4/#25, root cause is Alex's no-heading-detection note); (2) `metadata_match` skips on every fixture ("outside our metadata providers' coverage") and it's the only check that catches the `wrong_paper` defect, so the corpus's best case passes clean; (3) `claim_supported` never evaluates ("no citations with resolved references") so `overclaims` isn't caught; (4) real DOIs often 403, so the clean `human` fixture reports unverifiable rather than passing. Of 5 candidate sample cases only `grant_application__fabricated_citations` demonstrates the tool working (3/9 DOIs not found while 9/9 well-formed) / next: sample-case selection parked on Dominique's call; #106 open with corrected copy / blocked on nothing
- 14:58 Emerson (claude-code) — reference-entry parsing fixed (#126, filed off a report Emerson was reading: visible References heading, nine DOIs, every DOI check saying "no reference list found"): entry splitter now tolerates rendered list ordinals/bullets before `[n]`, bare numbered entries, a form feed at a page break mid-list, and digit/URL-led lines; heading vocabulary gains sources/citations/endnotes; skip reason distinguishes "no list" from "list found, no entries parseable" (3 call sites in checks/, heads-up @nawagner). Grant application now parses 9 refs in pdf/md/html alike and `all_dois_resolve` returns False with the three planted fabricated DOIs each getting a finding — the demo works / next: PDF presentation polish, then #20 / blocked on nothing

- 14:55 Emerson (fable) — rubric plumbing landed (#90): `CheckContext.rubric` (pre-ingested FlattenedDoc; heads-up @danparshall — one field + registry package entry in pipeline/), `slopcheck run --rubric <path>` (fail-fast on bad path; rubric filename stamps `report.solicitation` when no explicit label), and first consumer `rubric_budget_ceiling` (deterministic: conservative cap-phrase parse of rubric text vs proposal budget-total line, every extraction miss → skipped gap row, never a guess; findings quote-anchor the proposal's total line with exact spans). Ground-truth tests catch both planted budget violations (climate $90k>$75k, edu $97k>$85k) using the committed fixtures. 484 passed, ruff clean / next: web `rubric` upload slot, then spec-drafting bridge to #16 / blocked on nothing

- 18:44 Dan (air) — #30 transcript upload fix landed on
  `danparshall/30-transcript-branch`: SessionEnd's `--push` now targets a
  dedicated `ai-log-uploads` branch instead of the working checkout's
  branch (usually `main`, which mainsaver rejects — hence the silent
  break). Built with git plumbing (`hash-object` + `read-tree` +
  `commit-tree`) so the current HEAD/index/working tree are never touched,
  meaning any session on any branch (main, feature, other worktree) can
  push without stepping on the user's edits or each other. Retries up to
  3× on push race; on persistent failure writes `ai-log/UPLOAD_FAILED.txt`
  with the last error so future breaks are visible even with the hook's
  `2>/dev/null` stderr swallow (fix #2 folded in). Fix #3 (drop the
  `2>/dev/null`) deliberately skipped — separate scope, touches everyone's
  hook UX. 7 new tests over a bare-repo fixture (RED-first: 6 failed under
  old script, Stop-copy passed unchanged); 431 total green, ruff clean /
  next: open PR / blocked on nothing.

- 14:40 Emerson (claude-code) — PDF prose now reflows in the report (#19, second pass): extracted PDF text carries one `\n` per visual line, so even after the page-split fix prose rendered as fragment columns; mid-sentence breaks now render as spaces while headings/`Key: value`/list lines keep hard breaks (NIH R01: 0.97 → 0.6 breaks per 100 chars, remainder is real structure). Trap worth knowing: v1 tested the char immediately before `\n`, which is a *space* on nearly every PDF line — heuristic never fired on real documents while synthetic tests passed / also merged #96 (citations+Pangram registered; live report now 13 ledger rows, real Pangram 1.0 on the fabricated fixture) and #115 (Railway llm extra — claims lens was erroring `ModuleNotFoundError: anthropic` on every live upload) / next: #20 batch summary (claimed, sequenced behind this) / blocked on nothing

- 14:23 Dan (fable) — #14 corpus similarity landed on
  `danparshall/14-similarity`: new `src/slopchecker/similarity/` module
  (shingles + MinHash+LSH index via `datasketch` as `[similarity]` extra +
  union-find clustering + verbatim shared-passage extraction for
  quote-anchored `Anchor`s); registered check `similar_documents` (counts
  near-neighbours at Jaccard ≥ 0.5) and cluster ledger row
  `template_cluster` (only when doc is in a ≥2-doc component) in
  `pipeline/checks_similarity.py`; extended `CheckContext` with
  `batch: Sequence[FlattenedDoc]` + `similarity_index` and added
  `pipeline.build_context(docs, ...)` factory; CLI batch mode restructured
  as two-pass (ingest all → build ctx → run per-doc) so the check sees the
  whole batch. Single-file / bare-ctx callers emit a clean `skipped`
  ledger row. Ownership table gains `similarity/` row. On the current
  fixture corpus: 0 clusters at 0.5 (no true near-dup pairs are planted
  yet — Alex's #94 has them); at 0.3 the shared grant-application
  scaffold over-clusters (33-doc mega-cluster); the check itself fires
  cleanly on planted-pair E2E test (Jaccard 0.60). 251 unit + 9 integration
  passed, ruff clean / next: PR, follow-up issues for local embeddings +
  reviewer-COI + renderer surfacing of cross-doc evidence / blocked on
  nothing.

- 18:32 Nick (claude-code) — #114 CI/test speed. Measured first: the `test` job was 42s, of which `pip install` 11s and `pytest` 20s. That 20s was only 3.9s of CPU — 88% of the "unit" suite was network wait, essentially all of it `tests/test_checks_live.py` (real doi.org/Crossref/OpenAlex/arXiv calls). Dropping that one file took the suite 20.09s → 2.48s with 391 still passing. Fix is the one its own docstring specced: `pytestmark = pytest.mark.live`, deselected via addopts alongside `integration`, and it now runs in its own parallel CI job. Three wins, and the third is the real one — once #43 makes `test` required, a Crossref rate limit would have blocked everyone's merges; as a separate advisory job it reds `live` and nothing else. **Do not add `live` to the `mainsaver` ruleset** (comment says so in ci.yml). Also swapped pip → uv (measured 2.0s vs 18.0s cold, same extras) and added a concurrency group so superseded pushes stop holding runner slots. Coverage: 24 live + 9 integration just aren't on the critical path. **Correction after independent review** — `metadata_match` and `citation_identifiers_valid` were named in NO test outside the live file, so gating it out let a broken borrowed-DOI check (#9's headline) merge with `test` green; added `tests/test_checks_registered.py` (stubbed provider chain, no network, 8 tests) and verified both sabotages now red the default suite (identifiers_valid 40%->97%, metadata_match 29%->84%). Also: "432 tests in CI" was wrong, 428 — test_harness.py module-skips without pyyaml, so `harness`+`similarity` added to CI extras. Deliberately did NOT add pytest-xdist — at 2.5s wall / 2.3s CPU, worker startup would eat the gain; not waiting on the network was the lever. Local `pytest` 20.1s → 2.7s / next: PR, then watch a real run for the uv + cache numbers / blocked on nothing.
  - Side finding, not fixed here: `mypy` in CI is a silent no-op — `src/slopchecker/` has no `py.typed`, so it exits "cannot be type checked" and `continue-on-error: true` masks it. Identical under pip and uv, so it predates this change. Worth its own issue; turning it on will surface real errors and that isn't a speed change.

- 17:54 Dan (fable) — #11 claim-support LLM check landed on `danparshall/11-claim-support`: new `pipeline/claim_support/` subpackage, adversarial verify (judge → mechanical `match_quote` grounding → refuter), registered under `tier="llm"` and off by default. Two invariants each covered by a test: every emitted `Finding` carries a passage the LLM claimed *and* verified against the retrieved source; `supported`/`unverifiable`/low-confidence/refuted/no-passage/unavailable-source all silent (bias hard toward silence, per #11). `Anchor.quote` is the claim sentence from `FlattenedDoc.text` (renderer contract — self-code-review caught me anchoring to the source passage); the LLM's source passage rides in `evidence["source_passage"]`. Cost ceiling = `max_citations_per_doc=20` (2N LLM calls worst-case) + `max_source_chars=30_000` head-truncation. All LLM plumbing (Transport protocol, `_call_with_retry` mirroring pangram, `output_config.format` structured output, prompt assembly) private to the subpackage per #37's design comment. Rebased over #93's fetchers; the check uses the `SourceFetcher` protocol so it picks up `build_default_fetcher()` for free once we wire it in. 20 new tests; full suite 228 passed, ruff+mypy clean / next: open PR, follow-up tickets for 20-pair confusion matrix (AC 2), cross-provider refuter, and wiring real fetchers into the registered wrapper / blocked on nothing.

- 17:29 Dan (fable) — #13 runtime half landed on `danparshall/13-lens-runtime`:
  `pipeline/lens_runtime.py` executes a lens pack against a `FlattenedDoc`
  via a real Anthropic call (client behind an injectable `LLMClient`
  protocol; `AnthropicClient` maps SDK exceptions to typed transport
  errors). Prompt assembly split from the call site (locks in one of
  #37's shape decisions). Strict-JSON parse tolerant of markdown fences,
  then mechanical quote-anchoring — claims whose `quote` isn't a verbatim
  substring of `doc.text` are dropped, not surfaced. Content-hash cache
  keyed on (model, lens.id, doc.text) — cache is opt-in via
  `SLOPCHECK_LENS_CACHE_DIR`; skipped when `ANTHROPIC_API_KEY` unset
  (degrade-to-gaps). `Finding.evidence` carries `{provider, model}` so
  #37's `rung` extension is a one-line schema-free change. Ships the
  registered `claims` check in `pipeline/checks_llm.py` mapping each
  claim → `Finding` per the table in `lenses/claims.md`, plus doc-level
  `claims` (ran/N) and `claims_quant_unsourced` (count) ledger rows.
  29 new tests (205 total green), ruff + mypy clean on new code.
  Deferred to a separate eval ticket: stability diffing + 5-real-proposal
  manual review. / next: open PR / blocked on nothing.
- 14:02 Dan (fable) — #98 CRLF audit on `danparshall/98-crlf-reference-region`
  (PR #105): raced Nick on the references.py legs — his #80 merge landed the
  heading + blank-line-split fixes first (independently converged,
  entry-split fix byte-identical; took main's version in rebase). What #105
  still carries: literal `\n\n` paragraph bounds in intext.py
  `sentence_bounds` (CRLF claim sentences bled across paragraph breaks —
  quote-anchor risk) + 6 tests incl. LF/CRLF extraction parity on all three
  fixture styles, which lock ALL the CRLF behavior down regardless of who
  fixes what; 366 passed / next: merge #105; demo-critical #25 still
  unowned / blocked on nothing.
- 17:39 Dan (fable) — #10 fetchers landed on `danparshall/10-fetchers`: real `SourceFetcher` implementations for arXiv (HTML then PDF-via-pymupdf), PMC-OA (DOI→PMCID→EFetch JATS body), DOAJ (OA gate — indexed DOIs only, then follow `bibjson.link[type=fulltext]`), and plain URL (gray literature); `ChainFetcher` + `build_default_fetcher()` route by `applies_to` with first-hit-wins (arXiv → PMC → DOAJ → URL). Every failure path — 4xx, 5xx, transport error, unparseable JSON, non-OA PMC, missing pymupdf — returns `None` and the check layer maps that to `source_unavailable` (skipped, mandatory reason); an uncheckable quote can never look like a `not_found`. Retries deliberately absent: #37's retry ladder wraps this layer rather than duplicating logic in each fetcher. 30 new tests via `httpx.MockTransport` (suite stays offline). Stayed out of `src/slopchecker/checks/` — Nick's #80 has its own net/cache; consolidation is later work. Full suite: 204 passed, 4 skipped, 9 deselected (integration), 0 failures / next: open PR, wire `build_default_fetcher()` into CLI as a small follow-up / blocked on nothing.
  (Note: this 17:39 entry was dropped from main by an earlier STATUS merge
  resolution — restored here per the append-only rule, corrections get a
  new line rather than silent loss.)
- 13:49 Emerson (claude-code) — first substance checks registered (#7/#12): `citations_linked` (orphan in-text markers, quote-anchored findings) + `pangram_document` (api tier; without PANGRAM_API_KEY it's a skipped gap row and no text leaves the process — #23 gates on setting the key, not on this code); fixed fallout the registration exposed: cli.py report.json now utf-8 (Windows cp1252 corrupted renders), registry-frozen test assumptions pinned with --only, and the local-only dry-run flake root-caused (rich ellipsizing the id column on narrow consoles — column now folds) / next: #20 batch summary view (Emerson claiming) / blocked on nothing

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
- 14:02 Dominique (claude-code) — #74 landing page reframed for funders: plain-language `h1` + CTA with the annotated specimen demoted to a labelled example (opening on raw output read as a claim about the reader's own proposal), long context folded behind a `<details>`, reordered to why → how it works → what it checks → how to read a result → uploader; **corrected copy that overstated the tool** — "the checks don't use AI at all" is false given #11/#13/#14/#18, now "two kinds of check, kept apart" (repeatable lookups vs. model judgements, both quote-anchored), and "we don't judge whether AI was used" is false given #12, now "a score is a signal, not a verdict"; added a "What it checks" section covering the real feature set from the issue tree; blue/green/white trust palette + inline-SVG process diagram and card/lane icons (all `aria-hidden` beside text labels, #26); fixed a dark-mode contrast bug (buttons/badges hardcoded `#fff` over inverted light fills) / next: `demo-report.html` still on the old warm palette and will look like a different product beside the new landing page / blocked on #23 for the privacy-and-retention line a funder will ask for first — deliberately left blank rather than guessed, and note #7–#11 aren't registered as checks yet so an upload today returns `has_text`/`word_count`/`tagging` only.

- 13:45 Nick (claude-code) — did D1 report history + Drizzle Kit schema
  migrations (#88, filed this session): 5 tables mirroring models.py,
  `/api/runs` store+read on the Worker, 72 worker tests + 8 Python schema
  guards, docs/d1-database.md / tests written by three independent agents from
  the contract (each test proved red under a targeted mutation before being
  kept) — caught a real idempotency bug: the replay hash used JSON.stringify,
  which normalizes whitespace but NOT key order, so the same report from a
  different producer created a duplicate run; fixed with a key-sorted
  canonical form / no new secret anywhere — D1 sits behind the
  Worker binding because the REST API would need a Cloudflare token (#23/#65);
  `database_id` is an identifier and a placeholder runs local dev + CI + tests
  / touched Emerson's `worker/src/index.ts` + `wrangler.toml`, flagged on #27
  / next: Nick creates the DB and pastes `database_id`, then
  `npm run db:migrate:remote`; add the `worker` CI job to the mainsaver ruleset
  / blocked on nothing.

- 13:29 Dan (fable) — #81 integration tests landed: `tests/test_integration_e2e.py`,
  9 subprocess-driven tests of the full chain (fabricated PDF → `run` →
  report.json/HTML validating `EvidenceReport` → `render --pdf` → real PDF),
  degrade-to-gaps singles + mixed-folder batch, and a loud-fail browser gate
  (macOS/CI missing-browser = FAILURE, not skip — closes the silent-skip trap
  behind #78); `integration` marker deselected by default (unit run stays ~5s),
  CI gains an explicit `pytest -m integration` step / next: PR review + merge /
  blocked on nothing.

- 13:27 Emerson (claude-code) — PDF text rendering fixed (#19): renderer split paragraphs on `\n\n`, which PDF extraction never emits — a real 120-page NIH R01 rendered as ONE `<p>` wall; now `\f`/blank-line boundaries with offset-exact anchor math, one block per page + `p. N` dividers, pre-wrap line structure / needs a Railway redeploy after merge (Nick) to reach the live site / next: demo scenario #25 / blocked on nothing

- 13:26 Dominique (claude-code) — picked up #74 (landing/index design-copy-UX lane, handed off from Emerson's #27 first pass); audited slop-checker.com and landed the two structural fixes: hero `mark` had a `nowrap`/`normal` pair fighting each other so a wrapped highlight painted its underline once and split mid-phrase (fixed with `box-decoration-break: clone`), and the page had no `h1` at all — the specimen sentence is now the `h1`, computed styles identical. Measured 4 WCAG AA contrast failures on the shared tokens (worst: white-on-`--accent` at 2.50:1 for the primary CTA in dark mode) and found the `data-theme` blocks in `report.css` are dead — nothing sets the attribute; both written up in the ai-log / next: contrast + focus pass across `index.html` and `report.css` together, then a decision on the theme toggle / blocked on nothing

- 13:21 Dan (fable) — #37 design conversation, no code: brainstormed retry-ladder shape, concluded it's post-MVP (Pangram already has an inline loop; no chat-model check exists yet to hit the refusal problem); captured two shape decisions as a comment on #37 (check-invoked `LadderExecutor`, `Finding.evidence["rung"]` for provenance) so the fork is settled when someone picks it up post-#13; also posted correction on #13 resolving a mutual-block loop (Dan's earlier "LLM client lives with #37" was wrong under new scoping); ticket parked / next: return to happy-path work / blocked on nothing.

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
