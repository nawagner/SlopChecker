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

# Part 3 — #143: what didn't work, and the metric that did

#114 and #118 cut *work*. By this point the problem was *shape*: four jobs,
none dominant. I shipped two changes. **One was wrong, and the one that
survived improved a different metric than the one I set out to improve.**

## Reverted: xdist on the live suite

Locally this looked decisive — serial 17.7s, n=2 13.5s, n=3 11.7s, n=4 10.5s,
n=6 12.5s, n=8 12.4s. A clean curve with an obvious optimum, reproducible.

**On the runner: 15s against 14s serial.** Nothing. And it aims four
concurrent workers at doi.org/Crossref/OpenAlex/arXiv for no benefit.

Same root cause as the #132 finding: this sandbox reaches those hosts through
a slow proxy, so the suite is genuinely network-bound *here* and workers
overlap the waiting. On a GitHub runner the network is fast enough that it
barely waits, and xdist's worker startup is pure overhead. Recorded in the
workflow comment at the point of use so nobody re-adds it off a local
benchmark.

## Kept: `integration` in its own job

Hermetic, verified rather than assumed — under blocked DNS it passes
identically and in the same time (9.39s vs 9.27s). That's what makes it safe
to *require*, unlike `live`. Ruleset set becomes `test` AND `integration`
(noted on #43); adding the job without the ruleset entry would be the #114
mistake in a new costume.

## The measurement that reframed it

Three runs, and the number I was chasing never moved:

| | before (3 jobs) | run 1 (4 jobs, xdist) | run 2 (4 jobs, no xdist) |
|---|---|---|---|
| `test` | 35s | 24s | 19s |
| `integration` | — | 29s | 21s |
| `live` | 26s | 25s | 27s |
| `worker` | 20s | 20s | 23s |
| max job | 35s | 29s | 27s |
| **wall span** | **35s** | **35s** | **35s** |

**Wall span was exactly 35s in all three.** With 3 jobs one is allocated ~6s
late; with 4 jobs, two are allocated ~8s late. The runner's allocation stagger
absorbs the parallelism almost exactly. More jobs did not make CI finish
sooner.

What *did* improve is the metric that actually gates a merge:

- time-to-**required**-checks-green: **35s → 21s**

`test` (19s) and `integration` (21s) both land before the advisory `live`
(27s), and nobody waits on `live` — it can never be required, by design. So
once #43 flips, a PR becomes mergeable 14s sooner even though the run as a
whole still takes 35s.

That is close to the ~21s I originally projected, and it is worth being clear
that I got there for a different reason than I claimed. The projection assumed
span would fall. It didn't.

## A CI landmine found by accident

A PR with merge conflicts gets **no workflow run at all** — `mergeable_state:
dirty` means GitHub can't compute `refs/pull/N/merge`, so `pull_request`
workflows never fire. I burned real time misdiagnosing this as a dropped
webhook and then as a repo-wide Actions outage; both were wrong.

It's nasty because it inverts the signal: the PR shows **no check**, not a
failing one, and the last green run stays visible so it reads as passing. Same
shape `ci.yml` already warns about for `paths:` filters. Once #43 flips, a PR
that develops a conflict silently stops producing checks and the fix is always
rebase, never re-run.

## Standing conclusion for whoever optimises this next

Per-job setup (~8-9s x 4) plus allocation stagger is the floor, and splitting
further will not beat it — that is now measured, not assumed. Real remaining
work is inside `test_integration_e2e.py` (subprocess-heavy) which is #81's
territory. And #132 stays a dev-loop fix: 19s locally, 0.147s on the runner.

**Three times this session a local profile pointed at the wrong thing** (#118
PDF tests invisible locally, #132 overstated by ~100x, xdist transferring to
zero). Profile on the machine that has the problem.
