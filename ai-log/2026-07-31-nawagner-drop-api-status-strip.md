# 2026-07-31 — nawagner (Claude Opus 5) — drop the API status strip

**Issues worked:** #74 (landing page).

## What changed

- Removed the live API status strip from `worker/public/index.html`: the
  `.apistrip` markup, its two CSS rules, and the `/api/health` →
  `/api/config` fetch chain that populated it. 20 lines deleted, nothing
  else touched.

## Why

The strip rendered `API live · v0.1.0 · 2/4 credentialed checks armed`,
which was wrong in two directions at once:

- **The count read worse than reality.** The denominator is
  `len(config.CREDENTIALS)`, which includes `CROSSREF_MAILTO` — not a
  credential at all. `config.py` marks it `secret=False` and
  `checks/net.py` says in as many words that DOI resolution must work
  without it; Crossref needs no auth. It also includes `CANDID_API_KEY`,
  which no check references yet. So "2/4" was really "both keys that
  gate a check are set, plus one courtesy header and one placeholder."
- **"Armed" is off-message.** Combat framing on a page whose entire pitch
  is signals-not-verdicts. An unset credential degrades its check to
  `skipped` (#5) — it doesn't disarm anything. The word also collided
  with the unrelated `.drop.armed` drag-hover class in the same file.

Considered rewording to `2 of 4 credentials configured` first (that's what
the before/after screenshots in the PR show), but a build-status readout
aimed at us, sitting on a page aimed at funders, isn't worth the line
either way. Deleted instead.

## Notes for whoever's next

- `/api/health` and `/api/config` still exist server-side (`web.py`) and
  are now unreferenced by the front end. Deliberate — they're useful for
  poking Railway directly (`curl https://slop-checker.com/api/config`
  still answers). If a build-info readout is wanted later, put it
  somewhere that isn't the funder-facing page, and don't count
  `CROSSREF_MAILTO` in the denominator.
- `worker/public/` is Dominique's per the ownership table; noted on #74
  rather than done silently.
- Verified with a local stub server (`/api/health` + `/api/config` faked
  to answer, so the strip *would* have shown if anything were left of
  it): no `apistrip`/`apitext`/`api/health` references remain in
  `worker/public/`, every `getElementById` in the page still resolves,
  the inline script passes `node --check`, and the sample-report line now
  meets the footer on the footer's own `3.5rem` margin — same gap the
  strip used to occupy, so there's no orphaned whitespace.
