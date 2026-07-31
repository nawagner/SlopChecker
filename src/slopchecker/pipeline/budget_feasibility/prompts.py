"""Prompt assembly + JSON schema for the budget-feasibility check (#17).

Kept separate from the API call per the #37 design comment: a future
reworded prompt (or a Ladder rung) is a sibling function, not an edit to
the call site. All prompt bodies are text-only functions of their inputs;
no model client and no I/O in this module.

Ground rules baked into the schema:

- The lens returns a single JSON object matching ``LENS_OUTPUT_SCHEMA``.
  ``additionalProperties`` is closed everywhere so a model that invents
  a field fails schema validation server-side before it costs a
  downstream evaluator branch.
- Every ``quote`` field is a string; the lens's markdown rules make it
  a verbatim substring of the document text. The orchestrator runs
  quotecheck at parse time — hallucinated quotes drop their items
  before the evaluator runs.
- Every nullable field the lens can legitimately omit (``period_yrs``,
  ``fringe_rate``, ``timeframe_yrs``, etc.) is typed ``["number",
  "null"]`` so the schema forces the model to say ``null`` explicitly
  rather than dropping the key. That preserves the "don't invent
  nullables" rule from the lens markdown.
"""

from __future__ import annotations

from slopchecker.lenses import Lens

# --- JSON schema for the lens's extraction output --------------------------

# Enums live here so a change to the lens's role/category vocabulary
# breaks the schema first (and thus the orchestrator, loudly) — rather
# than silently allowing model output the evaluator can't map.
_ROLE_ENUM = [
    "pi",
    "co_pi",
    "senior_scientist",
    "postdoc",
    "grad_student",
    "research_assistant",
    "admin",
    "technician",
    "consultant",
    "other",
]

_CATEGORY_ENUM = [
    "equipment",
    "travel",
    "supplies",
    "indirect",
    "subcontract",
    "other",
]


LENS_OUTPUT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "project": {
            "type": "object",
            "properties": {
                "stated_total_usd": {"type": ["number", "null"]},
                "duration_yrs": {"type": ["number", "null"]},
            },
            "required": ["stated_total_usd", "duration_yrs"],
            "additionalProperties": False,
        },
        "personnel_lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "page": {"type": "integer"},
                    "quote": {"type": "string"},
                    "amount_usd": {"type": "number"},
                    "period_yrs": {"type": ["number", "null"]},
                    "fringe_rate": {"type": ["number", "null"]},
                    "indirect_rate": {"type": ["number", "null"]},
                    "roles_named": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "role": {"type": "string", "enum": _ROLE_ENUM},
                                "count": {"type": "integer"},
                                "fte_fraction": {"type": "number"},
                            },
                            "required": ["role", "count", "fte_fraction"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": [
                    "id",
                    "page",
                    "quote",
                    "amount_usd",
                    "period_yrs",
                    "fringe_rate",
                    "indirect_rate",
                    "roles_named",
                ],
                "additionalProperties": False,
            },
        },
        "non_personnel_lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "page": {"type": "integer"},
                    "quote": {"type": "string"},
                    "amount_usd": {"type": "number"},
                    "category": {"type": "string", "enum": _CATEGORY_ENUM},
                },
                "required": ["id", "page", "quote", "amount_usd", "category"],
                "additionalProperties": False,
            },
        },
        "scope_commitments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "page": {"type": "integer"},
                    "quote": {"type": "string"},
                    "quantity": {"type": "number"},
                    "unit": {"type": "string"},
                    "timeframe_yrs": {"type": ["number", "null"]},
                },
                "required": ["id", "page", "quote", "quantity", "unit", "timeframe_yrs"],
                "additionalProperties": False,
            },
        },
        "pairings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "scope_id": {"type": "string"},
                    "budget_id": {"type": "string"},
                },
                "required": ["scope_id", "budget_id"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "project",
        "personnel_lines",
        "non_personnel_lines",
        "scope_commitments",
        "pairings",
    ],
    "additionalProperties": False,
}


# --- Prompt assembly -------------------------------------------------------


def build_budget_feasibility_prompt(*, lens: Lens, doc_text: str) -> tuple[str, str]:
    """Return (system, user) messages for one lens invocation.

    The lens's own ``system_prompt`` section carries the extraction rules
    (the closed enums, the "no arithmetic" rule, the "don't invent
    nullables" rule); those go verbatim as the ``system`` message.

    The ``user`` message carries a single one-shot — the lens's own
    ``### Input`` and ``### Output`` example — followed by the document
    to analyze. Grounding the one-shot in the same fabricated Meridian
    text the ``test_lenses.py`` quote-verbatim gate exercises keeps the
    model's output shape aligned with what the orchestrator will parse.
    """
    system = lens.system_prompt.strip()
    user = (
        "# EXAMPLE INPUT\n\n"
        f"{lens.example_input.strip()}\n\n"
        "# EXAMPLE OUTPUT\n\n"
        "```json\n"
        f"{lens.example_output.strip()}\n"
        "```\n\n"
        "# DOCUMENT TO ANALYZE\n\n"
        f"{doc_text.strip()}\n"
    )
    return system, user
