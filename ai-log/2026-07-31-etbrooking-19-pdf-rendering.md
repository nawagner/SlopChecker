# 2026-07-31 — etbrooking — #19 PDF text rendering fix

Session: Fable via Claude Code (same session as the web-layer log). Prompted
by Emerson uploading a real 120-page NIH R01 PDF to the live site: the
report rendered as one unreadable wall.

- **Root cause:** the renderer split paragraphs on `\n\n`, which real PDF
  extraction never emits — pymupdf produces one `\n` per visual line and
  `\f` between pages. A 298k-char document had zero `\n\n`, so the whole
  thing rendered as a single `<p>` with line breaks collapsed.
- **Fix:** paragraph boundaries are now `\f` OR blank lines, with offsets
  taken from regex match positions (never split-arithmetic — anchors index
  into the exact flattened text, and the two must not drift). PDFs render
  one block per page with a `p. N` divider. `.doc p` gets
  `white-space: pre-wrap` so the text renders with the line structure the
  checkers actually saw — the flattened text IS the evidence.
- **Verified:** 120 `<p>` blocks + 119 dividers on the real NIH PDF (was:
  1 block, 0 dividers); anchors still land after page breaks (regression
  tests for mixed separators); all 27 report/web tests green.
- **Not ours / expectation note:** "I only see tag findings" is correct
  behavior today — the taggers (#15) are the only registered checks that
  emit findings. Citations/quotes/Pangram engines are on main but not yet
  `@register`'d; that's Dan's registration lane, and reports fatten
  automatically when it lands.
- **Deploy note:** the renderer runs on Railway, which does NOT auto-deploy
  — Nick needs to redeploy after this merges for the live site to pick it up.
