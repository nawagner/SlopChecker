# 20260731 — Splitting #18 into a structured lane and an open-web lane

**Session:** 2026-07-31, Dan (fable) — ticket-scoping conversation with
Dan (human), no code.

**Issue:** [#18 — Auto-generated background report on the submitting team
and topic](https://github.com/nawagner/SlopChecker/issues/18).

## What #18 asks for

Two things bundled together:

1. **Structured, verified-source lookups** against public registries — ProPublica
   Nonprofit Explorer (Form 990), OpenAlex + ORCID (publications), IRS BMF
   (org existence), Candid (prior grants — has its own ticket, [#21](https://github.com/nawagner/SlopChecker/issues/21)).
2. **An optional open-web research pass** producing a short brief with every
   claim linked to its source.

Plus a load of tightly-drawn design constraints, because this is the one feature
in the tool that generates claims about identifiable people rather than about a
document. Concretely (paraphrased from the ticket):

- Every statement in the brief carries a source link.
- Structured-source lookups work independently of the open-web pass.
- Unverifiable entities produce an explicit "not-found" result, not silence.
- Restrict lookups to the professional/organizational record relevant to the
  application; never infer characteristics not in the cited source.
- Common names are a confusion risk — require corroborating affiliation before
  attaching a publication record to a person.
- Team decision needed on whether briefs get retained after review.

## The split, and why

Dan's opening framing was "this should be easy to do with research agents" —
i.e. point a Claude API instance at WebSearch + WebFetch and let it produce
the brief. That framing is right for **part** of the ticket, and wrong for
the other part:

- **Structured lookups don't want an agent.** ProPublica/OpenAlex/ORCID are
  typed public APIs with well-defined query shapes. A typed Python wrapper
  around each is more predictable, more auditable, faster, cheaper, and
  produces findings whose provenance is a specific API call rather than
  "the model decided to click here." It is also the part where the
  common-name confusion risk lives most sharply — and it is much easier to
  enforce affiliation-corroboration as a code-level invariant than to hope
  the agent honors it in a system prompt.

- **The open-web pass genuinely wants an agent.** The whole point of the
  optional open-web pass is to fill gaps the registries can't — a small
  org that isn't a 501(c)(3), a lead investigator with a body of work
  outside the traditional citation graph. That's search-and-follow-trail
  work, exactly what an agentic loop is built for. Trying to script it
  deterministically produces a much worse tool than trusting a research
  agent with strict grounding rules.

So: two lanes, two plans, two independent PRs.

## Contract between the lanes

Both lanes write into a shared shape defined once:

```
BackgroundReport
  entities: list[Entity]          # extracted from FlattenedDoc
  findings: list[BackgroundFinding]   # every one carries a source URL
  coverage_gaps: list[Gap]        # explicit "we did not / could not check X"
  brief_markdown: str | None      # only populated by the open-web lane
```

Rules the shape enforces (baked into `BackgroundFinding`):

- `source_url: str` is required — no unsourced findings.
- `entity_id: str` is required — every finding attaches to a named entity.
- `confidence: Literal["verified", "probable", "unverified"]` — three-way,
  not free text; `unverified` findings never enter the shipping report.
- Explicit `NotFound` variant when a registry says "no such entity" —
  distinct from "we didn't check."

The open-web lane consumes whatever the structured lane produced (or an
empty `BackgroundReport` if the structured lane hasn't run) so the agent
can see what's already established and only pursue gaps.

## Plans

- **Structured lane** — [plans/01_structured_lane.md](../plans/01_structured_lane.md)
  — available for a fresh agent to pick up. Deterministic, no LLM required.
- **Open-web lane** — [plans/02_openweb_lane.md](../plans/02_openweb_lane.md)
  — Dan (fable) takes this.

Both plans stand on their own — the structured lane can ship first and
be useful; the open-web lane can also ship first and produce a
lower-confidence brief. Ideal is both.

## What's still open

- **Retention policy for the generated brief.** Dan is punting this to
  the team; open on #18 as a discussion item. Interim posture in the
  open-web plan: brief rides `report.json` (inherits PRIVACY.md), agent
  transcripts are not persisted, output is banner-marked
  "unverified machine-generated research."
- **Candid / prior-grants integration.** Owned by [#21](https://github.com/nawagner/SlopChecker/issues/21).
  Neither lane blocks on it; the `BackgroundReport.findings` schema will
  accommodate Candid rows when they arrive.
- **Where the shared shape lives.** Recommendation: extend
  `src/slopchecker/models.py` (per the existing "change a shared model,
  comment on [#3](https://github.com/nawagner/SlopChecker/issues/3)
  first" rule). Whichever lane lands first files that comment.
