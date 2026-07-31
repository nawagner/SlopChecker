# STATUS

Append-only. Newest entry on top. One line per entry:
`- HH:MM <name> — did X / next Y / blocked on Z`

## Log

- 12:14 Dan (fable) — merged the model spine: #45 `models.py` + `docs/DATA_MODEL.md` (#3 — read that doc for the schema + which tests cover what), #46 claims lens + loader (#13), #49 CI fix (PDF tests deadlocked CI on every run since #40: snap chromium hang + crashpad pipe deadlock; test job now ~25s), #44 handle typo; filed #43 (Nick's Claude flipped it — CI is now a required check) / next: three parallel agent lanes in flight — #4 ingestion, #5+#6 runner+CLI, #7+#10 citations — then #29 harness / blocked on nothing.

- 16:05 Nick (claude-code) — did flip `test` on as a required status check
  on main via the `mainsaver` ruleset (#43, last box of #2) — it was a
  ruleset, not classic branch protection, per Dan's hunch / found CI was
  red on main at the time (since #40, Chromium PDF render timing out) so
  the required check blocked every PR briefly — filed #47 with a
  (wrong — see #47's later comments) `/dev/shm` diagnosis; #49 landed the
  real fix (crashpad pipe deadlock) minutes later and #47 is closed / #2's
  last box is genuinely done now: required + green / blocked on nothing.

- 15:31 Dan (claude-code) — added GH-handle → name map to CLAUDE.md, PR #41 (3 of 5 team members named — Alex + Dominique's handles later); also opened #37 (retry ladder + cross-provider failover, pattern from tls-review-shared) / next: continuing tls-review-shared reference review, planning pat-helper harness port for #29 / blocked on nothing.

- 11:39 Nick — did put slop-checker.com live on the Worker (custom domain
  route, already a Cloudflare zone with clean DNS, no registrar step
  needed) / did connect Cloudflare's native Git integration to the existing
  slopchecker-web Worker (root directory worker/, main → production,
  other branches → preview deploys) instead of a bespoke GitHub Actions
  pipeline — avoids ever handling a Cloudflare API token as a secret,
  Cloudflare's GitHub App generates its own scoped token / next: nothing
  blocking, `*.workers.dev` still occasionally 404s per Cloudflare's own
  "shared infra, not for production" guidance — cosmetic, the real domain
  is solid / blocked on nothing.
- 11:20 Emerson (claude-code) — PDF output landed (`slopcheck render --pdf`, headless Chrome/Edge print, no new deps); took over `report/` module ownership (Alex not tracking it — confirmed in person), further iteration hands to Dominique / next: demo scenario #25 / blocked on nothing

- 11:17 Nick — did deploy the Cloudflare Worker for real
  (slopchecker-web.nwagner.workers.dev), proxy to Railway verified on all
  routes / found + fixed a real bug: `/config` reloaded `.env` per-request
  instead of once at startup, which silently defeated a test's monkeypatched
  "key unset" scenario once real keys landed locally / next: Wrangler route
  + slop-checker.com DNS once it's on Cloudflare / blocked on nothing.
- 11:00 Emerson (claude-code) — #19 report.json → HTML renderer landed as `src/slopchecker/report/` + `slopcheck render`, tests green / next: PDF step (Alex), wire to models.py when #3 lands / blocked on nothing
- 10:57 Nick — did first real Railway deploy of the #27 stub, hit a
  Nixpacks/hatchling readme-timing build failure, fixed by dropping
  `readme=` from pyproject.toml / live at
  slopchecker-production.up.railway.app, `/health` + `/config` verified /
  next: Wrangler login (needs a browser, can't run headless) + real secret
  values, both mine to do, not the assistant's / blocked on nothing.
- 10:50 Nick — did Railway deploy target (FastAPI health/config stub) +
  Cloudflare Worker scaffold, PR #34 / did rebase onto module-ownership +
  git-discipline CLAUDE.md update / next real secret values go in via
  `railway variables set`, run directly, not through an AI session / blocked
  on nothing.
