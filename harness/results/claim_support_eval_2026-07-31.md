# Claim-support judge evaluation (#104)

Corpus: 20 fabricated triples (20 judged, 0 errored/refused). Overall judge accuracy: **85%**.

## Confusion matrix (rows = ground truth, cols = judge verdict)

| gt \ pred | suppo | overs | unsup | contr | unver | total |
|---|---|---|---|---|---|---|
| **supported** | 4 | 0 | 0 | 0 | 0 | 4 ✓ |
| **overstated** | 0 | 1 | 0 | 3 | 0 | 4 |
| **unsupported** | 0 | 0 | 4 | 0 | 0 | 4 ✓ |
| **contradicted** | 0 | 0 | 0 | 4 | 0 | 4 ✓ |
| **unverifiable** | 0 | 0 | 0 | 0 | 4 | 4 ✓ |

## Per-category precision / recall

| verdict | support | precision | recall | f1 |
|---|---|---|---|---|
| supported | 4 |  1.00 |  1.00 |  1.00 |
| overstated | 4 |  1.00 |  0.25 |  0.40 |
| unsupported | 4 |  1.00 |  1.00 |  1.00 |
| contradicted | 4 |  0.57 |  1.00 |  0.73 |
| unverifiable | 4 |  1.00 |  1.00 |  1.00 |

**Passage quotecheck:** 9/12 concern verdicts carried a passage that clears `match_quote` (the gate before a finding reaches the report).

## `min_confidence` threshold sweep (concern verdicts only)

The knob drops concern verdicts below the threshold. *Good flags* have a concern ground truth; *false alarms* flag a clean (supported/unverifiable) claim — the costly error.

| threshold | good flags kept | false alarms kept | exact-label kept |
|---|---|---|---|
| 0.50 | 12/12 | 0/0 | 9 |
| 0.55 | 12/12 | 0/0 | 9 |
| 0.60 | 12/12 | 0/0 | 9 |
| 0.65 | 12/12 | 0/0 | 9 |
| 0.70 | 12/12 | 0/0 | 9 |
| 0.75 | 12/12 | 0/0 | 9 |
| 0.80 | 12/12 | 0/0 | 9 |
| 0.85 | 12/12 | 0/0 | 9 |
| 0.90 | 12/12 | 0/0 | 9 |
| 0.95 | 11/12 | 0/0 | 8 |

**Recommended `min_confidence`: 0.60** (current default 0.60). no false alarms at any threshold in this corpus — the judge did not flag a single clean claim as a concern. Keep the current default and re-evaluate on a larger corpus; this run gives no evidence to raise it.

## End-to-end silence check

PASS — all supported/unverifiable claims stayed silent.

## Misclassifications

- `ov-01`: ground truth **overstated** -> judge **contradicted** (conf 0.95)
- `ov-03`: ground truth **overstated** -> judge **contradicted** (conf 0.98)
- `ov-04`: ground truth **overstated** -> judge **contradicted** (conf 0.97)

_Small-n caveat: this is a ~20-item fabricated corpus. Treat the numbers as directional smoke-tests of judge behavior, not production accuracy claims._
