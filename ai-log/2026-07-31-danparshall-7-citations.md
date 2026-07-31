# 2026-07-31 — danparshall — #7 citation extraction + #10 matching engine

Session: Dan (+ Fable), branch `danparshall/7-citations`.

## What landed

- `src/slopchecker/pipeline/citations/` (#7): regex+heuristics extraction.
  - `extract_citations(text, ref_region=None) -> CitationExtraction` is the
    entry point; operates on plain flattened text so ingestion (#4) wires in
    later without changes here.
  - Reference parsing: APA, Chicago author-date, numbered/IEEE. Fields:
    authors, year(+suffix), title, venue, DOI, URL, arXiv ID, pages. Raw
    text + Span always exact; parsed fields best-effort.
  - In-text markers: parenthetical author-year (incl. multi-cite `;` lists,
    `p. 14` suffixes, `see`/`e.g.` prefixes), narrative `Smith (2021)`,
    numeric `[14]` / `[3, 4]`. Each mention carries its claim sentence +
    Span (for #11).
  - Linking: numeric key match; author-date by (first-author surname, year,
    suffix). Unlinked markers become report-ready `Finding`s with
    `citation_has_reference: false`, quote-anchored to the claim sentence.
  - Citation types live in the pipeline package, NOT models.py (#3 stays
    untouched); will propose promotion on #3 if other checkers want them.
- `src/slopchecker/pipeline/quotes/` (#10, matching half):
  - `match_quote()`: pat-helper quotecheck port (normalize + offset map,
    exact then difflib fuzzy at 0.85) + ellipsis-spanning in-order fragment
    matching + `[sic]`/editorial-bracket stripping.
  - `check_quotes()`: quoted-passage detection, nearest-citation linking,
    Findings with `quote_in_source` (bool) + `quote_match_score` (float).
    `source_unavailable` => skipped check with reason — never a pass, never
    a plain fail.
  - Retrieval is STUBBED behind `SourceFetcher` protocol: `LocalFileFetcher`
    (tests/demo with pre-downloaded OA text) + `CachingFetcher` (disk cache;
    reports carry only the matched window). Network fetchers = follow-up.

## P/R on the hand-labeled fixture corpus (fabricated docs)

All three docs (APA / Chicago / IEEE), aggregate:
mentions P=1.00 R=1.00 (21 gold), references P=1.00 R=1.00 (12 gold),
links P=1.00 R=1.00 (22 gold incl. unlinked-marker cases).
Caveat: the corpus is small and clean — real PDFs will be uglier. The
numbers say the happy paths work, not that the parser is done.

## Decisions / dead ends

- Footnote-style superscript markers: out of scope for the regex pass —
  they don't survive text flattening reliably. Noted on #7.
- Numeric range markers (`[1]-[3]`) are parsed as two single cites, not
  expanded to include the middle; comma lists (`[3, 4]`) do expand.
- Fuzzy scoring penalizes very short quotes (window padding +10 chars in
  the difflib ratio): a one-word edit in a ~50-char quote can dip to ~0.81.
  Sentence-length quotes behave as validated in pat-helper. Threshold left
  at 0.85.
- `[sic]` is stripped from the quote, not the source — it's the quoter's
  insertion.

## What's left

- #10 retrieval: real arXiv/PMC-OA/DOAJ/URL fetchers behind SourceFetcher.
- LLM fallback for reference entries the regex parser can't handle (#7
  notes) — explicitly out of scope this PR.
- Wire `extract_citations` + `check_quotes` into the runner (#5) once
  ingestion (#4) emits FlattenedDoc.
