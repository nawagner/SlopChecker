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
  Loosened to "has_text ran, word_count didn't" — which is what --tier/--skip
  actually promise.

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

## Risk I flagged and Nick accepted

Live-network tests + CI as a required status check on main = a Crossref
outage turns the build red for everyone, not just for this module. The
offline files cover every decision the module makes on its own, so the fix if
it becomes routine is a marker skipping `test_checks_live.py` unless
`SLOPCHECK_LIVE=1`. Noted at the top of that file.

## Left to do

- **Dedup (#14) is not in this PR** — scoped out deliberately; it needs a
  corpus/index seam the CLI doesn't have yet.
- ISBN validity is checked but not *resolved* (no lookup provider for books).
- `--only`/`--skip` ergonomics: four checks now share one reference parse via
  an `lru_cache` on the document text; if ingestion (#4, #58) starts handing
  in huge texts, revisit that cache size.
