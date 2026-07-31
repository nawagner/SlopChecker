"""LLM topic classification: fit the document into the fixed taxonomy (#15 upgrade).

The deterministic ``tagging`` check matches taxonomy phrases literally, which
misses every document that talks about a topic without using the exact
vocabulary. This check asks Claude to classify the document into the SAME
fixed topic set (single source of truth: ``checks.tagging.load_taxonomy()``),
so the two tiers agree on vocabulary and the batch summary can group on
either. The model may not invent topics: anything outside the set maps to
``other``.

Same degrade discipline as every LLM check: no ``ANTHROPIC_API_KEY`` →
skipped gap row, transport failure → errored row, never a crash. Evidence
quotes that fail verbatim quotecheck are dropped from the anchor (the
classification survives; the bad quote does not reach the report).
"""

from __future__ import annotations

import json

from slopchecker import config as _config
from slopchecker.checks.tagging import load_taxonomy
from slopchecker.models import Anchor, CheckResult, Finding, FlattenedDoc, LedgerRow
from slopchecker.pipeline.lens_runtime import (
    AnthropicClient,
    LensRunConfig,
    TransportError,
    _call_with_retry,
    _parse_json_strict,
)
from slopchecker.pipeline.registry import CheckContext, CheckOutput, register

_MAX_SECONDARY = 2

_SYSTEM_TEMPLATE = """\
You are classifying a document submitted to a funding organization into a \
fixed topic taxonomy so program staff can route and group submissions.

The ONLY valid topics are:

{topic_lines}
- other: none of the above fits

Rules — all hard constraints:

1. Pick exactly one `primary` topic from the list. If nothing fits, use \
"other". Never invent a topic name.
2. List up to {max_secondary} `secondary` topics from the same list, only \
when the document substantively engages them. Empty list is the common case.
3. Every topic entry carries `confidence` (0.0-1.0) and `quote` — a \
verbatim, contiguous substring of the document that best evidences the \
topic. No paraphrase, no ellipsis: quotes are mechanically checked against \
the source and discarded on any mismatch.
4. Classify the document's subject matter, not its quality. This is \
routing metadata, not a judgment.
5. Output exactly one JSON object, no commentary, no markdown fences:

{{"primary": {{"topic": "...", "confidence": 0.0, "quote": "..."}},
 "secondary": [{{"topic": "...", "confidence": 0.0, "quote": "..."}}]}}
"""


def _system_prompt(topics: list[str]) -> str:
    topic_lines = "\n".join(f"- {t}" for t in topics)
    return _SYSTEM_TEMPLATE.format(topic_lines=topic_lines, max_secondary=_MAX_SECONDARY)


def _gap(status: str, reason: str) -> CheckOutput:
    return CheckOutput(
        ledger=[
            LedgerRow(
                check="topic_classification",
                label="Topic classification (LLM)",
                status=status,
                reason=reason,
            )
        ]
    )


def _entry(item: object, valid: set[str]) -> tuple[str, float, str | None] | None:
    """Validate one model-emitted topic entry to (topic, confidence, quote)."""
    if not isinstance(item, dict):
        return None
    topic = item.get("topic")
    if topic not in valid:
        return None
    try:
        confidence = min(1.0, max(0.0, float(item.get("confidence", 0.0))))
    except (TypeError, ValueError):
        return None
    quote = item.get("quote")
    return topic, confidence, quote if isinstance(quote, str) and quote else None


@register(
    id="topic_classification",
    name="Topic classification (LLM)",
    tier="llm",
    needs_network=True,
    timeout_s=90.0,
)
def topic_classification(doc: FlattenedDoc, ctx: CheckContext) -> CheckOutput:
    try:
        api_key = _config.require("ANTHROPIC_API_KEY")
    except _config.MissingCredential as exc:
        return _gap("skipped", f"missing {exc.env_var}")

    topics = list(load_taxonomy()["topics"].keys())
    valid = set(topics) | {"other"}
    run_config = LensRunConfig()
    model = run_config.model or _config.llm_model()

    try:
        raw = _call_with_retry(
            AnthropicClient(api_key=api_key),
            _system_prompt(topics),
            doc.text,
            run_config,
            model,
        )
        payload = _parse_json_strict(raw)
    except TransportError as exc:
        return _gap("errored", f"topic classification transport error: {exc}")
    except (json.JSONDecodeError, ValueError) as exc:
        return _gap("errored", f"topic classification output not valid json: {exc}")

    primary = _entry(payload.get("primary"), valid)
    if primary is None:
        return _gap("errored", "topic classification returned no valid primary topic")

    secondary = [
        e
        for item in (payload.get("secondary") or [])[:_MAX_SECONDARY]
        if (e := _entry(item, valid)) is not None
    ]

    primary_topic, primary_conf, primary_quote = primary
    detail = f"primary: {primary_topic} ({primary_conf:.2f})"
    if secondary:
        detail += "; secondary: " + ", ".join(f"{t} ({c:.2f})" for t, c, _ in secondary)

    findings = []
    for rank, (topic, confidence, quote) in enumerate([primary, *secondary]):
        # Quotecheck: an anchor only ships if the quote is verbatim in the doc.
        anchor = Anchor(quote=quote) if quote and quote in doc.text else None
        findings.append(
            Finding(
                id=f"topic-{'primary' if rank == 0 else f'secondary-{rank}'}",
                target="topic",
                label=f"Topic: {topic}",
                anchor=anchor,
                checks=[
                    CheckResult(name="topic_confidence", result=round(confidence, 2)),
                ],
                evidence={
                    "topic": topic,
                    "role": "primary" if rank == 0 else "secondary",
                    "model": model,
                    "taxonomy_topics": topics,
                },
            )
        )

    return CheckOutput(
        ledger=[
            LedgerRow(
                check="topic_classification",
                label="Topic classification (LLM)",
                result=round(primary_conf, 2),
                detail=detail,
            )
        ],
        findings=findings,
    )
