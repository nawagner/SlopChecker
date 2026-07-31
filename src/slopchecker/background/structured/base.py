"""Common protocol every structured-registry client implements (#18).

Keeps the runner independent of any specific registry: it fans an
``Entity`` out to every ``RegistryLookup`` it was given and aggregates
whatever they return. Each lookup returns a mixed list of
``BackgroundFinding``, ``EntityNotFound``, and ``BackgroundGap`` — a
single call can produce multiple outcomes (e.g. a person hit plus
several ambiguous candidates as gaps).
"""

from __future__ import annotations

from typing import Protocol

from slopchecker.models import (
    BackgroundFinding,
    BackgroundGap,
    Entity,
    EntityNotFound,
)

RegistryLookupResult = BackgroundFinding | EntityNotFound | BackgroundGap


class RegistryLookup(Protocol):
    """One public-registry client.

    ``registry`` is the id used in ``BackgroundFinding.registry`` — e.g.
    ``"propublica"``, ``"openalex"``, ``"orcid"``.

    ``lookup`` returns a list because a single call may produce multiple
    outcomes for one entity (a hit plus gaps for ambiguous candidates,
    or a gap for one sub-endpoint and a hit for another). An empty list
    means "definitely nothing to report from this registry about this
    entity" — the caller decides how to represent that; the client
    should have emitted an ``EntityNotFound`` if that's what it means.
    """

    registry: str

    def lookup(self, entity: Entity) -> list[RegistryLookupResult]: ...
