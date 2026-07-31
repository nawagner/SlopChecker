# 2026-07-31 — Dominique — #74 hero: headline, CTA, two-column layout

Issue: #74. Visual pass on the hero, asked for directly: headline should run
further right, the CTA should feel more inviting, and the page was "missing
something" on first view.

## What changed

`worker/public/index.html` only.

- **Headline reworded.** "Check whether a proposal's sources are real, before
  you spend an hour reading it." → "A fabricated citation looks exactly like a
  real one — until someone checks." States the problem the reader actually has
  instead of describing the feature, and "until someone checks" ties straight
  into the CTA. Framing rules hold: no claim to detect AI, no verdict language,
  and the sub still says plainly that it doesn't score or reject.
- **Headline spans the full measure.** It was capped at `max-width: 36rem` and
  rendered ~40% of a 1440px viewport with the whole right side empty. Now
  `grid-column: 1 / -1` at `clamp(2rem, 5vw, 3.5rem)` — 77% at 1440px, 96% at
  1024px.
- **Hero is two columns.** Copy + CTA left, the worked example right. This is
  the "missing something": stacked, the example sat below the fold, so the
  right half of every wide screen was blank *and* the specimen's ink-in
  animation never played on load. It does now.
- **`.wrap` 62rem → 72rem**, matching `report.css`. The landing page and the
  evidence report should hold the same measure.
- **CTA enlarged**: 0.9rem/38px tall → 1.05rem/55px, more padding, 6px radius,
  a two-layer shadow that deepens on hover, and a `→` that nudges right.
  Contrast unchanged at 7.62:1 (AAA).
- **Specimen scale reduced** to `clamp(1.05rem, 1.45vw, 1.2rem)`. It was sized
  for a full-width card; in the narrower column it split "does not / exist"
  mid-phrase. Now the short marks hold on one line each.

## Verified

Measured on the live DOM, not eyeballed:

| width | overflow | hero columns | h1 |
|---|---|---|---|
| 1440 | none | 559 / 505 | 1112px, 77%, 2 lines |
| 1024 | none | 491 / 445 | 984px, 96% |
| 375 | none, 0 offenders | single | 32px |

`prefers-reduced-motion: reduce` disables the button transition and the arrow
nudge. The arrow is `aria-hidden` beside real text. Heading order still starts
at `h1`.

## Traps worth knowing

- **Headless Chrome screenshots lie about mobile.** `--window-size=375,900`
  produced a screenshot that looked badly overflowed, but the live DOM at 375
  reports `bodyScrollWidth === clientWidth` and zero overflowing elements. Old
  headless ignores `<meta viewport>` and lays out wider, then clips. Trust a
  DOM measurement over the image.
- **The in-app browser pane served stale content repeatedly** this session —
  screenshots of a previous version after navigating to a new file, and one
  render at a broken scale. `javascript_tool` measurements were reliable
  throughout; screenshots were not. Headless Chrome
  (`--headless --screenshot`) is a good second opinion for desktop widths.
- STATUS.md is deliberately **not** in this PR. It is the only file everyone
  edits, and including it is what made #134 go `DIRTY` four times. Log line
  goes separately.
