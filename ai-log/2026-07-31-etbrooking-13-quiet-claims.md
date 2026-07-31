# 2026-07-31 — etbrooking — #13 claims → Finding mapping: flag-only

Session: Fable via Claude Code. Emerson's read on the live demo report:
"the claim (capability, prior-work, etc.) system is polluting without
helping." Verified, then fixed at the mapping.

- **Diagnosis:** `_map_claim_to_finding` emitted every extracted claim
  with three descriptive booleans (`claim_quantitative`, `claim_cited`,
  `quant_unsourced`). At least one is False for every possible claim
  (a cited quantitative claim gets `quant_unsourced: False`), and the
  renderer's `_finding_lane` paints any finding containing a False as
  the red failing lane. Net effect on the demo grant application: all
  10 claims marked red, visually identical to the 3 fabricated DOIs;
  the one real problem (unsourced quantitative claim) showed a *green*
  `quant_unsourced: YES` chip in its card. Attributes encoded as
  pass/fail checks, polarity inverted end to end.
- **Fix (pipeline/checks_llm.py + lenses/claims.md mapping table):** a
  claim becomes a Finding only when it flags something — currently
  `quantitative && citation == null` — labeled "Unsourced quantitative
  claim" with a single check `quant_claim_sourced: false` (False *is*
  the flag, so the lane reads correctly). Unflagged claims are silent,
  mirroring claim_support's silent `supported` verdict. Ledger keeps
  the full extraction: `claims` = total, `claims_quant_unsourced` =
  flagged count. `claim_support` consumes `extract_citations`, not
  these findings, so nothing downstream moves.
- **DOI question, also from Emerson ("is doi working properly?"):** yes.
  Fresh live run on grant_application__fabricated_citations: 3 real
  Nature DOIs resolve; the 3 fabricated DOIs (10.7274/jlc90oup,
  10.1862/lo7cze3s, 10.5979/p3x5m8pj) 404 and each raises a red
  finding; PNAS + JAMA×2 return 403 bot-walls and are reported as
  per-item coverage gaps, not failures — the "a dead link is evidence
  of a dead link" design doing its job. metadata_match remains the weak
  one (all 9 "could not be checked").
- **Process:** design comment posted on #13 tagging Dan (his module,
  co-owned by Fable per the ownership table).
- Tests: two mapping tests rewritten (flag-only + polarity), 501 unit
  tests green, ruff clean.
