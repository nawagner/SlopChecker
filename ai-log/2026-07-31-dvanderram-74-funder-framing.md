# 2026-07-31 — Dominique (claude-code) — #74 landing page: funder framing, trust palette, process graphics

Issue: #74 (landing page + index refinement). Only file touched:
`worker/public/index.html`.

## Why

The page was written for someone who already knew what the tool was. The
audience we actually need to convince is a funder — a program officer who is
not technical and is wary of AI in a review process. Three passes with
Dominique reshaped it around that reader.

## What changed

**Opening.** The annotated specimen was the `h1`, so the page opened on raw
output. To a first-time reader that parses as *us asserting these things about
their proposal* rather than *this is what comes back*. The `h1` is now a plain
sentence, followed by a sub, a primary CTA, and the specimen demoted into a
bordered `<figure>` captioned "What a finding looks like". Marking it visually
as an example is what does the work; the copy alone didn't.

**Ordering.** Was hero → context → uploader → how-to-read → how-it-works.
Now hero → why it exists → how it works → what it checks → how to read a
result → uploader. A hesitant reader reaches the upload box having already been
told what happens to the file and what comes back. Header nav and hero CTA link
to `#check` so a returning user can skip the explanation.

**Context length.** First draft was four paragraphs plus a four-item list
before the fold — too much. Trimmed to two short paragraphs with the rest
behind a `<details>` disclosure. Available on demand, invisible to a skimmer.

**Corrected claims (the substantive fix).** The copy I wrote first — and some
of what was already on the page — overstated what the tool does and
understated what it uses. Wrong in three ways:

- "Nothing is inferred / the checks don't use AI at all" is false. Claim
  extraction (#13), claim-support judgement (#11), similarity (#14), and
  background reports (#18) all involve a model. Replaced with "Two kinds of
  check, kept apart": lookups a human can repeat by hand vs. judgements made
  with a language model, both quote-anchored. For an AI-wary funder the honesty
  *is* the trust move — the claim would collapse the moment they read the repo.
- "It does not judge whether AI was used" is false with Pangram (#12) as a
  headline feature. Now "An AI-detection score is a signal, not a verdict,"
  which keeps the CLAUDE.md framing while naming the detector.
- Scope was too narrow: the page described a citation checker. Added a "What
  it checks" section covering the real feature set from the issue tree —
  citations (#7–#11, all four sub-checks), Pangram (#12), overlap with prior
  submissions and reviewer pool (#13/#14), solicitation compliance (#16) and
  budget (#17), background report (#18), tagging (#15).

**Design — trust palette.** Warm greys out, blue/green/white throughout
(Dominique's brief: those are the colors that read as trustworthy). White
background, blue-tinted hero band, `--panel` `#F2F7FB`, accent deepened to
`#14568F` (7:1 on white), green strengthened to `#1E7A4B` with the pass lane
tinted green. Red kept for failures — semantically necessary — but confined to
findings, never chrome.

**Graphics.** Inline SVG `<symbol>` sprite, `currentColor`, no network
requests: a four-step process diagram for "How it works" with connector rules
on desktop, icons on the six feature cards, and ✗/✓/dial on the result lanes.
Every icon is `aria-hidden` next to a real text label, so the page reads
identically with images off, in a screen reader, or printed (#26).

## Decisions and dead ends

- **Live-vs-planned badges: considered, rejected.** I proposed marking which
  checks run today. Dominique's call was to present the full feature set using
  GitHub as the guide. The honesty valve instead is one line under the feature
  grid — every run reports what ran, what was skipped, and why — which is the
  repo's own "degrade to gaps" principle doing the work.
- **Retention/privacy: deliberately left blank.** A funder's first question
  about uploading an applicant's document is what happens to it. #23 is open,
  so there is no answer to state and I wrote none. When #23 lands, one line in
  the limits list is probably the highest-value addition on the page for this
  audience.
- **Fixed a real dark-mode bug in passing.** Buttons and chip badges hardcoded
  `color: #fff`, so in dark mode — where `--accent`/`--no` invert to light
  tints — white text sat on light fills. Added `--on-accent` / `--on-strong`.
- **Flow connectors are gated to a 4-across layout only.** With `auto-fit` the
  connector on the last item of a wrapped row pointed into empty space; forcing
  4 columns above 52rem and 1 below makes it either a clean row or a clean
  stack.

## Verified

Rendered at 375px, 529px, 1100px, and 1200px, light and dark. All 13 `<use>`
references resolve, one `h1`, no horizontal overflow at 375px, disclosure opens
to the four limits and three glossary terms, upload form and its JS untouched.
The wrapped-highlight rule from the previous #74 commit still holds on the
narrow layouts.

## Left

- Privacy/retention line, once #23 decides it.

### Correction to an earlier claim in this log

I first wrote that only `has_text`, `word_count`, and `tagging` were registered,
so citation checks weren't live. **That was wrong** — a grep artifact. Those
modules register with `id=CHECK_ID` module constants, not string literals, so a
search for `id="..."` missed them. Verified against the live API instead of the
source: eight checks are registered and running — `all_dois_resolve`,
`all_urls_resolve`, `citation_identifiers_valid`, `metadata_match`,
`claim_supported`, `has_text`, `word_count`, `tagging`. (`doi_resolves` in
`registry.py` is a docstring example, not a real registration.)

So #8, #9 and #11 are live. What's actually still missing: quote-in-source
(#10, on Dan's unmerged `danparshall/10-fetchers`), Pangram as a registered
check (#12 — `detect/pangram.py` has no `@register`, and it produces no ledger
row on a live run), similarity (#14), compliance (#16), budget (#17), and
background reports (#18).

### Demo-critical findings from live-API runs (not landing-page bugs)

Ran the #22 fixture corpus through `slop-checker.com/api/check` to generate
real sample reports. Four things surfaced that belong to other people's
modules:

1. **PDF and Markdown uploads skip every citation check** — ledger reason "no
   reference list found in the document". DOCX and HTML detect it fine (9
   identifiers on the same document). Alex flagged the underlying cause on #90
   and #22: the PDF loader does no heading detection, so `sections=0`. A funder
   uploading a PDF — the format they will actually use — currently gets zero
   citation findings. Worth raising against #4/#25 before demo day.
2. **`metadata_match` skips on every fixture** — "no canonical record for any
   of N identifier(s) — outside our metadata providers' coverage". That check is
   the only one that catches the `wrong_paper` defect (real, resolving DOI
   attributed to the wrong paper), so the corpus's most interesting case
   currently passes clean.
3. **`claim_supported` never evaluates** — "no citations with resolved
   references" on every fixture, so `overclaims` isn't caught either.
4. **Real DOIs frequently 403.** On the clean `human` fixture all three DOIs
   came back "blocked or paywalled", so a clean document reports as
   unverifiable rather than as passing.

Net effect for sample cases: of five candidates I generated, only
`grant_application__fabricated_citations` produces a report that demonstrates
the tool working (`all_dois_resolve = false`, 3/9 not found, while
`citation_identifiers_valid = true` at 9/9 well-formed — precisely the "looks
perfect, isn't real" story). The other four show the tool missing their planted
defect. Sample-case selection is parked on Dominique's call rather than shipping
reports that undersell or misrepresent.

### R2 contents (checked, since sample cases were expected there)

The bucket holds 11 objects and is not a case library: `fixtures/proposal_climate.pdf`
(one proposal), `rubrics/synthetic/` (3 RFP/rubric docs, md+pdf — Emerson's #90),
and `unimelb/` (the UniMelb grant-applications CSV dataset + zip). The actual
case variety is in-repo at `tests/fixtures/synthetic/` — 126 documents, 19
rendered cases across 4 formats, with planted defects: fabricated citations (12),
mismatched citations (10), overclaims (11), near-duplicates (6), budget math (3),
budget inflated (3), missing methods (2).
- `demo-report.html` still carries the old warm palette — it will look like a
  different product next to the new landing page. Worth a follow-up pass.
