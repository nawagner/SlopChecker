# Open-web research agent — Implementation Plan

**Goal:** For a submitted proposal, run a Claude-driven research agent
with WebSearch / WebFetch tools that fills gaps left by the structured
lane and produces a short, source-linked brief on the applicant
organization and named personnel — with an explicit
"could-not-verify" output when it can't.

**Originating conversation:** [docs/active/18-background-report/convos/20260731_split_structured_vs_openweb.md](../convos/20260731_split_structured_vs_openweb.md)

**Context:** [#18](https://github.com/nawagner/SlopChecker/issues/18) has
two halves; the structured half is handled by the other plan. This lane
is the "optional open-web research pass" the ticket calls for. It's the
right shape for an agentic loop — search, follow trails, integrate —
but it's also the risky half: it generates natural-language claims
about identifiable people. Grounding discipline (every sentence
carries a source URL, unverifiable claims are dropped, common-name
confusion is caught by affiliation matching) is the whole game.

**Confidence:** Exploratory. This is the first agent-driven check in
the codebase. The grounding rules are settled in principle
(source-per-sentence + affiliation corroboration + explicit
`could_not_verify`); the open question is whether the agent can be
reliably held to them in practice. Plan includes an evaluation gate
before it's exposed in `slopcheck run` on real submissions.

**Architecture:** New `src/slopchecker/background/openweb/` subpackage.
Reuses `AnthropicClient` from `pipeline/lens_runtime.py` (already
handles retries, error mapping, structured output). Tools: WebSearch +
WebFetch (via Anthropic's native tool use), no custom API wrappers —
the structured lane owns those. Input: `FlattenedDoc` and (optionally) a
`BackgroundReport` from the structured lane, so the agent sees what's
already verified and only chases gaps. Output: a `research_brief` in
markdown, plus `BackgroundFinding` rows in the shared shape. A
post-hoc grounding validator drops any sentence whose cited URL
doesn't resolve or whose quote isn't a substring of the fetched page.

**Branch:** `danparshall/18-background-report` (this branch — the
worktree at `.worktrees/dan-18-background-report/`).

**Tech Stack:** Anthropic Python SDK (already in pyproject), `httpx`
for URL validation, `pydantic` for the shape, `pytest` +
`pytest-recording` for cassette-based end-to-end tests. Claude Agent
SDK **not** used — direct API tool use keeps the code shape
consistent with `pipeline/lens_runtime.py`.

---

## Testing plan

The agent is nondeterministic, so the tests target invariants of the
output, not exact strings. Three layers:

- **Invariant tests** on the grounding validator (deterministic code):
  drop sentences without a source URL, drop sentences whose URL 404s,
  drop sentences whose quoted string isn't in the fetched page, drop
  sentences making individual-level claims without affiliation
  corroboration.
- **Cassette-based end-to-end tests** using recorded WebSearch /
  WebFetch tool-call responses replayed through the agent loop. One
  fixture proposal, one recorded run, assert on the resulting brief
  shape and on the invariants (every sentence sourced, no unverified
  claims, `could_not_verify` present when the recorded searches
  returned empty).
- **Adversarial tests** (also cassette-based): a proposal naming
  "Jane Smith" with no affiliation, where recorded WebSearch returns
  three unrelated Jane Smiths. Assert the brief attaches nothing to
  Jane Smith and instead emits a `could_not_verify` block.

Behavior to cover:

- Every sentence in the generated brief has a resolvable `source_url`
  attached. Zero unsourced sentences reach the report.
- Given a fixture proposal from a real, well-documented org, the agent
  produces a brief with ≥3 sourced sentences.
- Given a fixture proposal from a fabricated org that doesn't exist
  online, the brief is empty and the report contains a
  `could_not_verify` block naming the fabricated org.
- Given a proposal that names an individual without affiliation, no
  publication or "prior work" claim is attached to that individual —
  the agent emits a `Gap` instead.
- Given the structured lane already verified the org via ProPublica,
  the agent does not re-do the org check; it works only on the gaps.
  (Verify via a test that asserts the recorded search queries do not
  include the already-verified fields.)
- Given a WebSearch tool call that errors (mocked 500), the agent
  degrades to a partial brief with a coverage-gap row rather than
  aborting.
- Given `--tier` doesn't include `research` (default), the check does
  not run. Given `--tier research` and no `ANTHROPIC_API_KEY`, the
  check emits `skipped: missing ANTHROPIC_API_KEY`.

NOTE: I will write *all* tests before I add any implementation behavior.

---

## Steps

### Phase 0 — Prerequisite

- [ ] Confirm the shared `BackgroundReport` shape has landed on
      `models.py` (either by the structured lane's Phase 0 PR merging
      first, or by adding it here and posting the required comment on
      [#3](https://github.com/nawagner/SlopChecker/issues/3)). Whichever
      lane lands first files that comment; the other rebases.
- [ ] Verify `AnthropicClient` in `src/slopchecker/pipeline/lens_runtime.py`
      supports tool use, or extend it. Read the module end to end
      before adding.

### Phase 1 — Grounding validator (write this first, alone, deterministic)

The validator is what keeps the agent honest. It runs on the agent's
output, not inside the agent loop, so it's fully unit-testable without
network. Every rule below is a test to write before code.

- [ ] Write failing tests for `validate_brief(brief: str, cited_urls:
      dict[str, str], fetched_pages: dict[str, str], entities:
      list[Entity]) -> ValidatedBrief`:
  - drops sentences with no cited URL;
  - drops sentences whose URL is not in `cited_urls` (agent
    hallucinated a link);
  - drops sentences whose citation-quote is not a substring of the
    fetched page (agent fabricated a quote);
  - drops individual-level claims (publication, employment history,
    prior grant) about a person unless the fetched page mentions an
    affiliation matching one of the extracted `Entity` affiliations;
  - preserves organization-level claims without the affiliation rule.
- [ ] Implement `background/openweb/validator.py`. Run tests; green.
- [ ] The validator returns both the surviving brief and a list of
      dropped-sentence records for the coverage-gap section, so we
      never silently drop.

### Phase 2 — Agent loop

- [ ] Write a system prompt spec in `background/openweb/prompts.py`
      that codifies the grounding rules: every sentence must carry a
      URL; every URL must be one the agent fetched; every claim about
      an individual must be corroborated by an affiliation on that
      URL's page; if evidence is thin, output an explicit
      "could not verify" block. Version it — the prompt is going to
      change and we want to know which prompt produced a given brief.
- [ ] Write failing test for `run_openweb_research(doc, structured_report=None,
      client=AnthropicClient()) -> BackgroundReport` using a recorded
      cassette (Anthropic SDK exposes tool-use trace via
      `messages.create` output). The test asserts on the invariants
      above.
- [ ] Implement the agent loop: system prompt from Phase 2 step 1;
      tools = WebSearch + WebFetch; max iterations bounded (e.g. 12
      tool calls, cost ceiling similar to Pangram's).
      Emit the raw model output plus the list of fetched pages so the
      validator has everything it needs. Model output is structured
      JSON per `output_config.format` (the same shape Dan's #11
      claim-support check uses); brief goes into the `brief` field.
- [ ] Pipe the output through `validator.validate_brief`. Emit
      `BackgroundReport` with `findings` (one per surviving sentence),
      `coverage_gaps` (one per dropped sentence and one per
      `could_not_verify`), and `brief_markdown` (the surviving text).

### Phase 3 — Adversarial evaluation gate

Before this feature ships to real submissions, it must survive an
adversarial evaluation batch. This is not optional — it's the check
that answers "does the grounding discipline actually hold."

- [ ] Assemble an evaluation set in `harness/openweb_eval/`:
  - 3 fabricated orgs (from `fixtures/rubrics/` or new synth) that
    don't exist online — expected output: empty brief +
    `could_not_verify`;
  - 3 real, well-documented orgs — expected output: non-empty
    brief, ≥3 sourced sentences per, zero unsourced;
  - 3 common-name personnel (e.g. "James Wilson", "Maria Garcia")
    with weak or missing affiliation — expected output: no
    person-attached findings, `Gap` rows only;
  - 3 real named personnel with strong affiliation — expected
    output: at least one publication finding, with corroborating
    affiliation visible on the source page.
- [ ] Run the eval, record results in `docs/active/18-background-report/results/openweb_eval_v1.md`
      with brief excerpts.
- [ ] Gate: if any of the fabricated / common-name cases produce a
      finding that would be shown to a reviewer, iterate on prompt or
      validator. Do not ship until the gate passes.

### Phase 4 — Integration

- [ ] Register the check under a new `research` tier in the pipeline
      runner. Off by default; opt-in via `--tier research` (or
      `--tier all` if the user opts everything on).
- [ ] Wire the structured `BackgroundReport` (if present in the
      report so far) as input to the agent, so it sees verified facts
      and doesn't re-do them.
- [ ] Add a report-level "Unverified machine-generated research"
      banner rendered any time `brief_markdown` is populated. Static
      copy, always visible, part of the rendered output.

### Phase 5 — Retention & disclosure

- [ ] Update `PRIVACY.md`:
  - Add rows for Anthropic (agent tool use — sends **entity names and
    search queries**, not the submission body — call this out
    explicitly).
  - Add rows for WebSearch / WebFetch. What gets sent: search queries
    derived from extracted entity names; page contents are fetched
    and cached locally for the validator (30-day retention rule).
  - Add explicit line: "Agent transcripts (the model's tool-call
    trace) are **not** retained. Only the validated brief and its
    cited URLs land in the report."
- [ ] Post on #18 asking the team to confirm the retention posture
      before merge. Don't ship until answered.

### Phase 6 — Ship

- [ ] Run the full test suite. All green.
- [ ] `ruff check`, `ruff format --check`, `mypy` clean on new module.
- [ ] Run the eval batch one more time on the final code; results
      still pass the gate.
- [ ] Write `ai-log/<date>-danparshall-18-openweb.md` session log.
- [ ] Push, rebase on origin/main, open PR titled
      `#18 Open-web background research agent (opt-in --tier research)`.
      PR body links this plan doc and the eval results. Do not close
      #18 unless the structured lane has also landed.

---

**Testing Details** Grounding validator is fully unit-testable and
carries the load — every invariant we care about lives there.
Cassette-based end-to-end tests exercise the agent loop against
recorded tool responses (deterministic, offline, fast). Adversarial
evaluation is a manual gate against a fixed set of fabricated /
common-name / real fixtures — the results file gets committed so
regressions on grounding discipline are visible in PRs. All tests
assert on observable output invariants; none inspect internal
prompt-formation code (which is the part we expect to iterate on).

**Implementation Details**

- New subpackage: `src/slopchecker/background/openweb/`.
- Shared shape (`BackgroundReport`) added in Phase 0 or reused if the
  structured lane landed first.
- Agent client: reuse `AnthropicClient` from `pipeline/lens_runtime.py`.
  Extend to support tool use if needed.
- Tools: Anthropic native WebSearch + WebFetch. No custom tools.
- Prompt lives in `background/openweb/prompts.py`, versioned; brief
  carries the prompt version in its metadata.
- Grounding validator is deterministic Python, runs after the agent
  loop; drops any unsourced or unverifiable sentence and records the
  drop in coverage gaps.
- Max iterations bounded (12 tool calls); cost ceiling documented.
- Off by default; runs on `--tier research`; skipped with
  `missing ANTHROPIC_API_KEY` when key unset.
- Report always carries the "unverified machine-generated research"
  banner when the brief is populated.
- Structured-lane output (if present) fed to the agent as prior
  context; agent should not re-query already-verified facts (tested
  as an invariant).
- Agent transcripts never persisted; only the validated brief and
  its cited URLs land in `report.json`.

**What could change**

- **The retention posture.** Punted to the team via a comment on #18.
  If the team says "never retain the brief either," we ship as a
  print-on-review-only feature: brief rendered live in the reviewer's
  UI, never persisted to `report.json`. That's a schema change but
  not a big one.
- **Model choice.** Default should follow whatever `lens_runtime.py`
  uses (currently `claude-opus-5`). If the agent loop turns out to
  need less capability than the claims lens, `claude-haiku-5` may be
  the better cost/quality point — decide after Phase 3 eval.
- **Tool set.** If WebSearch coverage is thin for `.org` /
  gray-literature material, add domain-scoped WebFetch calls to
  registries (LinkedIn is off-limits for TOS reasons; Wikipedia,
  Guidestar, `.edu` faculty pages are candidates). Do not add
  scraped-social-media sources.
- **Grounding validator strictness.** Start strict (drop anything
  ambiguous); loosen only in response to eval failures where the
  agent's actual output was correct but rejected.

**Questions**

- **Do we cache the agent's fetched pages** past the run? The 30-day
  cache retention rule fits; the alternative is per-run purge, which
  costs latency on re-runs of the same proposal. Recommend caching
  under the existing rule, note it in `PRIVACY.md`, get team sign-off
  on the retention comment on #18.
- **Does the brief render to PDF?** Emerson/Dominique own `report/`.
  Coordinate before Phase 4 — the "unverified research" banner
  needs to survive PDF rendering, and long-form markdown is a new
  content shape for the report.
- **Rate limits on WebSearch?** The Anthropic tool has a per-turn
  budget. Confirm before the eval batch; if it's a bottleneck,
  serialize entities rather than fan out.
- **Structured lane's `Entity` extraction is a shared dependency.**
  If it lands with the structured lane, we reuse it (recommended).
  If the structured lane hasn't landed by the time we get to Phase 2,
  we write our own rules-based extractor here and refactor later.
  Prefer to wait a beat if it's close.

---
