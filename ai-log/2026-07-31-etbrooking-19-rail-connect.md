# 2026-07-31 — etbrooking — #19 rail connection + DOI consistency audit

Session: Fable via Claude Code. Emerson's live-review flag, three parts:
"lens/derived stuff doesn't work; DOI detection not consistently working;
comments should be inline and showing when something connects."

- **Lens clutter** — already fixed in #147 (claims flag-only mapping),
  which had merged minutes earlier; Railway deploy hadn't flipped when
  Emerson looked. Verify live once the deploy lands (claim findings
  should drop 10 → 2 on the demo doc).
- **DOI consistency — audited, working.** Four fixtures through the live
  API: both `__fabricated_citations` docs fail `all_dois_resolve` with
  per-DOI findings; clean docs pass. References parse everywhere. The
  "inconsistent" *feel* comes from two honest-gap sources: doi.org
  bot-walls 403 real publisher DOIs from the datacenter IP ("N could not
  be checked"), and `metadata_match` skipping on every document. The
  latter is a bug in effect: the identical `ProviderChain.lookup` works
  from a residential IP (Nature/PNAS found, fabricated → None), so
  Railway's anonymous cloud-IP traffic is being dropped by
  Crossref/OpenAlex. Filed **#152**: set `CROSSREF_MAILTO` on Railway
  (courtesy contact, not a secret; wired via User-Agent in `checks/net.py`).
- **Rail connection (this PR)** — two renderer changes, my module:
  - Cards whose anchor quote never matched used to absolute-position at
    `top: 0`, silently piling at the head of the rail and looking
    attached to the first paragraph. Now: server marks them
    `anno unanchored` (dashed border + "Quote not found in the extracted
    text" line) and the JS stacks them after the anchored cards.
  - Two-way hover: card → its `<mark>`s get `.active`; highlight → its
    card(s) get `.linked` (accent outline). Previously nothing connected
    visually until you clicked, and only in condensed mode.
- **Windows note for Dan:** `harness/substrates/grant_application__human.pdf`
  is a git symlink; Windows checkouts materialize it as a 65-byte stub, so
  `test_harness_end_to_end` fails locally (`cite-orphan-real-pdf: MISS`)
  while CI (Linux) is green. Pre-existing on main, not from this branch.
- Tests: 2 new/extended renderer tests; full suite green minus the
  pre-existing Windows symlink failure above.
