# 2026-07-31 — Dominique — #74 landing page audit + first fixes

Issue: #74 (landing/index design-copy-UX lane, handed off from Emerson's #27
first pass). Touches #26 (accessibility) as scoped by #74.

## What landed in this PR

Two fixes to `worker/public/index.html`, landing page only:

- **Hero mark no longer breaks its own underline.** The CSS had
  `white-space: nowrap` on `.specimen mark` and then, three lines later, a
  second `.specimen mark` rule setting `white-space: normal`. `normal` won,
  so a highlighted phrase could wrap — but the `inset 0 -3px 0` shadow that
  draws the coloured rule painted only once, leaving "does not / exist" split
  with a severed underline at 1280px. Fixed with
  `box-decoration-break: clone` (+ `-webkit-` prefix) so every line fragment
  carries its own background and rule. Verified: the mark reports 2 client
  rects at 1280px and both are painted; no horizontal overflow at 375px.
- **The page now has an `h1`.** It had none — headings started at `h2`. The
  specimen sentence is the page's actual title, so it became
  `<h1 class="specimen">` rather than adding a hidden heading that would give
  screen-reader users different content from sighted users. `.specimen` sets
  `font-size`, `font-weight` and `margin` explicitly, so the computed style is
  unchanged (38.4px / 400 / 0px at 1280px) — a pure semantics change.

## Audit findings NOT fixed here (measured, for whoever picks them up)

Contrast ratios computed from the shared tokens. WCAG AA wants 4.5:1 for
normal-size text:

| Pair | Ratio | Used by | Mode |
|---|---|---|---|
| white on `--accent` | **2.50** | `button.check`, the primary CTA | dark |
| `--soft` on `--panel` | **4.32** | `.lane p`, `.drop p` | light |
| `--yes` on `--panel` | **4.49** | `.lane.l-yes .tag` | light |
| `--rule` on `--bg` | **1.36 / 1.49** | drop-zone border, dividers | both |

The dark-mode CTA at 2.50:1 is the serious one. These tokens are shared with
`src/slopchecker/report/assets/report.css`, so fixing them is one change
across both surfaces plus a `slopcheck render` regeneration — not a
landing-page-only edit. Deliberately left for its own PR.

Also open:

- `:root[data-theme="light"]` / `["dark"]` blocks exist in `report.css` (and
  therefore in the generated `demo-report.html`) but **nothing sets the
  attribute** — no toggle, no JS. Dead CSS. Needs a decision: wire a real
  toggle across both surfaces, or delete the rules. Asked on #74 rather than
  guessing at Emerson's intent.
- The file input at `index.html:158` is hidden with `opacity:0` at 1×1px but
  stays focusable, and `#choose` duplicates its job — keyboard users land on
  an invisible control. Wants a `<label for>`.
- `header nav a:focus-visible` changes `color` only, no outline. Colour alone
  fails 2.4.7.
- `aria-hidden="true"` on `.chips` hides the check IDs and the score from
  assistive tech entirely — the one place they appear, and the product's core
  concept. Defensible as decorative; worth reconsidering.
- No `h1` in `demo-report.html` or `mockups/evidence-report-mock.html` either,
  so that defect is systemic across both surfaces, not just this page.

## Dead ends / notes for the next person

- Don't try to fix the wrap with `nowrap`. That's what the original rule did
  and it's presumably why the `normal` override was added on top of it —
  `nowrap` on "0.96 on an AI detector" at `clamp(1.5rem, 3.4vw, 2.4rem)`
  forces horizontal overflow on narrow viewports. `box-decoration-break` is
  the property that actually addresses this.
- The browser pane times out on `scroll` against the live site; `get_page_text`
  and `javascript_tool` are reliable substitutes for auditing below the fold.
- The framing rules from #74 hold up in the current copy — "signals" not
  detection, the third lane is explicitly "a score, not a verdict", the footer
  states screening-aid-not-determination, and step 2 says skipped checks
  report rather than pass silently. No copy changes needed on that axis.
- Live API strip works end to end: `API live · v0.1.0 · 2/4 credentialed
  checks armed`, so the Worker → Railway proxy is healthy.

## What's left

Per the sequence proposed on #74: contrast + focus pass (index.html and
report.css together, regenerate `demo-report.html`), then the theme-toggle
decision. Boundaries respected — `worker/src/` and `worker/wrangler.toml`
untouched, upload-flow JS wiring unchanged.
