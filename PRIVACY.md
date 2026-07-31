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

- The **Pangram** AI-detection check is the only thing that sends your document's
  **raw text** off-machine, and only when `PANGRAM_API_KEY` is set.
- Citation source-fetching (#10) sends **cited identifiers/URLs** (not the
  submission body) to open-access sources, and only when a network fetcher is
  configured.
- Everything else is either fully local or not yet wired to a network service
  (see the table). No check transmits data to a service you have not enabled.

## What each check sends, and when

| Check / tier | Service | Endpoint | What is sent | Runs only when | Status |
|---|---|---|---|---|---|
| AI-generated text detection (#12) | **Pangram** | `https://text.external-api.pangram.com/task` | Windows of the submission's **raw text** plus a model name | `PANGRAM_API_KEY` is set | **Live in code today** |
| Claims / citation support / budget review (LLM tier) | **Anthropic** (default model `claude-opus-5`) | Anthropic API | Extracted claims and citation/quote text | `ANTHROPIC_API_KEY` is set | `[PLANNED]` — declared in `config.py`, no live call in `src/` yet |
| DOI / reference resolution (#8) | **Crossref** | Crossref REST API | Citation metadata / DOIs only (no submission body) | always (no auth; `CROSSREF_MAILTO` is a courtesy header) | `[PLANNED]` — not yet implemented |
| Prior-funding lookups (#21) | **Candid** | Candid grants API | Lookup queries derived from the submission | `CANDID_API_KEY` is set | `[PLANNED]` — not yet implemented |
| Quote verification against sources (#10) | Open web — **open-access only** (arXiv, PMC OA, DOAJ, plain-URL gray literature) | various | The **cited identifiers/URLs** (DOI, arXiv id, URL) — **not** the submission body | a network fetcher is configured (default is `LocalFileFetcher`, which stays local) | **Live in code today** (#93) — OA-only by design; no paywall circumvention |
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

The tool is **online-capable by default today** — network tiers run when their
keys are set and, for #10, when a network fetcher is configured. A dedicated
`[PLANNED]` `--offline` flag (#23 acceptance criterion) will force the
deterministic tier only and make **zero** third-party network calls, with a test
asserting no outbound requests; that flag is a follow-up, not yet shipped.

Until it lands, the practical equivalent is to **leave all API keys unset** and
use the default `LocalFileFetcher` — with no `PANGRAM_API_KEY` (and no
LLM/Candid keys) and no network fetcher, no check has a way to call out and the
run stays local. The report records each such check as `skipped: missing <KEY>`,
so a keyless run is honest about what it did not do rather than silently passing.

## Caches and retention

| Cache | What it holds | Location | Default |
|---|---|---|---|
| Check results (network/LLM checks) | Results keyed by a content hash, as `{"cached_at", "value"}` JSON | `~/.cache/slopchecker/` | **On** — override with `--cache-dir` or `$SLOPCHECK_CACHE_DIR`; disable with `--no-cache` |
| Source text (#10) | Fetched open-access source full text | under the cache dir | Populated only when a network fetcher is configured; never redistributed (reports carry only the matched window) |
| Credentials | API keys | `.env` (never committed; see `.gitignore`) | — |

Only checks that make network/LLM calls write to the cache; a deterministic-only
run stores nothing. The `<cache_dir>/<hash>.json` scheme is shared by the LLM
lens cache and the (not-yet-wired) Pangram detector cache.

- **Retention period** — the policy is to purge cached results and fetched
  source text after **30 days**, matching the default deletion window the major
  API providers we call already use (e.g. Anthropic's commercial API). Entries
  carry a `cached_at` timestamp, but automatic TTL enforcement is not yet
  implemented — today caches persist until deleted.
- **Cache purge** — `[PLANNED]` (#23 acceptance criterion, tracked in #108): a
  command to delete all caches on demand; until then, remove
  `~/.cache/slopchecker/` (or your `--cache-dir`) by hand, or run with
  `--no-cache`.
- Shared bulk corpora and fixtures live in Cloudflare R2, not in git — see
  [docs/data-storage.md](docs/data-storage.md). That store holds
  **synthetic** data; if real submissions are ever indexed for similarity
  (#14), the same questions in this document apply to them.

## Team policy decisions (settled)

- **Default mode** — online-capable by default (network tiers run when their
  keys/fetchers are configured). An `--offline` switch is a planned follow-up.
- **Open-web source fetch (#10)** — permitted for unpublished submissions for
  the MVP. In practice the shipped fetchers are **open-access only** (arXiv, PMC
  OA, DOAJ, plain-URL gray literature) and send cited identifiers/URLs, not the
  submission body — so the exposure is narrow by design.
- **Cache retention period** — **30 days**, aligned with the major API
  providers' default deletion window. Caching defaults on at
  `~/.cache/slopchecker/` (override with `--cache-dir`/`$SLOPCHECK_CACHE_DIR`,
  disable with `--no-cache`); TTL enforcement is tracked in #108.

The only items still open are the two provider-side `[CONFIRM]`s above (the
Pangram API-path confirmation and confirming Anthropic Commercial Terms), which
warrant a note in writing before the first real submission.

## Per-report disclosure

`[PLANNED]` (#23 acceptance criterion): every generated report will carry a
one-line disclosure naming which external services it actually called (for
example, "External services used: Pangram" or "External services used: none").
The list is derived from the checks that ran, so the disclosure can never drift
from what the tool actually did.
