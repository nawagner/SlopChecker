"""Structured and open-web background lookups on an application's entities (#18).

The shared shape (``BackgroundReport``, ``Entity``, ``BackgroundFinding``,
``EntityNotFound``, ``BackgroundGap``) lives on ``slopchecker.models``.

Submodules:

- ``extract``: rules-first entity extraction from a ``FlattenedDoc``.
- ``structured``: typed clients per public registry (ProPublica, OpenAlex,
  ORCID) behind a common ``RegistryLookup`` protocol, plus the top-level
  runner.
"""

from slopchecker.background.extract import extract_entities

__all__ = ["extract_entities"]
