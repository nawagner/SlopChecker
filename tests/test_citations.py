"""Tests for #7: citation extraction — unit behavior + P/R vs hand labels.

The fixture corpus (`tests/fixtures/citations/`) is fabricated (repo rule:
no real applicant material). Each doc ships with a hand-labeled
`*.labels.json`; the P/R test scores mention detection, reference parsing,
and mention→reference linking against those labels and prints the numbers
(run with `-s` to see them — they get posted to issue #7).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from slopchecker.pipeline.citations import extract_citations, find_reference_region

FIXTURES = Path(__file__).parent / "fixtures" / "citations"
DOCS = ["apa", "chicago", "ieee"]


def load(name: str):
    text = (FIXTURES / f"{name}.txt").read_text()
    labels = json.loads((FIXTURES / f"{name}.labels.json").read_text())
    return text, labels


def nth_offset(text: str, needle: str, occurrence: int) -> int:
    """Offset of the nth (1-based) occurrence of needle; asserts it exists."""
    pos = -1
    for _ in range(occurrence):
        pos = text.find(needle, pos + 1)
        assert pos != -1, f"label references missing text: {needle!r} x{occurrence}"
    return pos


def overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start < b_end and b_start < a_end


# ---------------------------------------------------------------- unit tests


def test_reference_region_found():
    text, _ = load("apa")
    region = find_reference_region(text)
    assert region is not None
    assert "Delacroix" in text[region.start : region.end]
    assert "References" not in text[region.start : region.end]


def test_apa_reference_fields():
    text, _ = load("apa")
    refs = {r.key: r for r in extract_citations(text).references}
    delacroix = refs["delacroix-2023"]
    assert delacroix.year == 2023
    assert delacroix.doi == "10.1234/jams.2023.0142"
    assert delacroix.url == "https://doi.org/10.1234/jams.2023.0142"
    assert delacroix.title == "Prebunking at platform scale: A field experiment"
    assert delacroix.venue == "Journal of Applied Misinformation Studies"
    assert delacroix.pages == "101-129"
    assert delacroix.authors[0].startswith("Delacroix")
    assert len(delacroix.authors) == 3
    assert refs["smith-2021"].arxiv_id == "2107.04321"


def test_ieee_reference_fields():
    text, _ = load("ieee")
    refs = {r.key: r for r in extract_citations(text).references}
    assert set(refs) == {"1", "2", "3", "4"}
    alvarez = refs["1"]
    assert alvarez.year == 2020
    assert alvarez.pages == "211-224"
    assert alvarez.title.startswith("Field measurements")
    assert len(alvarez.authors) == 2
    assert refs["3"].doi == "10.9012/tpr.2022.1201"


def test_chicago_year_suffix_keys():
    text, _ = load("chicago")
    refs = {r.key: r for r in extract_citations(text).references}
    assert "nakamura-2019a" in refs
    assert "nakamura-2019b" in refs
    assert refs["nakamura-2019a"].title == "Community Archives and the Recent Past"
    assert refs["nakamura-2019a"].doi == "10.2345/ap.2019.312"


def test_multi_number_marker_yields_one_citation_per_number():
    text, _ = load("ieee")
    ext = extract_citations(text)
    pair = [c for c in ext.citations if c.mention.marker == "[3, 4]"]
    assert [c.number for c in pair] == [3, 4]
    assert all(c.reference is not None for c in pair)


def test_unlinked_mention_becomes_finding():
    text, _ = load("apa")
    ext = extract_citations(text)
    assert len(ext.findings) == 1
    f = ext.findings[0]
    assert f.target == "Marlowe, 2018"
    assert f.checks[0].name == "citation_has_reference"
    assert f.checks[0].result is False
    # anchor must be mechanically grounded: quote is verbatim at its span
    assert f.anchor is not None and f.anchor.span is not None
    assert text[f.anchor.span.start : f.anchor.span.end] == f.anchor.quote
    assert "Marlowe" in f.anchor.quote


def test_unlinked_numeric_marker_becomes_finding():
    text, _ = load("ieee")
    ext = extract_citations(text)
    assert [f.target for f in ext.findings] == ["[7]"]


def test_claim_sentence_covers_marker():
    text, _ = load("apa")
    for m in extract_citations(text).mentions:
        assert m.claim_span.start <= m.span.start
        assert m.claim_span.end >= m.span.end
        assert text[m.claim_span.start : m.claim_span.end] == m.claim_text


def test_no_reference_section_degrades_to_unlinked():
    text = (
        "Prior work shows the effect is robust (Imaginary, 2020).\n\n"
        "We build on that result here."
    )
    ext = extract_citations(text)
    assert ext.ref_region is None
    assert ext.references == []
    assert len(ext.mentions) == 1
    assert len(ext.findings) == 1


# ------------------------------------------------------- precision / recall


def score_doc(name: str) -> dict[str, dict[str, int]]:
    """TP/FP/FN tallies for mentions, references, and links on one doc."""
    text, labels = load(name)
    ext = extract_citations(text)

    gold_mentions = []
    for gm in labels["mentions"]:
        start = nth_offset(text, gm["marker"], gm["occurrence"])
        gold_mentions.append((start, start + len(gm["marker"]), gm["links"]))

    m_tp = m_fn = 0
    matched_pred: set[int] = set()
    for start, end, _links in gold_mentions:
        hit = False
        for i, pm in enumerate(ext.mentions):
            if overlaps(start, end, pm.span.start, pm.span.end):
                matched_pred.add(i)
                hit = True
        m_tp += hit
        m_fn += not hit
    m_fp = len(ext.mentions) - len(matched_pred)

    gold_keys = {gr["key"] for gr in labels["references"]}
    pred_keys = {r.key for r in ext.references}
    r_tp = len(gold_keys & pred_keys)
    r_fp = len(pred_keys - gold_keys)
    r_fn = len(gold_keys - pred_keys)

    l_tp = l_fn = 0
    for start, end, links in gold_mentions:
        overlapping = [
            c
            for c in ext.citations
            if overlaps(start, end, c.mention.span.start, c.mention.span.end)
        ]
        for key in links:
            ok = any(
                (key is None and c.reference is None)
                or (key is not None and c.reference is not None and c.reference.key == key)
                for c in overlapping
            )
            l_tp += ok
            l_fn += not ok
    gold_link_count = sum(len(gm[2]) for gm in gold_mentions)
    l_fp = len(ext.citations) - gold_link_count if len(ext.citations) > gold_link_count else 0

    return {
        "mentions": {"tp": m_tp, "fp": m_fp, "fn": m_fn},
        "references": {"tp": r_tp, "fp": r_fp, "fn": r_fn},
        "links": {"tp": l_tp, "fp": l_fp, "fn": l_fn},
    }


def pr(t: dict[str, int]) -> tuple[float, float]:
    p = t["tp"] / (t["tp"] + t["fp"]) if t["tp"] + t["fp"] else 0.0
    r = t["tp"] / (t["tp"] + t["fn"]) if t["tp"] + t["fn"] else 0.0
    return p, r


def test_precision_recall_on_labeled_fixtures():
    totals = {
        kind: {"tp": 0, "fp": 0, "fn": 0} for kind in ("mentions", "references", "links")
    }
    lines = []
    for name in DOCS:
        tallies = score_doc(name)
        for kind, t in tallies.items():
            for k in t:
                totals[kind][k] += t[k]
            p, r = pr(t)
            lines.append(f"{name:8s} {kind:10s} P={p:.2f} R={r:.2f} {t}")
    print("\n" + "\n".join(lines))
    for kind, t in totals.items():
        p, r = pr(t)
        print(f"TOTAL    {kind:10s} P={p:.2f} R={r:.2f} {t}")
        assert p >= 0.90, f"{kind} precision {p:.2f} below 0.90: {t}"
        assert r >= 0.90, f"{kind} recall {r:.2f} below 0.90: {t}"


@pytest.mark.parametrize("name", DOCS)
def test_fixture_reference_fields_match_labels(name: str):
    text, labels = load(name)
    refs = {r.key: r for r in extract_citations(text).references}
    for gr in labels["references"]:
        if gr["key"] not in refs:
            continue  # counted by the P/R test, not here
        r = refs[gr["key"]]
        assert r.year == gr["year"]
        if "doi" in gr:
            assert r.doi == gr["doi"]
        if "arxiv_id" in gr:
            assert r.arxiv_id == gr["arxiv_id"]
