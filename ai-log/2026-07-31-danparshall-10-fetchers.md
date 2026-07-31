# 2026-07-31 — danparshall — #10 real source fetchers

## Issue

`#10` (Citation check: does the quoted text actually appear in the source?).
The matching engine + stub `SourceFetcher` protocol landed in #59; this PR
adds the four real fetchers that were called out as follow-up work in the
final comment there.

## What changed

New subpackage `src/slopchecker/pipeline/quotes/fetchers/`, each fetcher a
`SourceFetcher` implementation plus a static `applies_to(ref)`:

- `arxiv.py` — HTML endpoint (`arxiv.org/html/{id}`) first, PDF fallback
  via pymupdf for older papers with no LaTeX HTML.
- `pmc.py` — NCBI ID Converter (DOI → PMCID) then EFetch JATS XML.
  Non-OA articles have no PMCID (or return metadata-only XML with no
  `<body>`); either path degrades to `source_unavailable`.
- `doaj.py` — DOAJ acts as an OA gate: query `/api/search/articles/doi:X`;
  if indexed, follow the `bibjson.link[type=fulltext]` URL. If not
  indexed, we don't try — that's how we keep off paywalled sites.
- `url.py` — plain HTTP GET for gray literature (blog posts, gov reports).
  Content-type dispatch: HTML → stripped, PDF → pymupdf, `text/*` → raw.
- `chain.py` — `ChainFetcher` + `build_default_fetcher()` — first
  applicable non-None wins, order arXiv → PMC → DOAJ → URL.
- `_http.py` — shared: polite `httpx.Client` factory, HTML-to-text via
  stdlib `html.parser` (drops `<script>`/`<style>`/`<head>`/`<nav>`/…),
  `pdf_to_text` (returns `None` if pymupdf missing), `safe_get`
  (4xx/5xx/transport-error → `None`).

Re-exported from `pipeline/quotes/__init__.py`.

Tests: `tests/test_fetchers.py`, 30 cases, `httpx.MockTransport` for every
network call — suite stays fully offline. Full run: 202 passed, 4 skipped,
0 failures.

## Design decisions

**No retries in this layer.** The `safe_get` primitive is single-shot,
because #37 is the retry-ladder ticket and it's meant to wrap fetchers,
not be baked into each one. Keeps this PR shippable in isolation.

**One `httpx.Client` per chain, injected.** Constructor takes
`client=None` and uses a shared factory. Tests build a `MockTransport`
with a per-URL-prefix routing dict and pass one client to
`build_default_fetcher` — every fetcher in the chain uses it. No global
state, no monkeypatching, no real network.

**`applies_to` + first-hit-wins**, not "try everything." A URL-only ref
never triggers arXiv/PMC/DOAJ requests — proven by
`test_chain_skips_non_applicable_fetchers_entirely` (asserts zero calls
to those handlers). Cheaper and keeps traces clean.

**Failure → `None`, never a raised exception.** Every degradation path
(4xx, 5xx, transport error, unparseable JSON, missing pymupdf, missing
`<body>`) returns `None`. The check layer already maps `None` to
`source_unavailable` (skipped check, mandatory reason). Load-bearing
per #10: an uncheckable quote must never look like a `not_found`.

**HTML extraction is stdlib.** `html.parser.HTMLParser` subclass, ~30
lines. No BeautifulSoup dependency for something this thin. Skips
`{script, style, noscript, head, nav, header, footer, aside}` entirely;
paragraph tags force line breaks. Whitespace collapsed within lines,
paragraph blanks kept.

**pymupdf is optional.** `pdf_to_text` returns `None` if pymupdf isn't
importable, letting a keyless install run everything except the PDF-only
paths. The `[pdf]` extra was already in place for ingest.

## What I deliberately did not touch

`src/slopchecker/checks/` — Nick's PR #80 lives there with its own
`net.py`/`cache.py` for the deterministic tier (DOI resolution etc.). Two
net/cache stacks in flight is fine for the hackathon; consolidating into
one HTTP layer is future work, not a merge-blocker.

## Not addressed here (out of scope for #10)

- Retry ladder (#37): every fetch is single-shot. The `safe_get` seam is
  where a retry wrapper drops in.
- Real E2E integration test that hits arXiv/PMC/DOAJ live: #81's opt-in
  `integration` marker would be the right place.
- `text_to_html_only` fetcher for DOAJ records that only expose an HTML
  landing page with the actual paper text behind JS: for MVP, if the
  landing page's HTML has the body text (as many OA journals do), we
  extract it; if it needs JS, we get `None` and degrade cleanly.
- Rate-limit backoff for the two NCBI endpoints — E-utils asks for
  ≤3 req/sec without an API key; we're single-shot per reference here
  and the caching layer takes repeat load off after the first run.

## Dead ends avoided

None to speak of — the design followed straight from the existing
`SourceFetcher` protocol and the acceptance criteria in #10. First green
on all 30 new tests; only three lint fixes (unused import, two line
lengths) between "wrote tests" and "shipped."

## What's next after this PR

1. Wire `build_default_fetcher()` into the CLI so `slopcheck run` uses
   real fetchers instead of `LocalFileFetcher` (small follow-up).
2. Once #37 lands, wrap `safe_get` with the retry ladder in one place.
3. Consolidate net/cache with Nick's `checks/net.py`/`checks/cache.py`
   after #80 merges — probably a separate ticket.
