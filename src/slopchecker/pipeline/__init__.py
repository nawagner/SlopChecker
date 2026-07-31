"""Check registry + tiered runner (#5). See registry.py for how to add a check."""

from slopchecker.pipeline.registry import (
    TIER_ORDER,
    CheckContext,
    CheckOutput,
    RegisteredCheck,
    all_checks,
    discover,
    register,
    select_checks,
)
from slopchecker.pipeline.runner import run_checks

__all__ = [
    "TIER_ORDER",
    "CheckContext",
    "CheckOutput",
    "RegisteredCheck",
    "all_checks",
    "discover",
    "register",
    "run_checks",
    "select_checks",
]
