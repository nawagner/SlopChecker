# RESEARCH_LOG — 18-background-report

Newest first.

## 2026-07-31 — Split #18 into two lanes

- Convo: [convos/20260731_split_structured_vs_openweb.md](convos/20260731_split_structured_vs_openweb.md)
- Plan (structured lane, available for a fresh agent):
  [plans/01_structured_lane.md](plans/01_structured_lane.md)
- Plan (open-web lane, Dan owns):
  [plans/02_openweb_lane.md](plans/02_openweb_lane.md)

Design fork: ProPublica/OpenAlex/ORCID are typed public APIs — a
deterministic Python client per registry is more auditable, cheaper,
and easier to hold to common-name disambiguation than an agent. The
open-web pass is genuinely agent-shaped and gets its own plan, with
grounding invariants (source-per-sentence, quote verification,
affiliation corroboration) baked in as post-hoc validation code.

Contract between the lanes: both write into a shared `BackgroundReport`
shape defined once on `models.py`. Whichever lane lands first files
the required comment on #3.

Retention decision open — asked on #18 as a team-facing question.
