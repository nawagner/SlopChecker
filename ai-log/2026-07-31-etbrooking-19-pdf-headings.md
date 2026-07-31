# 2026-07-31 — etbrooking — #19 PDF presentation: heading structure

Session: Fable via Claude Code. Third and last pass on PDF report
presentation (#85 split pages, #122 reflowed prose, this one restores
hierarchy).

- **Problem:** extracted PDF text has no markup at all, so an entire page
  rendered as one undifferentiated block — document title, section headings
  and body prose all at the same weight. The report looked nothing like the
  document a reviewer submitted.
- **Fix:** `_blocks()` splits each page block at heading-shaped lines and
  renders them `<p class="dh">`. A heading is: ≤72 chars, ≤8 words, starts
  with a capital, no terminal sentence punctuation (a trailing colon is
  allowed), not a reference entry / list item / URL, not a `Key: value` form
  field, and not the tail of a sentence wrapped from the line above.
- **Self-disabling guard.** Detection switches off entirely when more than
  25% of lines look like headings — the document is then a form of short
  labelled fields, and bolding a third of it is worse than bolding none.
  Calibrated on measurements, not taste: fabricated grant application 0.21,
  two fabricated RFPs 0.12 / 0.07, real 120-page NIH R01 face page **0.32**.
  Result: 8 headings on the grant application, 15 on the RFP, 0 on the NIH
  form (which degrades to the previous rendering, still reflowed and
  page-split).
- **Two heuristics that had to be separated.** A heading and a wrapped line
  both end mid-air. What distinguishes them is that a wrapped line also
  *starts* mid-sentence — hence the capital-letter rule. Without it,
  "Background\nthe claim appears…" read as a wrap, and with only the wrap
  test, "We will measure … using a" (70 chars, capital) read as a heading;
  the ≤8-word cap kills that one.
- **Offsets:** blocks carry a running cursor over the original text, same
  discipline as pages. A mis-detected heading costs a font weight, never an
  anchor. Regression test covers a mark inside a heading-split block.
- **Verified:** 484 unit + 8 integration green (4 new tests), ruff clean;
  all three documents re-rendered and reviewed in browser.
- **Left:** the reference list still renders as body prose rather than a
  styled bibliography — cosmetic, deliberately not chased.
