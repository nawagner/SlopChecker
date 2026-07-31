"""Deterministic-tier checks (Nick's package per CLAUDE.md).

Seeded by #15 (tagging). ``pipeline.registry.discover()`` imports every module
in here for its ``@register`` side effects, so a new check is one new file — no
central list to edit.

Nothing in this tier needs an LLM or an API key: a dumb script with (at most) a
network connection runs all of it.

Registered checks:

- ``tagging.py`` (#15) — topics, document type, submitter type. Offline.
- ``identifiers_valid.py`` (#8) — DOI / arXiv / ISBN / URL well-formedness.
  Offline.
- ``doi_resolution.py`` (#8) — every well-formed DOI, through doi.org.
- ``url_resolution.py`` (#8) — plain reference URLs, counted separately.
- ``metadata_match.py`` (#9) — cited metadata vs. the canonical record.

Support modules, which register nothing: ``identifiers`` (pure validation),
``cache`` (disk cache, ``--no-cache``), ``net`` (HTTP + outcome
classification), ``providers`` (Crossref / OpenAlex / arXiv behind one
interface), ``compare`` (fuzzy grading), ``refs`` (shared reference extraction
and anchoring), ``resolution`` (the engine the two resolution checks share).

Wording discipline (#8's notes): a dead link is evidence of a dead link.
Nothing in here says "fabricated" — that inference belongs to the human
reading the report with the other signals in hand. Dedup (#14) still to come.
"""

from slopchecker.checks.identifiers import (
    Identifier,
    identifiers_in,
    normalize_doi,
    valid_arxiv_id,
    valid_doi,
    valid_isbn,
    valid_url,
)

__all__ = [
    "Identifier",
    "identifiers_in",
    "normalize_doi",
    "valid_arxiv_id",
    "valid_doi",
    "valid_isbn",
    "valid_url",
]
