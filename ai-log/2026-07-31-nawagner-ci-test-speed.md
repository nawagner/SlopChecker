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
- Expect `test` job ~42s → ~10s; CI wall clock bounded by `live` (~25s)
- Coverage unchanged — all 432 tests still run in CI

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
