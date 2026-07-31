# 2026-07-31 — nawagner (Claude Opus 5) — package scaffold + env config

**Issues worked:** #2 (PR #28), #27 (filed, then rewritten).

## What changed

- `pyproject.toml`, `src/slopchecker/` — Python 3.11+ package, hatchling,
  `slopcheck` console entry point. Heavy deps behind extras (`[pdf]`, `[docx]`,
  `[llm]`) per the note on #2, so citation work doesn't pull the PDF stack.
- `src/slopchecker/config.py` — credentials resolve from `.env`; a missing key
  raises a typed `MissingCredential` rather than crashing. That's the hook #5
  needs to record `skipped: missing PANGRAM_API_KEY`.
- `src/slopchecker/cli.py` — `slopcheck config` prints which keys are set,
  masked to the last 4 chars. `run` is still #6's to write.
- `.env.example` — Pangram (#12), LLM provider (#13/#17/#18), Crossref contact
  (#8), Candid (#21). Every key optional.
- `.gitignore` — added `.env` before anyone could put a real key in one. Merged
  as a union with main's version; `.slopcheck-transcript` kept.
- `.github/workflows/ci.yml` — ruff + pytest on push/PR, mypy non-blocking.
- Issue #27: hosting at slop-checker.com.

## Decisions

- **Cloudflare can't host the Python core.** #27 originally proposed a
  `/lib` + `/web` monorepo with a Worker importing the library directly. That's
  wrong — Python Workers are Pyodide-based and won't take pypdf/pdfplumber/
  python-docx/the Anthropic SDK. Rewrote #27 as Cloudflare for DNS + frontend,
  Railway for the Python API. Cloudflare Containers would work and keeps one
  vendor, but it's newer and off the Workers free tier — revisit after the
  pipeline stabilizes.
- **Missing credentials are a first-class state, not an error.** A no-keys
  checkout still runs the deterministic tier; the report says what was skipped
  and why. Falls straight out of #5's acceptance criteria.
- **Secrets never print in full.** `config.status()` masks to the last 4 chars;
  non-secret values (Crossref contact email) show in full since they're meant
  to be read. Test asserts a raw secret can't come back from `status()`.
- Default LLM model is `claude-opus-5`, overridable with `SLOPCHECK_LLM_MODEL`.

## Dead ends

- Assumed this was a TypeScript/Workers project from the issue title and nearly
  scaffolded an npm monorepo. Reading #2 first would have saved it — **the
  issue tree is the spec; read it before writing code.**
- Nearly filed #27 as a duplicate. `gh issue list` before filing: the repo had
  25 open issues that don't show in `git log`, because a 3-commit repo looks
  empty from the shell.

## Left to do

- Branch protection so CI is required on PRs — the one unchecked box in #2's
  acceptance criteria. Repo setting, not a code change.
- `.env` keys themselves (Pangram, Anthropic) — nobody's supplied them yet.
- #27 needs a Railway service before any of the Cloudflare side is testable.
  Noted there: uv-managed deploys can boot-fail with
  `uvicorn: command not found` until `UV_PROJECT_ENVIRONMENT=/opt/venv` is set
  in Railway's variables. Railway setting, not a repo change.
