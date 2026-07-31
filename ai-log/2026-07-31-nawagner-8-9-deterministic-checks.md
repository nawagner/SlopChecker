# 2026-07-31 — nawagner — #8 DOI/URL resolution + #9 metadata match

Session: Nick (claude-code), branch `claude/checks-deterministic-tier-xc57l0`.
First code in `src/slopchecker/checks/` — the deterministic tier the registry
(#5) has been scanning for since it landed.

## What landed

`src/slopchecker/checks/`, four registered checks plus their plumbing.

**Checks** (one file, one `@register`, per Dan's convention):

| id | file | network | what it says |
|---|---|---|---|
| `citation_identifiers_valid` | `identifiers_valid.py` | no | DOI/arXiv/ISBN/URL are well-formed |
| `all_dois_resolve` | `doi_resolution.py` | yes | N of M DOIs have a record at doi.org |
| `all_urls_resolve` | `url_resolution.py` | yes | same, for plain reference URLs |
| `metadata_match` | `metadata_match.py` | yes | cited title/author/year/venue vs. canonical |

**Support modules** (register nothing): `identifiers.py` (pure validation),
`cache.py` (disk cache), `net.py` (HTTP + classification), `providers.py`
(Crossref/OpenAlex/arXiv behind one interface), `compare.py` (fuzzy grading),
`refs.py` (shared reference extraction + anchoring), `resolution.py` (the
engine both resolution checks share).

Ledger ids `all_dois_resolve` and `metadata_match` match the ones already in
`mockups/evidence-report-mock.html` / `tests/fixtures/sample_report.json`, so
Emerson's renderer needed no change.

## Decisions made (also posted to #8 and #9)

- **Four outcomes, not two.** `resolves / not_found / blocked / unreachable`,
  and only `not_found` (404/410) flips a ledger row to false. A paywall
  (401/403/429/451) and a timeout are per-item *coverage gaps* — a
  `CheckResult` with `status="skipped"` and a reason, which the renderer
  already draws as a gray chip. We didn't learn the source is missing; we
  learned we couldn't look.
- **A run where nothing answered is `errored`, not "all citations fake."**
  Transport failures are tracked separately from HTTP answers precisely so
  that "we have no network" can never be reported as a document defect. This
  is #8's second acceptance criterion.
- **Malformed ≠ unresolvable.** The offline check owns typos; the network
  checks skip malformed identifiers entirely so one defect never appears
  twice under two names.
- **Metadata: title decides, author/year escalate, venue never decides.**
  Abbreviated venues, initials, dropped subtitles and ±1 year are graded
  *minor* and don't flip the row. Real-DOI-plus-invented-title is what
  `different` is reserved for.
- **A missing canonical record is our gap.** Books and gray literature (i.e.
  much of what a think tank cites) aren't in Crossref/OpenAlex/arXiv. Those
  report "not covered by our metadata providers" and are excluded from the
  match tally rather than counted against the applicant.
- **Reverse lookup distinguishes "wrong DOI" from "no such paper"** (#9's
  key AC): when an identifier has no record we search by title+author
  anyway; a hit ≥0.80 title similarity is reported as *the identifier looks
  wrong*, which is a very different thing to tell a reviewer.
- **Tier is `deterministic`, not `api`**, per CLAUDE.md's ownership table.
  These need no key and no LLM; `needs_network=True` is what gates them.

## Cross-module edits (small, flagged on the issues)

- `pipeline/registry.py`: two optional fields on `CheckContext`
  (`no_cache`, `cache_dir`). Additive, defaults preserve behavior.
- `cli.py`: `--no-cache` and `--cache-dir` on `slopcheck run` (#8 requires
  the escape hatch).
- `tests/test_cli_run.py::test_tier_and_skip_selection` asserted the ledger
  equals `["has_text"]` exactly, so *any* new deterministic check broke it.
  Alex hit the same wall on #15 and loosened it identically; took theirs on
  rebase.

## Observation for #15 (not fixed from here — Alex's module)

Tagging emits findings with `anchor=None` (e.g. `tag-doc-type` at confidence
0.4 with an empty `signals` list). CLAUDE.md says every finding is
quote-anchored, and the renderer has nothing to align an anchorless card
against. Caught because this PR's `test_every_finding_is_quote_anchored`
originally asserted over *all* findings in the report; it's now scoped to
this module's four checks. Worth a look on #15.

## Tests

261 passed. Offline: `test_checks_identifiers.py`, `test_checks_compare.py`,
`test_checks_cache.py`, `test_checks_net.py`. Live network:
`test_checks_live.py` — really calls doi.org, Crossref, OpenAlex, arXiv (Nick's
call; see the risk note below).

Fixture `tests/fixtures/checks/citations-proposal.md` is fabricated (#22 rule)
with seven planted references: one honest, one unregistered DOI, one real DOI
wearing another paper's title, one unresolvable host, one 404 URL, one bad
ISBN checksum, one non-DOI-shaped DOI. Full tier over it: 4.7s cold, and
`--only all_dois_resolve` is 3.6s cold / 0.4s warm off the cache.

## Dead ends / things the next person should know

- **Token-overlap similarity divided by `min()` and it was wrong.** Any title
  whose words were a subset of the canonical's scored a perfect 1.0, so
  "Thermometry of a living cell *nucleus*" matched the paper it merely
  extends. Now Jaccard; truncated subtitles are handled explicitly instead.
  Regression test: `test_a_superset_title_is_not_a_free_match`.
- **Don't split the cited author on a comma.** IEEE style is "G. Kucsko", so
  that yielded a surname of "G. Kucsko" and graded every correct IEEE
  reference in the fixture as sloppy. `citations.first_surname` already
  handles both shapes — use it.
- **doi.org, not the Crossref API, for resolution.** Crossref only knows
  Crossref-registered DOIs; a DataCite DOI is a real DOI and would have
  read as fabricated.
- **Negative results need a sentinel to cache.** `cache.set(key, None)` is
  indistinguishable from a miss, so "no provider has this" re-fetched every
  run. Values are wrapped as `{"record": ...}`.
- Transport errors are deliberately *not* cached — caching "the network was
  down" would poison later runs.
- **arXiv's export API 503s constantly** (5 hand probes: three 503s). It was
  the one provider not going through the retry ladder, so roughly half the
  time an available record read as "no record". `net.get_text` now shares the
  ladder with `get_json`. Found by a flaky live test — which is the argument
  for live tests, and also the argument against them.

## Risk I flagged and Nick accepted

Live-network tests + CI as a required status check on main = a Crossref
outage turns the build red for everyone, not just for this module. The
offline files cover every decision the module makes on its own, so the fix if
it becomes routine is a marker skipping `test_checks_live.py` unless
`SLOPCHECK_LIVE=1`. Noted at the top of that file.

## Second pass: independent spec-derived review (red-green)

Four independent Sonnet subagents were given the #8/#9 acceptance criteria and
CLAUDE.md's invariants — *not* the implementation's reasoning — and asked to
write failing tests for whatever the spec implies. They found eight real
defects in code I'd already called done and tested. All fixed; regression
tests in `tests/test_checks_regressions.py` (25 tests, 17 of which fail
against the pre-fix tree — verified by stashing the fixes and re-running).

Worst first:

1. **Vacuous pass.** `conclusive = resolves + not_found + blocked` meant five
   paywalled DOIs produced `result=True`, "All DOIs resolve", next to a detail
   reading "0 / 5 resolved". One 403 among four network failures was enough to
   suppress the `errored` path entirely. A bot wall is not evidence a citation
   is sound; only `resolves`/`not_found` are conclusive now, and an
   all-blocked batch is a `skipped` gap, an all-unreachable one `errored`.
2. **Anchor spans slid on indented references.** `anchor_for` stripped the
   quote but left `span.start` put, so on any hanging-indent bibliography the
   span kept the leading whitespace and chopped an equal number of characters
   off the end — `text[span] != quote`, breaking the one invariant every
   finding in the module rests on.
3. **A valid ISBN reported as malformed.** ISBNs group with spaces, so the
   scan can't stop at whitespace; a bibliography that doesn't punctuate
   between fields ("…40615-7 2020") swept the year in and reported a 17-digit
   "malformed ISBN". A false positive on an honest citation — the failure
   this project can least afford.
4. **A malformed arXiv id silently rewritten into a real one.** The scanner
   capped the suffix at 5 digits, so `2107.043210` was captured as
   `2107.04321` — a different, real paper. We'd have hidden the defect and
   then reported another author's metadata against the reference.
5. **Coverage gaps cached as fact.** Only `transport_error` was excluded from
   the cache, so a 5xx→`unreachable` was persisted for the 7-day TTL and
   served as settled fact long after the source recovered.
6. **Negated titles graded as clean matches.** "Attention Is Not All You Need"
   vs "Attention Is All You Need" scores 0.93 — one word barely moves any
   ratio on a short title. Asymmetric whole-word negation now caps the title
   grade at `minor` (surfaced for a human, not escalated to a verdict).
7. **Name particles read as a different author.** "Berg" for "van der Berg" —
   how half the world's bibliographies alphabetize — scored 0.5 and, combined
   with a merely-uncertain title, pushed an honest citation all the way to
   "different work entirely".
8. **`ProviderChain` didn't isolate providers.** `MetadataProvider` is a
   public Protocol; a provider raising instead of returning None propagated
   out through the thread pool and killed the check for the whole document.

Lesson worth keeping: my own tests were written alongside the code and
inherited its assumptions. Every one of these came from someone reading the
spec cold. The two guard tests that pass both before and after ("a genuinely
bad ISBN checksum is *still* reported", "'non' must not match inside
'nonlinear'") exist because two of the fixes could easily have over-corrected.

### Found in other people's modules — flagged, not fixed

- **`pipeline/citations/references.py` (#7, Dan):** `_HEADING_RE` ends
  `[ \t]*:?[ \t]*$` under `re.MULTILINE`, and Python's `$` doesn't consume a
  preceding `\r`. A CRLF document — i.e. anything authored on Windows, which
  is a lot of grant proposals — never matches the heading, so
  `find_reference_region` returns None and **all four of my checks report "no
  reference list found"** on a document that plainly has one. High impact,
  one-character fix, but it's their module and their fixture P/R numbers.
- **`checks/tagging.py` (#15, Alex):** registered id is `tagging`, but the
  ledger rows are emitted as `doc_type_confidence`, `submitter_type_confidence`
  and `topic_tags`, so those rows don't trace back to a registry entry the way
  registry.py's contract requires. Also emits findings with `anchor=None`.

## Left to do

- **Dedup (#14) is not in this PR** — scoped out deliberately; it needs a
  corpus/index seam the CLI doesn't have yet.
- ISBN validity is checked but not *resolved* (no lookup provider for books).
- `--only`/`--skip` ergonomics: four checks now share one reference parse via
  an `lru_cache` on the document text; if ingestion (#4, #58) starts handing
  in huge texts, revisit that cache size.
