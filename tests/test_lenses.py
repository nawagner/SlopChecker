"""Tests for the lens prompt-pack loader and the claims lens (#13).

The generic tests iterate over every lens in the package, so a teammate
adding a new lens .md gets format + quote-anchoring validation for free.
"""

import json

import pytest

from slopchecker.lenses import (
    LensFormatError,
    LensNotFoundError,
    list_lenses,
    load_lens,
)

CLAIM_TYPES = {"capability", "outcome", "timeline", "prior-work", "impact"}
CLAIM_KEYS = {"id", "type", "page", "quote", "quantitative", "citation"}


# ---------------------------------------------------------------- loader


def test_list_lenses_includes_claims_not_readme():
    lenses = list_lenses()
    assert "claims" in lenses
    assert "README" not in lenses


def test_load_missing_lens_raises():
    with pytest.raises(LensNotFoundError):
        load_lens("no-such-lens")


def test_malformed_lens_raises(tmp_path):
    bad = tmp_path / "bad.md"
    bad.write_text("# No frontmatter here\n\njust prose\n", encoding="utf-8")
    with pytest.raises(LensFormatError):
        load_lens("bad", directory=tmp_path)


def test_missing_required_section_raises(tmp_path):
    bad = tmp_path / "partial.md"
    bad.write_text(
        "---\nid: partial\n---\n\n# Partial lens\n\n## System prompt\n\nhi\n",
        encoding="utf-8",
    )
    with pytest.raises(LensFormatError):
        load_lens("partial", directory=tmp_path)


def test_lens_as_dict_roundtrips_meta():
    lens = load_lens("claims")
    d = lens.as_dict()
    assert d["id"] == "claims"
    assert d["meta"] == dict(lens.meta)
    assert set(d["sections"]) == set(lens.sections)


# ------------------------------------------------- generic lens contract


@pytest.mark.parametrize("name", list_lenses())
def test_lens_has_required_sections(name):
    lens = load_lens(name)
    assert lens.system_prompt.strip()
    assert lens.output_format.strip()
    assert lens.example_input.strip()
    assert lens.example_output.strip()


@pytest.mark.parametrize("name", list_lenses())
def test_lens_example_output_is_valid_json(name):
    lens = load_lens(name)
    json.loads(lens.example_output)


@pytest.mark.parametrize("name", list_lenses())
def test_lens_example_quotes_are_verbatim(name):
    """Every `quote` in a lens's few-shot output must be a verbatim,
    contiguous substring of the few-shot input. Quote-anchoring is a
    repo-wide design decision; the few-shot must model it exactly."""
    lens = load_lens(name)
    payload = json.loads(lens.example_output)
    quotes = _collect_quotes(payload)
    assert quotes, f"lens {name!r} example output has no quote fields"
    for quote in quotes:
        assert quote in lens.example_input, f"not verbatim in input: {quote!r}"


def _collect_quotes(node):
    found = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "quote" and isinstance(value, str):
                found.append(value)
            else:
                found.extend(_collect_quotes(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_collect_quotes(item))
    return found


# ------------------------------------------------------- claims lens


def test_claims_meta():
    lens = load_lens("claims")
    assert lens.id == "claims"
    assert lens.meta["issue"] == "13"
    assert lens.meta["output"] == "json"


def test_claims_example_claims_are_well_formed():
    lens = load_lens("claims")
    claims = json.loads(lens.example_output)["claims"]
    assert claims
    seen_ids = set()
    for claim in claims:
        assert set(claim) == CLAIM_KEYS
        assert claim["type"] in CLAIM_TYPES
        assert isinstance(claim["page"], int) and claim["page"] >= 1
        assert isinstance(claim["quantitative"], bool)
        assert claim["citation"] is None or isinstance(claim["citation"], str)
        assert claim["id"] not in seen_ids
        seen_ids.add(claim["id"])


def test_claims_example_teaches_unsourced_quantitative():
    """The demo-worthy failure mode — a quantitative promise with no
    citation — must appear in the few-shot so the model learns to keep
    `citation: null` honest rather than inventing a source."""
    lens = load_lens("claims")
    claims = json.loads(lens.example_output)["claims"]
    assert any(c["quantitative"] and c["citation"] is None for c in claims)
    assert any(c["quantitative"] and c["citation"] is not None for c in claims)
