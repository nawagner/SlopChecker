"""Deterministic-tier checks (Nick's package per CLAUDE.md).

Seeded by #15 (tagging). ``pipeline.registry.discover()`` imports every module
in here for its ``@register`` side effects, so a new check is one new file — no
central list to edit. DOI resolution, metadata, and dedup (#8+) land here too.
"""
