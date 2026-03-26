"""
Structured query lifecycle logger.

Emits one JSON log line per request through the /query/plan (and /query/answer)
pipeline so that plan quality, execution outcomes, and answer generation can be
audited and analysed after the fact.

Log schema (all fields guaranteed present, None where not applicable):
  {
    "event":            "QUERY_LIFECYCLE",
    "query":            <original NL question>,
    "plan_type":        <lookup|traverse|filter|aggregate|path|anomaly|null>,
    "plan_entity":      <start_entity or null>,
    "plan_target":      <target_entity or null>,
    "plan_confidence":  <HIGH|MEDIUM|LOW|null>,
    "plan_filters":     <number of filter conditions>,
    "execution_status": <success|empty|error>,
    "execution_type":   <type field from result, or null>,
    "result_count":     <record_count / flagged_count / row_count, or null>,
    "answer_length":    <character count of LLM answer>,
    "planner":          <"v1"|"full"|"fallback">,
    "guardrail_hit":    <true if blocked by guardrails>,
  }
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger("dodge_ai.query")


def log_query_lifecycle(
    *,
    query: str,
    plan: Any = None,
    execution_result: Optional[dict[str, Any]] = None,
    answer: str = "",
    planner: str = "full",
    guardrail_hit: bool = False,
) -> None:
    """
    Emit a single structured JSON log entry for a completed query lifecycle.

    Args:
        query:            The sanitised natural-language question.
        plan:             The GraphQueryPlan (or ParsedGraphQuery) produced by the planner.
        execution_result: The serialised GraphExecResult dict.
        answer:           The final natural-language answer string.
        planner:          Which planner produced the plan: "v1", "full", or "fallback".
        guardrail_hit:    True if the guardrail blocked the query before planning.
    """
    result = (execution_result or {}).get("result") or {}

    # Extract a meaningful record count from whatever result type was returned
    result_count: Optional[int] = None
    rtype = result.get("type")
    if rtype == "lookup":
        result_count = result.get("record_count")
    elif rtype == "traverse":
        result_count = result.get("target_record_count") or len(result.get("target_records", []))
    elif rtype == "filter":
        result_count = result.get("record_count")
    elif rtype == "aggregate":
        result_count = result.get("row_count") or (1 if result.get("value") is not None else None)
    elif rtype == "path":
        result_count = result.get("path_length")
    elif rtype == "anomaly":
        result_count = result.get("flagged_count")

    entry = {
        "event":            "QUERY_LIFECYCLE",
        "query":            query,
        "plan_type":        getattr(plan, "type", None),
        "plan_entity":      getattr(plan, "start_entity", None),
        "plan_target":      getattr(plan, "target_entity", None),
        "plan_confidence":  str(getattr(plan, "confidence", "")) or None,
        "plan_filters":     len(getattr(plan, "filters", None) or []),
        "execution_status": (execution_result or {}).get("status"),
        "execution_type":   rtype or None,
        "result_count":     result_count,
        "answer_length":    len(answer),
        "planner":          planner,
        "guardrail_hit":    guardrail_hit,
    }

    logger.info("QUERY_LIFECYCLE %s", json.dumps(entry, default=str))
