"""Lens prompt packs: markdown prompt definitions for the LLM tier.

Owned by Dan (+ anyone) — see CLAUDE.md module table. Format spec is in
README.md next to this file; parsing lives in loader.py.
"""

from slopchecker.lenses.loader import (
    LENS_DIR,
    Lens,
    LensError,
    LensFormatError,
    LensNotFoundError,
    list_lenses,
    load_lens,
)

__all__ = [
    "LENS_DIR",
    "Lens",
    "LensError",
    "LensFormatError",
    "LensNotFoundError",
    "list_lenses",
    "load_lens",
]
