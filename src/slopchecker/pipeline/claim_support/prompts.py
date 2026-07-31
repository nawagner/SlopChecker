"""Prompt assembly + JSON schemas for the claim-support check (#11).

Kept separate from the API call per the #37 design comment: a future
"reframed" prompt (or a Ladder rung) is a sibling function, not an edit to
the call site. Both prompts are text-only functions of their inputs; no
model client and no I/O in this module.

Ground rules baked into the prompts:

- The model MUST return a passage verbatim from the source (mechanically
  verified against the retrieved text before the finding reaches the
  report). Reject anything else.
- The judge returns a closed enum (matches ``models.Verdict``) — no free
  text; the check ignores prose fields and reads only the verdict + passage
  + confidence.
- The refuter's default is to refute — on uncertainty, kill the finding
  rather than let it through (per #11's "bias toward silence").
"""

from __future__ import annotations

# --- JSON schemas ---------------------------------------------------------

# Note on the enum values: kept identical to ``slopchecker.models.Verdict``
# so ``Verdict(payload["verdict"])`` never raises. If you change one, change
# the other in the same PR.
JUDGE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "verdict": {
            "type": "string",
            "enum": [
                "supported",
                "overstated",
                "unsupported",
                "contradicted",
                "unverifiable",
            ],
        },
        "supporting_passage": {
            "type": "string",
            "description": (
                "Verbatim contiguous excerpt from the SOURCE TEXT that supports the "
                "verdict. MUST be copy-pasted from the source — no paraphrase, no "
                "ellipsis, no smoothed punctuation. If no such passage exists (e.g. "
                "verdict is 'unsupported' or 'unverifiable'), return an empty string."
            ),
        },
        "confidence": {
            "type": "number",
            "description": "Judge's own confidence in the verdict, 0.0 to 1.0.",
        },
        "reasoning": {
            "type": "string",
            "description": "One-sentence rationale. Not read by downstream code.",
        },
    },
    "required": ["verdict", "supporting_passage", "confidence", "reasoning"],
    "additionalProperties": False,
}


REFUTER_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "outcome": {
            "type": "string",
            "enum": ["upheld", "softened", "refuted"],
            "description": (
                "'refuted' if the judge's verdict is wrong or unsupported by the "
                "quoted passage; 'softened' if it has a real core but overstates; "
                "'upheld' if it survives your best attempt to kill it."
            ),
        },
        "reasoning": {
            "type": "string",
            "description": "One-sentence rationale. Not read by downstream code.",
        },
    },
    "required": ["outcome", "reasoning"],
    "additionalProperties": False,
}


# --- Prompt bodies -------------------------------------------------------

_JUDGE_SYSTEM = """\
You are evaluating whether a source paper supports the claim that a proposal
attributes to it. You are the FIRST reader; a skeptical refuter will read
your judgment next and try to knock it down. Your job is to be right, not
to be agreeable.

Verdicts (choose exactly one):
- supported: the source clearly supports the claim as written.
- overstated: the source supports a weaker version — the claim is directionally
  right but stronger, broader, or more definitive than the source justifies.
- unsupported: the source neither supports nor contradicts the claim; it does
  not address what the claim asserts.
- contradicted: the source states the opposite, or supports a materially
  different conclusion.
- unverifiable: the retrieved source text is insufficient to judge — too
  short, off-topic, or missing the relevant section.

Rules — hard constraints:
1. `supporting_passage` MUST be a verbatim, contiguous substring of the
   SOURCE TEXT below. Not the proposal text, not a paraphrase, not smoothed
   punctuation. If the source has no passage that supports your verdict —
   including all 'unsupported' and 'unverifiable' verdicts — return an
   empty string.
2. Never quote from the proposal. The proposal is the CLAIM under scrutiny;
   only the source can support or refute it.
3. `confidence` reflects your judgment quality, not the strength of the
   claim. Values below 0.6 will be discarded silently downstream.
4. A false accusation of misrepresenting a source is more costly than a
   missed one. When in doubt between 'supported' and 'overstated', pick
   'supported'. When in doubt between 'unsupported' and 'unverifiable',
   pick 'unverifiable'.
5. Output exactly one JSON object matching the schema. No commentary, no
   markdown fences.
"""


_REFUTER_SYSTEM = """\
You are a skeptical referee. Another reader (a different context, possibly
a different model) produced the verdict below about a claim and the source
it cites. Your job is to try to REFUTE the verdict, not to be agreeable.

Check, in order:
1. Does the quoted supporting_passage appear verbatim in the SOURCE TEXT,
   and does it actually say what the judge claims?
2. If the judge's verdict is a concern (overstated / unsupported /
   contradicted): does the source in fact contain other passages that would
   have supported the claim? If so, the judge missed context and the
   verdict should be refuted.
3. Is the judgment generic reviewer boilerplate that would apply to any
   proposal, rather than something specific to THIS claim and THIS source?
4. Is the stated severity justified given what the source says?

Outcomes:
- refuted: the judge misreads the source, missed a supporting passage
  elsewhere in the source, or the verdict is boilerplate. When in doubt
  on (1) or (2), lean 'refuted' — silence is cheaper than a false accusation.
- softened: the verdict has a real core but overstates severity or scope.
- upheld: the verdict survives your best attempt to kill it.

Output exactly one JSON object matching the schema. No commentary, no
markdown fences.
"""


def judge_prompt(*, claim: str, citation_marker: str, source_text: str) -> tuple[str, str]:
    """Return (system, user) for the judge turn."""
    marker = citation_marker or "(unmarked reference)"
    user = (
        f"# CLAIM\n\n"
        f"The proposal makes the following claim, citing {marker}:\n\n"
        f"{claim.strip()}\n\n"
        f"# SOURCE TEXT (from the cited reference)\n\n"
        f"{source_text.strip()}\n"
    )
    return _JUDGE_SYSTEM, user


def refuter_prompt(
    *,
    claim: str,
    citation_marker: str,
    source_text: str,
    judge_verdict: str,
    judge_passage: str,
    judge_reasoning: str,
) -> tuple[str, str]:
    """Return (system, user) for the refuter turn."""
    marker = citation_marker or "(unmarked reference)"
    user = (
        f"# CLAIM\n\n"
        f"The proposal makes the following claim, citing {marker}:\n\n"
        f"{claim.strip()}\n\n"
        f"# SOURCE TEXT (from the cited reference)\n\n"
        f"{source_text.strip()}\n\n"
        f"# JUDGE'S VERDICT\n\n"
        f"verdict: {judge_verdict}\n"
        f"supporting_passage: {judge_passage!r}\n"
        f"reasoning: {judge_reasoning}\n"
    )
    return _REFUTER_SYSTEM, user
