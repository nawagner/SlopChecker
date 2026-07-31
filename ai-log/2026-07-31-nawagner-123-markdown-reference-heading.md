# #123: Markdown ATX headings aren't recognised as bibliography headings

**Issue:** #123 (citation-integrity tier dark on the #22 corpus)
**Landed:** `src/slopchecker/pipeline/citations/references.py`, `tests/test_citations.py`, README correction, STATUS.md
**Surface:** claude-code (Opus 5)

## Context: this issue had already been narrowed twice

Emerson filed #123, then split the actual parser bug into #126 (which Dan
merged) and reframed #123 down to "fixture bodies need in-text markers"
(addressed by Alex in #138, a separate PR). By the time I opened this issue
looking for the next priority, the remaining scope of #123 read as mostly
done. I re-measured before touching anything rather than trusting my own
week-old comment on the issue — good thing, because that comment was stale.

## The correction that mattered before the fix

Earlier today (PR #141, "pick the demo document") I wrote a README table
saying PDF and Markdown both fail citation checks and to demo from DOCX/HTML
only. That was measured on a worktree whose base predated #126's parser fix.
By the time #141 merged, PDF had been fixed for over two hours and the README
was actively telling the team not to demo from a format that worked. Caught it
by re-measuring on current `main` before starting this fix — the table showed
PDF passing, which didn't match what I'd written that morning. Fixed the
README as part of this change; STATUS.md has the correction with the "why."

Lesson: a worktree's base commit is a silent staleness trap when multiple
people are landing fixes on the same day. Re-measure against fresh `main`
before restating a status claim, especially right before demo day.

## The actual bug

Two independent reference-region finders exist and disagree:

- `ingest/util.find_references()` — used by the ingest layer, reads
  `Section.title`, which loaders have already stripped of markup. Finds
  `## References` fine.
- `pipeline/citations/references.find_reference_region()` — used by the
  checks, reads raw `FlattenedDoc.text`. The markdown loader passes text
  through verbatim (comment in `ingest/markdown.py` says so explicitly), so
  the `#`s are still on the heading line. `_HEADING_RE` had no `#` in it, so
  it never matched `## References`, `region_finder` returned `None`, and the
  citation-integrity tier reported `skipped — no reference list found` on
  the `.md` copy of every fixture.

Worse than a coverage gap: `citations_linked` doesn't skip when the region is
missing, it runs, finds zero matched entries, and reports every `[n]` marker
in the (unfound) reference list as an "unlinked in-text citation" — 9 false
findings per document. HTML/DOCX/PDF were unaffected; only Markdown routes
raw ATX-prefixed text into this specific function.

## Fix

One-line-scoped regex change in `_HEADING_RE`: optionally consume a leading
`#{1,6}` marker, and tolerate a trailing `#*` (closing ATX syntax,
`## References ##`, is valid Markdown). Comment added explaining why this
function needs it and the sibling function in `ingest/util.py` doesn't.

## Red-green TDD, with an independent agent writing the test

Per instruction, delegated the test-writing to a separate `general-purpose`
subagent with no visibility into my fix (I stashed the fix as a patch and
reverted `references.py` to unfixed before spawning it). Told it the bug,
the repro, and where the two region-finders live so it wouldn't touch the
working one. It:

- added 8 tests to `tests/test_citations.py` (matching existing style/fixture
  conventions): 5 covering the bug (`## References`, `# Sources`, closing-`##`
  form, entries actually parsing, and an end-to-end `extract_citations` check)
  and 3 regression guards (bare heading and numbered heading still match;
  heading-shaped prose — "sources"/"bibliography" used mid-sentence — still
  does NOT match, since a false positive here swallows the rest of the
  document into the reference region)
- ran them and reported RED: `5 failed, 535 passed`

I independently re-ran the reported-RED tests myself before touching `src/`
— reproduced the same 5 failures, all genuine assertion failures on
`region is None`, not import/collection errors. Then re-applied my saved
patch and confirmed GREEN: `540 passed, 0 failed`, full suite (no regressions
elsewhere).

A background adversarial-review agent (refute-the-fix framing) was spawned
to hunt for false positives, but it died mid-task on the account's monthly
API spend limit — an infrastructure failure, not a review outcome, so its
run produced no findings either way. Ran the same probe directly instead:
16 hand-constructed adversarial strings against `find_reference_region`
(hashtag-shaped lines, `#` in prose, code-fence `# comment` lines,
`## Sources of error` / `## Bibliography of related tools` non-bibliography
headings, CRLF, no-space-after-hash, a heading+numbered-list combo, a
table-of-contents-then-real-heading case exercising the existing
last-match rule, trailing `######`). Zero false positives — the existing
end-anchor (heading keyword must be the last non-punctuation token on the
line) was untouched by this change and still rejects "Sources of error"
etc. for the same reason it always did.

## Verified end-to-end (not just unit tests)

Ran `grant_application__fabricated_citations` through the CLI in all four
formats, before and after. Before: PDF/DOCX/HTML matched (9/9, 3 not found),
MD alone skipped + emitted 9 false findings. After: all four formats produce
the identical result — `citation_identifiers_valid` true/9/9,
`all_dois_resolve` false/3-not-found. Format parity, the demo-critical
property, is real now — not just asserted in a unit test.

## Ownership note

`pipeline/` is Dan's module. Small, scoped, single-regex change with full
test coverage and an independent adversarial review — following CLAUDE.md's
"comment on the issue if stuck" latitude for a hackathon, not asking
permission for an obvious fix, but flagging on #123 so Dan sees it land in
his module.

## What's left

- The adversarial review was done by hand, not by an independent model —
  worth a real second-opinion pass (e.g. `/code-review`) if someone wants
  more assurance before demo day, since the background agent that was
  supposed to provide that didn't run to completion.
- The two-region-finder duplication itself (`ingest/util.find_references()`
  vs `pipeline/citations/references.find_reference_region()`) is a design
  smell worth a follow-up issue — not fixed here, in scope creep territory
  for a one-line bug fix.
