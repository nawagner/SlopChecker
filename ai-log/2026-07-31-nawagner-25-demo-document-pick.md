# Picking the demo document (#25)

**Issue:** #25 (demo day scenario), touching #123 (reference lists don't parse)
**Landed:** README "Demo document" section, plus two smaller README corrections
**Surface:** claude-code (Opus 5)

## The question

"Look across the R2 bucket and find a good example proposal to demo with."

## What was actually in R2

Listed the bucket directly over the S3 API (boto3, `R2_*` keys from `.env`).
**11 objects, exactly one proposal:**

```
  16840  fixtures/proposal_climate.pdf          <- the only proposal
  6 x    rubrics/synthetic/{aldergrove,hartwell}-*.{md,pdf}
  4 x    unimelb/*.{csv,zip}
```

Matches `docs/data-storage.md` and Dominique's 14:41 STATUS line exactly. R2 is
a file drop, not a case library — the README now says so, because two of us
have now gone looking there for demo material and found nothing.

The actual case library is in-repo: `tests/fixtures/synthetic/` — 18 cases x 4
formats, with `files_index.csv` as ground truth.

## Why the R2 proposal is the wrong pick

Ran `fixtures/proposal_climate.pdf` through the pipeline:

- all four citation checks: `skipped — no reference list found in the document`
- `doc_type_confidence`: **0.4 `blog_post`** (it is a grant proposal)
- `citations_linked`: **false, "0/10 markers linked"** — which is wrong; the
  document does have a References section

So the demo would show a grant proposal labelled a blog post, a fabricated
"no citations linked" finding, and nothing from the citation tier.

## The pick

`tests/fixtures/synthetic/files/grant_application__fabricated_citations.docx`

`citation_identifiers_valid` **true, 9/9 well-formed** while
`all_dois_resolve` **false, 3/9 resolved, 3 not found**. Nine perfectly
formatted DOIs, three of which don't exist — the pitch in one screen, and no
spurious findings alongside it.

## Format is the whole ballgame

Same document, same checks, four formats:

| format | `citation_identifiers_valid` | `all_dois_resolve` |
|---|---|---|
| `.docx` | true — 9/9 | false — 3/9 resolved, 3 not found |
| `.html` | true — 9/9 | false — 3/9 resolved, 3 not found |
| `.md` | skipped | skipped (+ 9 spurious "unlinked citation" findings) |
| `.pdf` | skipped | skipped |

**This adds a row to Emerson's #123 table**, which lists html/md/pdf but not
docx. DOCX behaves like HTML — it is a format where the tier is live. Worth
knowing before demo day, and before anyone "fixes" #123 assuming only HTML
works.

## Dead ends / things not to repeat

- **`wrangler` cannot list R2 objects.** There is no `r2 object list`
  subcommand, and the Cloudflare management API has no object-listing endpoint
  at all — R2 listing is S3-only. `cf` CLI has the same gap (`cf r2 buckets`
  covers buckets, not objects). `cf r2 temporary-credentials create` needs a
  parent access key that doesn't exist. The answer is boto3 + the `R2_*` keys.
- **This worktree's `.env` has the R2 keys but empty `ANTHROPIC_API_KEY` /
  `PANGRAM_API_KEY`**, so `claim_supported`, `claims` and `pangram_document`
  all skip. Those lanes are unverified here.
- **Raw finding counts are not stable.** Two runs of the same file gave 17 and
  18 findings — the difference was entirely whether the Pangram score was
  present (cached vs. missing key). Don't quote a finding count on stage; quote
  the citation numbers, which were identical across every run.
- **Most findings are coverage gaps, not defects.** Of ~18, nine are
  `metadata_match` "could not be checked". Only six are DOI findings.

## Considered and rejected

`pandoc harness/fixtures/proposal_climate.md -o climate.docx` does unlock the
citation tier on the realistic hand-written proposals (13 findings, 3/3
well-formed). Rejected because every DOI in them is a fabricated
`10.9999/fake-*`, so it resolves **0/3** — no real-vs-invented contrast, which
is the whole point. It also emits a spurious `citations_linked` finding
(1/4 linked) that the DOCX fixture doesn't.

## Known weakness of the pick

The fixture's prose is visibly machine-generated — Aims 1, 2 and 3 are the
same sentence three times. On-message (the corpus labels it `slop`) but *so*
obvious that it may undercut "you can't catch this by reading." Not fixed
here; flagged for whoever scripts #25.

## Ownership note

README narrative is Emerson + Dominique's per the ownership table. Edited
rather than asked because it was the explicit request — flagging on #25 rather
than assuming it's fine.

## What's left

- #123 is the demo-critical one: PDF is the format funders actually upload,
  and it currently produces nothing from the citation tier.
- Re-run the pick with real `PANGRAM_API_KEY` / `ANTHROPIC_API_KEY` before
  relying on the detector or claims lanes.
