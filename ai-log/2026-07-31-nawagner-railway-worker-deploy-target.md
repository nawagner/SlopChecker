# 2026-07-31 — nawagner (Claude Sonnet 5) — Railway + Worker deploy target

**Issues worked:** #27.

## What changed

- `src/slopchecker/web.py` — minimal FastAPI stub: `/health`, `/config`
  (booleans only — never a masked value fragment, unlike `slopcheck config`'s
  terminal output). Exists so Railway has something to deploy and so a set
  secret can be confirmed visible to the running process. Not the real API
  from #27's scope — that's still open.
- `railway.toml` — Nixpacks, `pip install -e '.[web]'`, uvicorn start command,
  `/health` healthcheck.
- `worker/` — Cloudflare Worker scaffold: `wrangler.toml`, a proxy Worker
  (`/api/*` → `RAILWAY_API_URL`, everything else → static assets), and a
  placeholder `public/index.html`.
- `pyproject.toml` — added `[web]` extra (fastapi, uvicorn).

## Decisions

- **No `uv.lock` in this repo → Nixpacks uses pip, not uv.** Sidesteps the
  `UV_PROJECT_ENVIRONMENT` boot failure hit on a different Railway project
  (uv-managed venv landing somewhere the start command doesn't look).
  `railway.toml` documents this explicitly so it isn't silently reintroduced
  if a lockfile shows up later.
- **`/config` never echoes secret material, not even masked.** The CLI's
  `slopcheck config` shows masked values because it's local, in a terminal
  you control. This endpoint is unauthenticated on the open internet, so it
  reports `set: true/false` only. Tested: setting `ANTHROPIC_API_KEY` and
  asserting the raw value never appears in the response body.
- **Didn't enter any real secret values anywhere.** Scaffolded the places
  secrets go (`.env.example`, this stub reading from `os.environ`, Railway
  variable slots) but the actual key material — Anthropic, Pangram, Candid —
  still needs to go in via `railway variables set` or the Railway dashboard,
  run by a human, not by the assistant.
- Worker proxy path deliberately simple: no auth, no rate limiting, nothing
  beyond "forward `/api/*`, serve static otherwise" — there's no real backend
  API yet for any of that to matter against.

## Mid-session: conventions changed under me

Rebased onto main partway through and picked up #32/#33's CLAUDE.md rewrite —
module ownership table, `STATUS.md`, branch-naming convention, git-identity
format. Handled:

- CI was broken by my own PR: workflow installed `.[dev]`, `test_web.py`
  needs `.[web]` for `fastapi`. Fixed to `.[web,dev]`.
- `web.py`/`railway.toml`/`worker/` aren't in the new module-ownership table,
  so no heads-up comment needed beyond what's already on #27.
- Created `STATUS.md` (referenced in CLAUDE.md, didn't exist yet) with an
  entry for this session.
- Left branch name (`railway-worker-deploy-target`) as-is rather than
  renaming to `<handle>/<issue>-<slug>` — it predates the convention and PR
  #34 was already open; renaming mid-PR is more churn than it's worth here.
- Did **not** change `git config user.name` to the new `"Name (surface)"`
  format — that's a git config change, which I don't make regardless of
  in-repo convention. Nick would need to set that himself if he wants it.

## Dead ends

- First `curl` verification of `/config` set the env var on the *client*
  (`ANTHROPIC_API_KEY=... curl ...`) instead of the server process — of
  course it read as unset. Re-ran with the var set before `uvicorn` started;
  worked as expected. Not a bug, just a test mistake.
- `.venv` here was built with `uv venv`, which doesn't ship `pip` — `uv pip
  install -p .venv/bin/python` instead of activating and using `pip` directly.

## Left to do

- `railway init`/`railway up` to actually create the Railway project and get
  a live URL — CLI is authenticated, hasn't been run yet this session.
- `wrangler login` — needs a browser, can't run from a non-interactive
  session. Nick needs to run it himself.
- Real secret values (Anthropic, Pangram, Crossref contact, Candid) — nobody
  has supplied them yet; they go in via `railway variables set` / Railway
  dashboard directly, not through an assistant session.
- Custom domain wiring (slop-checker.com → Cloudflare) still open, tracked
  on #27.
