# 2026-07-31 — etbrooking — #126 reference-entry parsing

Session: Fable via Claude Code. Emerson spotted it in a rendered report: a
visible **References** heading with nine DOIs, and every DOI/metadata check
reporting "no reference list found in the document."

- **Root cause (three strategies, all defeated).** `_split_entries` tries
  bracketed-key lines, then blank-line-separated paragraphs, then
  one-entry-per-line. The list `1. [1] https://doi.org/...` fails all three:
  the bracket isn't at line start (rendered list ordinal precedes it), there
  are no blank lines, and the per-line fallback only starts an entry on `[`
  or a capital letter. Result: zero entries from a perfectly ordinary
  bibliography.
- **Framing correction (Emerson's, and he was right).** I first filed this
  as a fixture problem (#123) — "the corpus emits non-standard references."
  Wrong: a numbered list of DOIs *is* a reference list. Funders receive
  bibliographies in every shape. A parser that only reads author-title-year
  silently returns "couldn't check" on real submissions, which reads like a
  clean pass. #126 owns the parser; #123 narrowed to "fixture bodies need
  in-text markers."
- **Changes:**
  - entry start accepts an optional list ordinal or bullet before `[n]`
    (`1. [1] `, `- [1] `), and a bare ordinal (`1. `, `1) `) for lists that
    never used brackets. Key still comes from `[n]` when present, so in-text
    `[3]` links to the right entry.
  - leading form feed allowed: PDF page breaks land mid-reference-list and
    were merging two entries into one.
  - per-line fallback also starts an entry on a digit or a bare URL.
  - heading vocabulary gains `sources`/`citations`/`endnotes`/`works
    consulted` (blog posts and think-tank reports rarely say "References").
    Bare `notes` deliberately excluded — the region runs heading-to-end, so a
    false positive swallows the document.
  - skip reason now distinguishes "no reference list found" from "found a
    reference list but could not parse any entries" (touches `checks/refs.py`,
    Nick's module — three call sites pass `doc`).
- **Result on the priority path (grant application, all three formats):**
  references parsed 0 → 9 (pdf), 2 → 9 (md), 9 → 9 (html). With DOI
  resolution live: `all_dois_resolve = False`, "3 / 9 resolved — 3 not
  found", and the three planted fabricated DOIs each get their own finding.
  That is the demo.
- **Not fixed / deliberate:** blog-post and think-tank fixtures still parse
  zero because their `## Sources` lists are bullet-only *and* those documents
  have no in-text markers (#123). Grant application was the priority; stopped
  there rather than chasing the other two doc types.
- **Verified:** 491 unit + 8 integration green, ruff clean.
- **Also this session:** hackathon Anthropic key added to gitignored `.env`
  so the LLM-tier checks run locally. Railway still needs it set by Nick for
  the live site (his access, same as Pangram).
