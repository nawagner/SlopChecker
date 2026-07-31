## Synthetic rubric fixtures

This directory holds fabricated funder-side reference documents
("rubrics" in SlopChecker terminology: RFP/solicitation text and
evaluation criteria that a submitted proposal is checked against). They
pair with the fabricated proposals in `harness/fixtures/` to exercise
SlopChecker's compliance-checking layer against both a proposal
document and the funder document it should be evaluated against.

## Fabricated-fixtures rule (repo policy #22)

Everything in this directory is entirely invented: funder organizations,
program officers, addresses, program history, solicitation numbers,
scoring rubrics. Every file carries a `FABRICATED DOCUMENT — TEST
FIXTURE` banner at the top. No real foundation, real person, or real
applicant material appears anywhere here, and none should be added later
— see `CLAUDE.md` and issue #22 for the full rule. All URLs and email
domains use `.example` per RFC 2606.

## Files

| File | What it is |
|---|---|
| `aldergrove-community-climate-rfp.md` | Full RFP from the fictional "Aldergrove Resilience Fund," Community Climate Adaptation Grants program. |
| `aldergrove-evaluation-rubric.md` | Weighted scoring rubric companion to the Aldergrove RFP — table-heavy, exercises a different document shape in the ingest layer than prose-style RFPs. |
| `hartwell-education-innovation-rfp.md` | Shorter RFP from the fictional "Hartwell Foundation," Education Innovation Grants program. Deliberately different structure/voice from Aldergrove (numbered `## 1. Purpose`-style sections, word limits instead of page limits, different attachment set) so the fixture set covers more than one funder-document shape. |
| `README.md` | This file. |

## Pairing map

| Rubric | Pairs with proposal | Proposal path |
|---|---|---|
| `aldergrove-community-climate-rfp.md` + `aldergrove-evaluation-rubric.md` | Heat-vulnerability mapping proposal | `harness/fixtures/proposal_climate.md` |
| `hartwell-education-innovation-rfp.md` | Fraction-reasoning intervention proposal | `harness/fixtures/proposal_edu.md` |

## Planted compliance violations

These are intentional, mechanically-checkable mismatches between each
rubric and its paired proposal, planted for compliance-check testing.
Each is verifiable by reading the paired proposal — none require
judgment calls.

### Aldergrove RFP vs. `proposal_climate.md`

1. **Missing required section — Data Management Plan.** The Aldergrove
   RFP's "Required Proposal Sections" list mandates a `## Data
   Management Plan` heading (item 7). `proposal_climate.md` has no such
   section; its headings run Title, PI/Institution, Abstract, Aims,
   Background & Prior Work, Approach, Budget, References — no Data
   Management Plan anywhere.
2. **Missing required attachment — Letters of Institutional
   Commitment.** The RFP requires a signed commitment letter from each
   named municipal or community partner. `proposal_climate.md` names
   three unnamed "participating cities in the mid-Atlantic region" in
   its Abstract and Approach but includes no letters of commitment, and
   in fact never names the partner cities specifically enough to
   identify who would have signed one.
3. **Budget exceeds the award ceiling.** The RFP caps awards at
   **$75,000** total per project ("Award Size and Period"). The
   proposal's budget table totals **$90,000** — $15,000 over the stated
   ceiling.

### Hartwell RFP vs. `proposal_edu.md`

1. **Missing required attachment — IRB Approval Letter or
   Exempt-Determination Letter.** The Hartwell RFP requires this
   attachment for any project collecting data from students or
   classrooms (Section 7). `proposal_edu.md` describes pre/post
   assessment of Grade 4-5 students across twelve classrooms — squarely
   inside that requirement — but includes no IRB or human-subjects
   material anywhere in the document.
2. **Budget exceeds the award ceiling.** The Hartwell RFP caps awards at
   **$85,000** total (Section 4). The proposal's budget table totals
   **$97,000** — $12,000 over the stated ceiling.

## Shared mirror

These files are also mirrored to the shared R2 bucket at
`slopchecker-docs/rubrics/synthetic/` alongside the rest of the team's
shared document corpus. See `docs/data-storage.md` for the bucket layout
and sync details; this directory in the repo is the source of truth,
the R2 copy is a mirror for teammates who want the files without a
local clone.
