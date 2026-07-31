# 2026-07-31 — danparshall — claims-extraction lens (#13)

Session: Dan (+ Fable), worktree `danparshall/13-claims-lens`.

## What landed

- `src/slopchecker/lenses/` package: `claims.md` prompt pack (system
  prompt + JSON output spec + few-shot on the fabricated Meridian
  fixture text), `README.md` lens-format spec, `loader.py` (markdown →
  `Lens` dataclass, ~150 lines, no LLM client).
- `tests/test_lenses.py` — includes generic per-lens tests that run
  against every `*.md` in the package: example output must parse as
  JSON and every `quote` must be a verbatim substring of the example
  input. Quote-anchoring is enforced mechanically on future lenses too.

## Decisions

- Claim item shape: `{id, type, page, quote, quantitative, citation}`;
  type enum `capability|outcome|timeline|prior-work|impact` per the
  issue. Mapping to the #3 strawman `Finding` is a table in the lens
  file: label `Claim (<type>)`, anchor = page+quote, checks derived
  deterministically (`claim_quantitative`, `claim_cited`,
  `quant_unsourced`) — all bool, no LLM prose in the evidence layer.
- `quant_unsourced = quantitative && citation == null` is the summary
  counter for #13's "unsourced quantitative claims" acceptance
  criterion; computed downstream, not by the model.
- Few-shot input reuses the fabricated proposal text from
  `tests/fixtures/sample_report.json` (with `[[page N]]` markers) so
  the example stays consistent with the report fixture and stays
  fabricated.
- Deliberately NOT here (YAGNI, per issue scope + #37): LLM client,
  retries, caching/idempotency per doc hash, the claims→Finding
  converter code. The lens defines the contract; the pipeline engine
  executes it.

## Dead ends

- First venv attempt landed in the main worktree (agent cwd resets
  between calls) — removed, redone with absolute paths. No repo impact.

## What's left

- #3 models PR hadn't landed at branch time; if `models.py` names
  differ from the strawman, only the mapping table in `claims.md`
  needs touching.
- Acceptance criteria needing a live LLM remain open: run-to-run
  stability diffing, caching (pipeline #37), manual review on 5 real
  proposals.
- `Finding` has no first-class claim-type field; type currently rides
  in `label`. If a downstream feature needs to filter by type, raise it
  on #3.
