"""Structured registry clients — ProPublica, OpenAlex, ORCID (#18).

Each client implements ``RegistryLookup`` (see ``.base``) and can be
tested and skipped independently.
"""

from slopchecker.background.structured.base import RegistryLookup

__all__ = ["RegistryLookup"]
