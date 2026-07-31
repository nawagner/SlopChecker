# 2026-07-31 — etbrooking — #19 PDF prose reflow

Session: Fable via Claude Code. Second pass on PDF output quality (the first,
earlier today, fixed the one-`<p>`-wall problem by splitting on `\f`).

- **Problem:** even split into page blocks, extracted PDF text renders with a
  hard break every ~90 characters, because pymupdf emits one `\n` per visual
  line. Prose read like a column of fragments.
- **Fix:** `_soft_joins()` classifies each newline. A break renders as a
  space when the text on both sides reads as one continuing sentence
  (last non-space char lowercase or `,;` AND first non-space char after
  lowercase or an opener). Headings, `Key: value` lines, list items, and
  anything ending in a period keep their hard break.
- **Trailing-space trap:** the first version tested `par[i-1]`, which is a
  *space* on almost every PDF line — the heuristic silently never fired on
  the real document (measured: unchanged break density on the NIH R01). The
  test fixture happened not to have trailing spaces, so tests passed while
  nothing worked. Now looks past trailing/leading whitespace, and a join
  after existing whitespace is dropped rather than doubled (pre-wrap shows
  double spaces).
- **Offset safety:** joins are computed per paragraph and applied inside
  `_display()`, which renders one already-bounded segment. Mark boundaries
  still come from the original offsets, so anchors can't drift; regression
  test covers a quote spanning a soft-joined newline.
- **Verified:** 429 tests green; NIH R01 break density 0.97 → 0.6 per 100
  chars, and the remaining breaks are real structure (tables, headings,
  form fields). Reviewed in browser.
- **Left / not ours:** citation findings over-fire on PDFs because
  `find_reference_region` doesn't detect the bibliography in extracted PDF
  text (noted on #7; related to #90's "PDF loader does no heading
  detection"). That's the pipeline side, Dan's module.
- **Next:** #20 batch summary view (claimed; sequenced behind this).
