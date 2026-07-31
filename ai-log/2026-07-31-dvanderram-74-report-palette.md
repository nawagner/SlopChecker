# 2026-07-31 — Dominique — #74 evidence report palette + badge contrast

Issue: #74 (landing/index lane), closing the follow-on flagged in my own 14:02
note — the landing page moved to blue/green/white in #106 while the evidence
report was still on the original warm palette, so the two read as different
products. Also closes the `data-theme` question from
[the earlier audit](2026-07-31-dvanderram-74-landing-audit.md) and part of #26.

## What changed

Three files, all in `src/slopchecker/report/` plus its generated output:

- **`assets/report.css`** — token values swapped to the ones `index.html` uses.
  This was a value swap, not a restructure: `report.css` consumes exactly the
  twelve colour tokens the new palette already defines, so every consuming rule
  was left untouched.
- **`assets/report.css`** — added `--on-strong` and used it for `.a-id`.
- **`html.py`** — legend copy said "purple = detector score"; `--score` is now
  `#4A5CA6`, an indigo. Changed to "indigo".
- **`worker/public/demo-report.html`** — regenerated, not hand-edited.

## The bug the palette swap would have hidden

`.a-id` (the annotation ID badges) hardcoded `color: #fff` against
`var(--no)` / `var(--yes)` / `var(--score)` / `var(--soft)` fills. In dark mode
those tokens invert to light pastels, so it was white-on-pastel:

| dark mode | `#fff` (before) | `var(--on-strong)` (after) |
|---|---|---|
| on `--no` `#E3796F` | 2.90 | **6.26** |
| on `--yes` `#6DC194` | 2.16 | **8.41** |
| on `--score` `#9BA9EC` | 2.26 | **8.04** |
| on `--soft` `#9BABBC` | 2.35 | **7.75** |

This is the same defect Emerson fixed on the landing page in #106 ("buttons and
chip badges hardcoded `#fff` over inverted light fills"), and it existed
identically here. `--on-strong` flips to near-black in dark mode, matching how
`index.html` solves it. Every colour in `report.css` now goes through a token —
no hardcoded values left.

## Contrast, before and after

The swap also cleared both light-mode AA failures from the earlier audit:

| | before | after |
|---|---|---|
| `--soft` on `--panel` | 4.32 | **5.13** |
| `--yes` on `--panel` | 4.49 | **4.94** |

Everything else clears comfortably (`ink on bg` 15.65, `accent on bg` 7.62).
`--rule` on `--bg` is 1.31, but that token is only used for dividers and rules,
which are decorative rather than UI-component boundaries — noting it so the
next person doesn't re-flag it as a failure.

## `data-theme` resolved

The audit flagged `:root[data-theme="light"|"dark"]` in `report.css` as dead —
nothing ever set the attribute. #106 dropped those blocks from `index.html`
entirely, which settled the question by precedent, so they're deleted here too.
Zero `data-theme` references remain anywhere in the repo.

## Notes for whoever picks up next

- **Regenerating requires Python 3.11+.** This machine had only system 3.9.6,
  which dies on `zip(strict=True)`. Installed `python@3.11` via Homebrew and
  made a `.venv` (gitignored). The command is
  `slopcheck render tests/fixtures/sample_report.json -o worker/public/demo-report.html`.
  `pytest` needs `pip install -e ".[web,dev,pdf,docx,similarity]"` — without the
  `similarity` extra, `test_cli_run.py::test_batch_ranks_by_concerns` fails on a
  missing `datasketch` and it looks like a real failure.
- **`--score` and `--accent` are now both blues** (`#4A5CA6` vs `#14568F`). The
  separation that matters is score-vs-pass/fail, and that's intact — score is
  clearly distinct from `--no` red and `--yes` green. But if anyone finds the
  score lane reading as "brand blue" rather than its own lane, that's a palette
  change in *both* files, not just this one.
- **The palette is duplicated between `report.css` and `index.html` by hand.**
  There's no shared source. A comment at the top of `report.css` says so.
  Worth a real fix if the two drift again.

Full suite green: 473 passed, 1 skipped, 9 deselected.
