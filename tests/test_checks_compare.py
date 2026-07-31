"""Fuzzy metadata comparison (#9), offline.

These tests are the tuning record for the thresholds. The load-bearing cases
are the *negative* ones: ordinary citation sloppiness must not grade as
``different``, because the report's credibility dies the first time it calls
an abbreviated venue a fabricated source.
"""

from __future__ import annotations

import pytest

from slopchecker.checks.compare import (
    Grade,
    compare,
    grade_author,
    grade_venue,
    grade_year,
    normalize,
    title_similarity,
)
from slopchecker.checks.providers import SourceRecord
from slopchecker.models import Span
from slopchecker.pipeline.citations import ReferenceEntry

CANONICAL = SourceRecord(
    provider="crossref",
    doi="10.1038/nature12373",
    title="Nanometre-scale thermometry in a living cell",
    authors=("G. Kucsko", "P. C. Maurer", "N. Y. Yao"),
    surnames=("Kucsko", "Maurer", "Yao"),
    year=2013,
    venue="Nature",
    type="journal-article",
)


def _ref(**kwargs) -> ReferenceEntry:
    fields = {
        "key": "1",
        "raw": "placeholder",
        "span": Span(start=0, end=11),
        "authors": ["G. Kucsko"],
        "year": 2013,
        "title": "Nanometre-scale thermometry in a living cell",
        "venue": "Nature",
        "doi": "10.1038/nature12373",
    }
    fields.update(kwargs)
    return ReferenceEntry(**fields)


def test_normalize_strips_accents_case_and_punctuation() -> None:
    assert normalize("Zürich: A Réview, Vol. 2!") == normalize("zurich a review vol 2")


def test_identical_titles_score_one() -> None:
    assert title_similarity(CANONICAL.title, CANONICAL.title) == 1.0


def test_truncated_subtitle_is_not_a_different_paper() -> None:
    """ "Title" vs "Title: the long subtitle" — a citation that dropped the tail."""
    score = title_similarity(
        "Deep learning for protein folding",
        "Deep learning for protein folding: a decade in review",
    )
    assert score >= 0.90


def test_genuinely_different_titles_score_low() -> None:
    score = title_similarity(
        "Adaptive resonance in distributed civic sensing arrays",
        "Nanometre-scale thermometry in a living cell",
    )
    assert score < 0.70


@pytest.mark.parametrize(
    "cited,canonical,expected",
    [
        (2013, 2013, Grade.matches),
        (2012, 2013, Grade.minor),  # online-first vs issue date
        (2014, 2013, Grade.minor),
        (2019, 2013, Grade.different),
        (None, 2013, Grade.unknown),
    ],
)
def test_grade_year(cited, canonical, expected) -> None:
    assert grade_year(cited, canonical) is expected


@pytest.mark.parametrize(
    "surname,expected",
    [
        ("Kucsko", Grade.matches),
        ("Yao", Grade.minor),  # real author, listed first by mistake
        ("Ortega", Grade.different),
        (None, Grade.unknown),
    ],
)
def test_grade_author(surname, expected) -> None:
    assert grade_author(surname, CANONICAL) is expected


@pytest.mark.parametrize(
    "cited,canonical,expected",
    [
        ("Nature", "Nature", Grade.matches),
        ("J. Am. Chem. Soc.", "Journal of the American Chemical Society", Grade.matches),
        (
            "Proc. Natl. Acad. Sci.",
            "Proceedings of the National Academy of Sciences",
            Grade.matches,
        ),
        ("Nature", "Journal of Civic Infrastructure", Grade.different),
        (None, "Nature", Grade.unknown),
    ],
)
def test_grade_venue_tolerates_abbreviation(cited, canonical, expected) -> None:
    assert grade_venue(cited, canonical) is expected


def test_correct_citation_matches() -> None:
    match = compare(_ref(), CANONICAL)
    assert match.grade is Grade.matches
    assert match.summary() == "Cited metadata matches the canonical record."


def test_ieee_author_shape_is_not_read_as_sloppiness() -> None:
    """ "G. Kucsko" must yield the surname "Kucsko", not "G. Kucsko".

    Regression: splitting on the comma graded every IEEE-style reference in
    the fixture as a minor discrepancy against its own correct source.
    """
    assert compare(_ref(authors=["G. Kucsko"]), CANONICAL).grade is Grade.matches
    assert compare(_ref(authors=["Kucsko, G."]), CANONICAL).grade is Grade.matches


def test_abbreviated_venue_alone_does_not_downgrade() -> None:
    """Venue never decides on its own — honest citations abbreviate constantly."""
    match = compare(_ref(venue="Nat."), CANONICAL)
    assert match.grade is Grade.matches


def test_wrong_year_is_minor_not_fabrication() -> None:
    match = compare(_ref(year=2012), CANONICAL)
    assert match.grade is Grade.minor
    assert "minor" in match.summary().lower()


def test_real_doi_with_invented_title_is_a_different_work() -> None:
    """The #9 headline case: a real identifier on a made-up reference."""
    match = compare(
        _ref(
            title="Adaptive resonance in distributed civic sensing arrays",
            authors=["A. Ortega"],
            year=2019,
            venue="Journal of Civic Infrastructure",
        ),
        CANONICAL,
    )
    assert match.grade is Grade.different
    assert match.is_different_work
    assert "different work" in match.summary()


# Scores 0.875: close enough to be a sloppy citation, far enough to be the
# follow-up paper. Exactly the band where the author has to break the tie.
_UNCERTAIN_TITLE = "Nanometre scale thermometry of a living cell nucleus"


def test_uncertain_title_plus_wrong_author_is_a_different_work() -> None:
    match = compare(_ref(title=_UNCERTAIN_TITLE, authors=["Q. Nobody"]), CANONICAL)
    assert match.grade is Grade.different


def test_uncertain_title_with_right_author_is_only_minor() -> None:
    assert compare(_ref(title=_UNCERTAIN_TITLE), CANONICAL).grade is Grade.minor


def test_a_superset_title_is_not_a_free_match() -> None:
    """Containment overlap scored "X of a living cell nucleus" a perfect 1.0
    against "X in a living cell" — a follow-up study reading as the original."""
    assert title_similarity(_UNCERTAIN_TITLE, CANONICAL.title) < 0.90


def test_no_canonical_record_is_unknown_not_a_failure() -> None:
    """Gray literature: our coverage gap, never the applicant's defect."""
    match = compare(_ref(title="Handbook of Civic Resilience"), None)
    assert match.grade is Grade.unknown
    assert not match.is_different_work
    assert match.canonical is None


def test_unparsed_title_is_unknown() -> None:
    assert compare(_ref(title=None), CANONICAL).grade is Grade.unknown


def test_evidence_carries_the_canonical_record() -> None:
    """A human must be able to check the call without re-running anything."""
    evidence = compare(_ref(year=2012), CANONICAL).as_evidence()
    assert evidence["grade"] == "minor"
    assert evidence["canonical"]["title"] == CANONICAL.title
    assert evidence["canonical"]["provider"] == "crossref"
    assert evidence["fields"]["year"] == "minor"
    assert 0.0 <= evidence["title_similarity"] <= 1.0
