"""AI-detection providers (#12).

Detectors return `DetectorResult`s carrying quote-anchored findings and a
document-level ledger row. Scores live in their own visual lane per the
project rule "scores are not verdicts" (CLAUDE.md); the tool recommends
`human_review` and never auto-rejects.

Currently one implementation (`PangramDetector`) hidden behind the
`Detector` protocol so a second detector — a local model, an alternate
provider — can be added without touching callers.
"""

from __future__ import annotations

from slopchecker.detect.pangram import (
    Detector,
    DetectorResult,
    PangramConfig,
    PangramDetector,
)

__all__ = ["Detector", "DetectorResult", "PangramConfig", "PangramDetector"]
