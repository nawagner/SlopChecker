# 2026-07-31 — nawagner (Claude Sonnet 5) — custom domain + Git-based auto-deploy

**Issues worked:** #27.

## What changed

- `worker/wrangler.toml` — `[[routes]]` with `custom_domain = true` for
  `slop-checker.com`; `workers_dev = true` and `preview_urls = true` made
  explicit rather than left to Wrangler's implicit defaults.
- Deployed via `wrangler deploy` (manually, this session) — live at
  https://slop-checker.com, verified 15/15 stable. `*.workers.dev` still
  occasionally 404s; that's Cloudflare's documented "shared infra, not for
  production" characteristic of that subdomain, not a config issue — the
  real domain is unaffected.
- Connected Cloudflare's native Git integration (Workers Builds) to the
  **existing** `slopchecker-web` Worker: root directory `worker/`,
  production branch `main`, preview builds enabled for other branches. Nick
  did this by hand in the dashboard; I verified it end-to-end from a
  screenshot he shared (repo connected, root directory correct, branch
  config correct).

## Decisions

- **`slop-checker.com` was already a Cloudflare zone with clean DNS** —
  nameservers already pointed at Cloudflare, zero existing records. The
  registrar-side step I'd flagged as "Nick's to do" in an earlier session
  turned out to already be done (or the domain was bought through/pointed at
  Cloudflare from the start). Confirmed via `dig NS` + `cf zones list`
  before touching anything, rather than assuming.
- **Cloudflare-native Git integration over a bespoke GitHub Actions
  pipeline.** I started building a GH Actions workflow (`wrangler deploy` on
  push to main, `wrangler versions upload` + PR comment for previews), but
  every path there needs a `CLOUDFLARE_API_TOKEN` as a GitHub secret — which
  I don't create or enter myself regardless of who's asking, since it's
  credential material. Nick asked to just do the dashboard connection
  instead, which sidesteps the problem entirely: Cloudflare's GitHub App
  mints its own scoped token, visible in the Build settings, never touched by
  either of us directly.
- **First dashboard attempt would have created a duplicate Worker.** Nick
  initially landed on the generic "Create Application → Connect to Git"
  wizard, which defaults to a new project named `slopchecker` — separate
  from the existing `slopchecker-web` that already had the custom domain and
  `RAILWAY_API_URL` configured. Caught this from the screenshot before he
  clicked Deploy: told him to back out and connect from the existing
  Worker's own Settings → Builds tab instead. Confirmed after the fact via
  `cf workers scripts list` that no duplicate `slopchecker` project exists —
  only `slopchecker-web`.
- Root directory (`worker/`) was the setting most likely to be missed or
  defaulted wrong, since the repo is a monorepo (Python package at root,
  Worker in a subdirectory) and the wizard's fields don't make that
  obviously necessary. Confirmed correct from Nick's screenshot before
  calling this done.

## Dead ends

- Started down the GitHub Actions + `wrangler versions upload` + PR-comment
  path (checked `wrangler versions upload --help` for output format) before
  Nick redirected to the dashboard-native approach. Not wasted — the
  `preview_urls = true` wrangler.toml setting I'd already added for that
  path turned out to be exactly what Cloudflare's own Git integration uses
  for its preview builds too, so it stayed.
- `cf dns records list -z slop-checker.com` initially failed with "No
  account ID found" — the `cf` CLI needs `CLOUDFLARE_ACCOUNT_ID` set
  explicitly even when only one non-ambiguous zone match exists; `wrangler`
  needed the same thing later when two accounts were on the token
  (`Learning Journey AI` vs a personal account).

## Left to do

- Nothing blocking. `*.workers.dev`'s occasional 404 is cosmetic per
  Cloudflare's own guidance — not chasing further.
- Next real push to `main` that touches `worker/**` will be the first live
  test of the Git-integration production deploy; worth a glance at the
  Builds tab after that to confirm it actually fired.
