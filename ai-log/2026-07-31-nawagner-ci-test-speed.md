# 2026-07-31 — nawagner (claude-code) — CI/test speed

Issue: #114 (filed this session)

## The question

"Is there any way to make the CI tests go faster so we can increase dev
velocity?"

## What I measured before changing anything

CI wall clock across the last 25 runs was 30–90s, so CI was not slow in
absolute terms. Worth saying plainly, because the instinct at that number is
to reach for parallelism, and parallelism was the wrong lever.

Per-step timing, run 30654679072, `test` job (42s):

| Step | Time |
|---|---|
| `pip install -e ".[web,dev,pdf,docx]"` | 11s |
| `ruff check` + `ruff format --check` | 1s |
| `pytest` | 20s |
| `pytest -m integration` | 4s |
| `mypy` | 0s |

`worker` (20s) runs in parallel — not the critical path, left alone.

## The finding that mattered

Locally the default suite was **20.09s wall clock but 3.9s of CPU**. That gap
is the whole story: the suite was not computing, it was waiting. `--durations`
put ~17s of it in one file, `tests/test_checks_live.py`, which really calls
doi.org, Crossref, OpenAlex and arXiv.

Deleting that file from the run: **20.09s → 2.48s**, 391 tests still passing.

The live tests are deliberate and good — a mocked resolver agrees with our
idea of the outside world instead of the real one, which is the entire point
of the deterministic tier. They should keep running. They just should not sit
in the loop a developer hits dozens of times an hour.

The file's own docstring had already specced the fix and I took it nearly
verbatim, only preferring a marker over the `SLOPCHECK_LIVE=1` env var it
suggested, so it matches how `test_integration_e2e.py` already handles
`integration` (one mechanism, not two).

## What landed

1. **`pytestmark = pytest.mark.live`** on `tests/test_checks_live.py`;
   `addopts = "-m 'not integration and not live'"`; marker registered.
2. **Own CI job** (`live`), parallel with `test`, running `pytest -m live`.
3. **pip → uv** — measured 2.0s vs 18.0s cold on the same extras.
4. **`concurrency:` group** with cancel-in-progress everywhere except main.

## Why a separate job, not just a separate step

A separate *step* in `test` would have fixed the local loop but saved no CI
wall clock, and would have left the important problem in place. #43 is about
to make `test` a required check. Live tests inside a required check means a
Crossref rate limit or a doi.org blip blocks every merge on the repo. As its
own advisory job, an outage reds `live` and nothing else.

There is a comment in `ci.yml` saying so, because the failure mode here is
someone helpfully adding `live` to the `mainsaver` ruleset later and
reintroducing exactly the problem this removed.

## Results

- Local default `pytest`: **20.1s → 2.7s**
- CI `test` job: 42s → **35s** (uv 11s → 2s landed; see the PDF caveat below)

## What independent review caught — and why it changed the PR

I asked a separate agent to try to falsify this work rather than confirm it.
It confirmed the mechanism (no vacuous pass, clean three-way partition, no
network in the default run, timings reproduce) and **refuted the coverage
claim**, which was load-bearing:

`metadata_match` and `citation_identifiers_valid` were named in **no test
outside `test_checks_live.py`**. Gating that file out of `test` meant a real
regression merged green:

- neuter the borrowed-DOI comparison (#9's headline capability) → `pytest`
  green, only the advisory `live` job red
- stop reporting malformed identifiers → same

That is the exact shape a regression hides in: an advisory job reviewers are
told to expect red from third-party flakiness. And the PR's own argument for
keeping `live` advisory *rested* on that false premise.

Fix: `tests/test_checks_registered.py` drives both registered checks against a
stubbed `ProviderChain`, no network, 8 tests in 0.2s. Verified by replaying
both sabotages — each now reds the default suite. Coverage of
`checks/identifiers_valid.py` 40% → 97% and `checks/metadata_match.py` 29% →
84%, matching what live was contributing. The residual (`providers.py`,
`net.py`) is genuinely about the outside world, which is live's job.

Two smaller corrections from the same review:

- "all 432 tests run in CI" was wrong — **428 do**. `tests/test_harness.py`
  module-skips on `importorskip("yaml")` and no CI job installed the `harness`
  extra, so its 4 tests ran nowhere. Added `harness` (and `similarity`) to the
  CI extras.
- `pytest` returns exit 5 on zero-collected, so the mistyped-marker case I
  worried about is fail-safe. The residual is a marker plus a blanket
  `skipif` — collected but all skipped exits 0. Noted, not hit here.

## Dead ends / deliberate non-goals

- **pytest-xdist.** The reflexive fix, and wrong here. Post-gating the suite
  is 2.5s wall / 2.3s CPU; xdist worker startup would eat most of a 4-core
  runner's gain. Recorded in the issue so nobody re-derives it.
- **`paths:` filters** to skip jobs — `ci.yml` already warns why (a required
  check that never runs leaves a PR permanently pending). Didn't touch it.
- **Matrix on `test`** — same warning, renames the check. Adding a sibling
  job is safe; `test` keeps its name.
- **Caching the live responses** (VCR/cassettes) — considered and rejected.
  It would make them fast but would convert them into exactly the mocked
  tests the file exists to avoid. The value is that they can fail when the
  outside world changes.

## Side finding, not fixed

`mypy` in CI does nothing. `src/slopchecker/` has no `py.typed`, so mypy exits
with "Package 'slopchecker' cannot be type checked due to missing py.typed
marker" and `continue-on-error: true` hides it. That's why the step takes 0s.
Verified identical under both pip and uv, so it predates this change and the
installer swap neither causes nor fixes it.

Left alone on purpose: adding `py.typed` turns mypy on for real and surfaces a
backlog of type errors, which is not a CI-speed change and shouldn't ride in
on one. Worth its own issue.

## Next

- Watch a real run to confirm the uv and cache numbers on the runner
  (local measurements are a sandbox, not `ubuntu-latest`).
- When #43 is flipped: add `test` to the ruleset, **not** `live`.

---

# Part 3 — #143: the wall clock became a scheduling problem

#114 and #118 both cut *work*. By this point the remaining problem was
*shape*: four jobs, none dominant, wall clock = max(jobs).

Per-job on `6a58eeb`:

| Job | Total | Breakdown |
|---|---|---|
| `test` | 35s | setup 8 · ruff 1 · `pytest` 7.8 · `pytest -m integration` 11.6 |
| `live` | 26s | setup 9 · `pytest -m live` 14 |
| `worker` | 20s | setup 6 · npm ci 4 · checks 2 · `npm test` 6 |

Critical path flips between `test` and `live` run to run (on PR `a1c7afc` it
was test 25s / live 28s), so shaving either alone often buys nothing. Both
needed attacking.

## 1. `integration` gets its own job

11.6s serialised behind a 7.8s unit run for no reason.

The gating question is the one I got wrong in #114, so this time I measured
before arguing: **the integration suite is hermetic.** Under blocked DNS it
passes identically and in the same time (9.39s vs 9.27s). That's what makes
splitting it safe where splitting `live` was not — it can be a *required*
check, so the ruleset becomes `test` AND `integration`. Commented on #43,
because adding the job without adding the ruleset entry is precisely the #114
mistake wearing a new costume.

## 2. `pytest -m live -n 4`

xdist belongs here and *only* here. #114 explicitly rejected xdist for the
unit suite and that call still stands — it's CPU-bound at ~85% utilisation, so
worker startup costs more than it saves. The live suite is the mirror image:
24 tests at ~10% CPU, all of it waiting on four third-party hosts.

Worker count measured rather than guessed:

| workers | serial | 2 | 3 | **4** | 6 | 8 |
|---|---|---|---|---|---|---|
| wall | 17.7s | 13.5s | 11.7s | **10.5s** | 12.5s | 12.4s |

It gets *worse* past 4 — politeness limits and connection contention. Recorded
in the workflow comment as a ceiling, not a starting point, because the
obvious future "optimisation" is someone bumping it to 8.

`--dist load` deliberately: all live tests are in one file, so `--dist
loadfile` would pin them to one worker and buy nothing. Module-scoped fixtures
rebuild per worker as a result; that's already in the 10.5s.

Ran `-n 4` three consecutive times, 24/24 each. Concurrency against third-party
APIs is the one thing here that could flake, so a single green run wasn't
enough evidence.

## The finding that changed the plan

I went in expecting #132 (CLI/web network I/O) to be the big lever, since it's
~19s of the local unit suite. **On CI it's worth almost nothing:**
`test_web.py` runs in **0.147s on the runner** vs 2.35s here. GitHub's network
to Crossref is fast; my sandbox goes through a proxy.

So the local profile overstates #132's CI value by more than an order of
magnitude. It stays open as a dev-loop fix — which is still worth doing, it's
just not a wall-clock fix. Second time this session that local profiling
pointed at the wrong thing (the first was #118's PDF tests, invisible locally
because they skip without a browser). Profile on the machine that has the
problem.

## Not done

Per-job setup is ~8s × 4 jobs and is now the floor. No obvious lever — the uv
cache already hits. Anyone attacking wall clock further starts there.
