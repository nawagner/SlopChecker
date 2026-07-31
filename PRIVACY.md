# Data handling and privacy

SlopChecker screens funding proposals, which are often **unpublished** and
contain personal and organizational data about applicants. This document states
exactly what data leaves your machine, to whom, and what is kept. It is the
deliberate, documented decision the tool's data flows are held to — not whatever
falls out of implementation defaults (#23).

> **Status of this draft.** Sections marked `[CONFIRM]` need a provider's answer
> in writing; sections marked `[DECISION]` need a team policy call; sections
> marked `[PLANNED]` describe behavior tracked for follow-up but not yet
> implemented. Everything else is derived directly from the current code.

## The short version

- The **only** thing that sends your document off-machine today is the
  **Pangram** AI-detection check, and only when `PANGRAM_API_KEY` is set.
- Every other tier is either fully local or not yet wired to a network service
  (see the table).
- No check ever transmits data to a service you have not supplied a key for.

## What each check sends, and when

| Check / tier | Service | Endpoint | What is sent | Runs only when | Status |
|---|---|---|---|---|---|
| AI-generated text detection (#12) | **Pangram** | `https://text.external-api.pangram.com/task` | Windows of the submission's **raw text** plus a model name | `PANGRAM_API_KEY` is set | **Live in code today** |
| Claims / citation support / budget review (LLM tier) | **Anthropic** (default model `claude-opus-5`) | Anthropic API | Extracted claims and citation/quote text | `ANTHROPIC_API_KEY` is set | `[PLANNED]` — declared in `config.py`, no live call in `src/` yet |
| DOI / reference resolution (#8) | **Crossref** | Crossref REST API | Citation metadata / DOIs only (no submission body) | always (no auth; `CROSSREF_MAILTO` is a courtesy header) | `[PLANNED]` — not yet implemented |
| Prior-funding lookups (#21) | **Candid** | Candid grants API | Lookup queries derived from the submission | `CANDID_API_KEY` is set | `[PLANNED]` — not yet implemented |
| Quote verification against sources (#10) | Open web (arXiv, PMC, DOAJ, cited URLs) | various | Requests to cited source URLs | a network fetcher is configured | `[PLANNED]` — currently **local-only**; only `LocalFileFetcher` (reads pre-downloaded text) ships today |
| Ingestion, tagging (#15), quote-matching, report render | none | — | nothing leaves the machine | always | Fully local |

Everything in the **deterministic tier** — document ingestion, tagging, word
counts, quote-string matching, and report rendering — runs entirely on your
machine with no network access.

## Does any provider train on submitted content?

This is the question that matters most for unpublished applicant material. The
answers below are taken from each provider's published policy as of
**2026-07-31**; provider terms change, so re-check before relying on them.

- **Pangram** — Per Pangram's published data-privacy commitment, it does **not**
  retain submitted data beyond what is needed to return a result and states it
  will never use submitted data to train an AI system of any kind; enterprise
  zero-data-retention options exist, and handling is described as FERPA- and
  GDPR-aligned. Their public statements do not separate the API from other
  products (the API page defers to a Data Privacy FAQ), so `[CONFIRM]` get a
  one-line written confirmation for the **API path specifically**
  (privacy@pangram.com) before the first real submission. Sources:
  [privacy commitment](https://www.pangram.com/blog/pangram-s-commitment-to-data-privacy),
  [privacy policy](https://www.pangram.com/privacy-policy),
  [API](https://www.pangram.com/solutions/api).
- **Anthropic** (LLM tier, default `claude-opus-5`) — Per Anthropic's API
  data-retention docs, on the **commercial API** prompts and outputs are not
  retained by default and retained data is never used for model training without
  express permission; zero-data-retention is available on request, and flagged
  content may be held up to two years. `claude-opus-5` is not a "Covered Model"
  (only Fable 5 / Mythos 5 require mandatory 30-day retention), so it is
  ZDR-eligible. `[CONFIRM]` that this deployment is under Anthropic's Commercial
  Terms (not a consumer plan) before the LLM tier is enabled. Sources:
  [API and data retention](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention),
  [is my data used for training](https://privacy.claude.com/en/articles/7996868-is-my-data-used-for-model-training).
- **Crossref / Candid** — receive citation metadata and lookup queries rather
  than the submission body; lower sensitivity, but note their terms when those
  checks land.

## Offline / deterministic-only mode

`[PLANNED]` (#23 acceptance criterion): a flag (e.g. `--offline`) that runs the
deterministic tier only and makes **zero** third-party network calls, for
reviewers who cannot send submissions to any external service. A test will
assert no outbound requests are made in this mode.

Until that flag lands, the practical equivalent is to **leave all API keys
unset** — with no `PANGRAM_API_KEY` (and no LLM/Candid keys), no check has a
credential to call out with, and the run stays local. The report records each
such check as `skipped: missing <KEY>`, so a keyless run is honest about what it
did not do rather than silently passing.

## Caches and retention

| Cache | What it holds | Location | Default |
|---|---|---|---|
| Pangram results | Detection results keyed by a content hash of the text | `<cache_dir>/<hash>.json` | **Off** — caching is opt-in; disabled unless a `cache_dir` is configured |
| Source text (#10) | Fetched open-access source full text | cache directory | Only populated once network fetchers exist; local-only today |
| Credentials | API keys | `.env` (never committed; see `.gitignore`) | — |

- **Retention period** — `[DECISION]` How long may cached results and any
  fetched source text persist before they must be purged?
- **Cache purge** — `[PLANNED]` (#23 acceptance criterion): a command to delete
  all caches on demand.
- Shared bulk corpora and fixtures live in Cloudflare R2, not in git — see
  [docs/data-storage.md](docs/data-storage.md). That store holds
  **synthetic** data; if real submissions are ever indexed for similarity
  (#14), the same questions in this document apply to them.

## Team policy decisions still open

Each carries a recommended default; the team makes the final call.

- `[DECISION]` **Default mode** — offline-by-default, or online-by-default once
  keys are present? _Recommended: offline-by-default_, so network tiers are
  opt-in and unpublished submissions never leave the machine by accident.
- `[DECISION]` **Open-web source fetch (#10)** — acceptable for unpublished
  submissions, or restricted to allow-listed open-access repositories?
  _Recommended: allow-listed open-access repositories only._
- `[DECISION]` **Cache retention period** (above) — _Recommended: caching off by
  default; if enabled, a short TTL (e.g., seven days) plus the purge command._

Provider training and retention answers are filled in above from each provider's
published policy (2026-07-31); the two `[CONFIRM]` items there are the only
provider-side questions that still warrant confirmation in writing.

## Per-report disclosure

`[PLANNED]` (#23 acceptance criterion): every generated report will carry a
one-line disclosure naming which external services it actually called (for
example, "External services used: Pangram" or "External services used: none").
The list is derived from the checks that ran, so the disclosure can never drift
from what the tool actually did.
