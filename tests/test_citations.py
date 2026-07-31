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
        "Prior work shows the effect is robust (Imaginary, 2020).\n\nWe build on that result here."
    )
    ext = extract_citations(text)
    assert ext.ref_region is None
    assert ext.references == []
    assert len(ext.mentions) == 1
    assert len(ext.findings) == 1


# ------------------------------------------- entry-shape tolerance (#126)

# A rendered numbered list keeps its ordinal when printed to PDF, so the
# bracketed key is no longer at the start of the line.
_ORDINAL_PREFIXED = """References

1. [1] https://doi.org/10.1038/s41586-020-2649-2
2. [2] https://doi.org/10.1073/pnas.1517384113
3. [3] https://doi.org/10.7274/jlc90oup
"""

_MARKDOWN_BULLETS = """Sources

- [1] https://doi.org/10.1016/j.cell.2016.07.054
- [2] https://doi.org/10.3353/uuwzix69
"""

_PLAIN_NUMBERED = """References

1. Okafor, J. Prebunking at scale. Journal of Applied Studies, 2021.
2. Reyes, M. Cross-platform replication. Journal of Applied Studies, 2022.
"""


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (_ORDINAL_PREFIXED, 3),
        (_MARKDOWN_BULLETS, 2),
        (_PLAIN_NUMBERED, 2),
    ],
    ids=["ordinal-prefixed", "markdown-bullets", "plain-numbered"],
)
def test_bare_identifier_reference_shapes_parse(text, expected):
    """A bibliography of plain DOI links is still a bibliography (#126)."""
    ext = extract_citations(text)
    assert len(ext.references) == expected


def test_ordinal_prefixed_entries_keep_their_bracketed_key():
    # The key must come from [n], not the list ordinal, so in-text [3] still
    # links to the right entry.
    ext = extract_citations(_ORDINAL_PREFIXED)
    assert [r.key for r in ext.references] == ["1", "2", "3"]


def test_page_break_between_entries_does_not_merge_them():
    # Extracted PDFs put a form feed at the page boundary, mid reference list.
    text = "References\n\n1. [1] https://doi.org/10.1/aaa\n\f2. [2] https://doi.org/10.2/bbb\n"
    assert len(extract_citations(text).references) == 2


def test_sources_heading_is_a_reference_section():
    # Blog posts and think-tank reports say "Sources", not "References".
    ext = extract_citations(_MARKDOWN_BULLETS)
    assert ext.ref_region is not None


# ------------------------------------------------------------- CRLF (#98)


def to_crlf(text: str) -> str:
    assert "\r" not in text, "fixture already has CR — conversion would double it"
    return text.replace("\n", "\r\n")


def test_reference_region_found_crlf():
    text, _ = load("apa")
    crlf = to_crlf(text)
    region = find_reference_region(crlf)
    assert region is not None
    assert "Delacroix" in crlf[region.start : region.end]
    assert "References" not in crlf[region.start : region.end]


@pytest.mark.parametrize("name", DOCS)
def test_crlf_extraction_parity(name):
    """CRLF and LF versions of the same doc extract identically (#98)."""
    text, _ = load(name)
    lf = extract_citations(text)
    crlf_text = to_crlf(text)
    crlf = extract_citations(crlf_text)

    # same references, same parsed fields
    assert [r.key for r in crlf.references] == [r.key for r in lf.references]
    for a, b in zip(crlf.references, lf.references, strict=True):
        assert (a.year, a.doi, a.arxiv_id, a.pages, a.title, a.venue, a.authors) == (
            b.year,
            b.doi,
            b.arxiv_id,
            b.pages,
            b.title,
            b.venue,
            b.authors,
        )

    # same mentions, same linking
    assert [m.marker for m in crlf.mentions] == [m.marker for m in lf.mentions]
    assert [c.reference.key if c.reference else None for c in crlf.citations] == [
        c.reference.key if c.reference else None for c in lf.citations
    ]

    # claim sentences match modulo line endings
    for a, b in zip(crlf.mentions, lf.mentions, strict=True):
        assert a.claim_text.replace("\r\n", "\n") == b.claim_text.replace("\r\n", "\n")

    # same findings — guards the grounding loop below against passing vacuously
    assert [f.target for f in crlf.findings] == [f.target for f in lf.findings]

    # spans stay mechanically grounded in the CRLF text (quote-anchor rule)
    for r in crlf.references:
        assert crlf_text[r.span.start : r.span.end] == r.raw
    for f in crlf.findings:
        assert crlf_text[f.anchor.span.start : f.anchor.span.end] == f.anchor.quote


def test_crlf_blank_line_split_keeps_wrapped_entries_whole():
    """Blank-line-separated entries whose continuation lines start at column 0
    must not fragment under CRLF (`\\n[ \\t]*\\n` never matches `\\r\\n\\r\\n`)."""
    body = (
        "Prior work shows the effect (Vega, 2021).\n"
        "\n"
        "References\n"
        "\n"
        "Vega, L. (2021). First fabricated entry.\n"
        "Journal of Nothing, 3(1), 1-9.\n"
        "\n"
        "Wren, T. (2020). Second fabricated entry.\n"
        "Annals of Nowhere, 7(2), 10-19.\n"
    )
    lf = extract_citations(body)
    crlf = extract_citations(to_crlf(body))
    assert [r.key for r in lf.references] == ["vega-2021", "wren-2020"]
    assert [r.key for r in crlf.references] == ["vega-2021", "wren-2020"]
    assert crlf.citations[0].reference is not None


def test_crlf_claim_sentence_clamped_to_paragraph():
    """A heading with no terminal punctuation must not bleed into the claim
    sentence when paragraphs are CRLF-separated."""
    body = "Section 2 Methods\n\nThe effect replicates (Vega, 2021). More text follows."
    for text in (body, to_crlf(body)):
        (mention,) = extract_citations(text).mentions
        claim = mention.claim_text.replace("\r\n", "\n")
        assert claim == "The effect replicates (Vega, 2021)."


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
    totals = {kind: {"tp": 0, "fp": 0, "fn": 0} for kind in ("mentions", "references", "links")}
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


# ---------------------------------------------------------------------------
# CRLF line endings (#7, found while red-green testing #8/#9)
#
# ingest.normalize() strips CRLF before any loader builds a FlattenedDoc, so
# the CLI and web paths were never affected. But extract_citations() is a
# public entry point, and a caller handing it raw Windows-authored text got
# zero references back with no signal that anything had gone wrong — the
# heading regex's `$` matches before \n without consuming the preceding \r.
# ---------------------------------------------------------------------------

CRLF_DOC = (
    "Prebunking achieves durable inoculation [1]. A second claim follows [2].\r\n"
    "\r\n"
    "References\r\n"
    "\r\n"
    "[1] Smith, J. (2020). A Title. A Venue. doi:10.1234/one\r\n"
    "\r\n"
    "[2] Jones, A. (2021). Another Title. Venue Two. doi:10.1234/two\r\n"
)


def test_crlf_document_parses_identically_to_lf():
    crlf = extract_citations(CRLF_DOC)
    lf = extract_citations(CRLF_DOC.replace("\r\n", "\n"))

    assert len(crlf.references) == len(lf.references) == 2
    assert [r.key for r in crlf.references] == [r.key for r in lf.references]
    assert [r.doi for r in crlf.references] == [r.doi for r in lf.references]
    assert [r.year for r in crlf.references] == [r.year for r in lf.references]
    assert len(crlf.mentions) == len(lf.mentions) == 2
    assert all(c.reference is not None for c in crlf.citations)


def test_crlf_spans_index_the_text_the_caller_passed():
    """The fix tolerates \\r in the patterns rather than rewriting the text —
    rewriting would shift every offset out from under the caller's spans."""
    extraction = extract_citations(CRLF_DOC)
    for ref in extraction.references:
        assert CRLF_DOC[ref.span.start : ref.span.end].startswith("[")
    for mention in extraction.mentions:
        assert CRLF_DOC[mention.span.start : mention.span.end] == mention.marker
