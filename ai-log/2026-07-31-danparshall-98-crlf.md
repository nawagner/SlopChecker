# 2026-07-31 — danparshall (Fable session) — #98 CRLF reference-region fix

## Issues

- #98 (filed this session): CRLF documents report no reference region.
  Root cause was diagnosed by Nick on #7 during his #80 red-green work and
  handed over; #98 tracks it so #7 stays about Emerson's registry wiring.
- Touches #7 / #8 / #10 indirectly: all three in-flight lanes consume
  `pipeline/citations/` extraction, which this fixes underneath them.

## What changed

- **references.py: nothing, in the end — Nick got there first.** I fixed
  `_HEADING_RE` (`\r?$`) and `_split_entries` (`\n[ \t\r]*\n`) in this
  branch, but his #80 merge landed the same two fixes on main mid-session
  (entry-split byte-identical; heading equivalent, `[ \t\r]*$`). Took main's
  version wholesale in the rebase. The conflict was how we found out —
  two sessions independently converging on the same patterns is decent
  evidence both were the right fixes, and the parity tests below now pin
  them regardless of provenance.
- `intext.py` `sentence_bounds`: literal `rfind("\n\n")`/`find("\n\n")`
  paragraph bounds → `_PARA_BREAK_RE = \n[ \t\r]*\n`. Without it, CRLF claim
  sentences bled across paragraph breaks (e.g. an unpunctuated heading line
  glued onto the claim sentence — worst case for quote-anchored findings).
- `tests/test_citations.py`: 6 new tests — region-found under CRLF, LF/CRLF
  extraction parity across all three fixture styles (references, mentions,
  linking, findings, claim sentences, span grounding in the CRLF text),
  wrapped-entry blank-line split repro, paragraph-clamp repro.

## Decisions

- **Fix the regexes, don't normalize the text.** Normalizing CRLF→LF inside
  extraction would desync every `Span` from the caller's text and break the
  quote-anchor rule (`text[span] == quote`). Offsets must stay grounded in
  whatever text the caller passed. (Normalizing at *ingest* would also be
  defensible, but extraction is called directly by the harness and by #80's
  tests with raw text, so it has to be CRLF-safe regardless.)
- Field parsing needed no changes: `_parse_entry` already normalizes with
  `" ".join(raw.split())`, which eats `\r` along with `\n`.
- Slight LF-side behavior change, deliberate: whitespace-padded "blank"
  lines (`\n  \n`) now count as paragraph breaks in `sentence_bounds`,
  consistent with what `_split_entries` already did. Full suite green.

## Dead ends / notes for the next person

- A reviewer subagent flagged the paragraph-clamp test as "fails under LF
  too" — empirically false (LF clamps correctly; only CRLF bled). Verified
  with a standalone repro before keeping the test. Lesson: a pytest diff
  from a loop over (lf, crlf) variants doesn't tell you which iteration
  failed; check before rescoping a test.
- The reviewer's real catch: the findings span-grounding loop in the parity
  test could pass vacuously if CRLF extraction dropped findings entirely.
  Guarded with a findings-parity assert.

## What's left

- PR open → merge; Emerson (#7 wiring) and Nick (#80) should rebase on it.
- Demo-critical and still unowned: #25 (scripted demo scenario + fallback
  reports + framing paragraph).
