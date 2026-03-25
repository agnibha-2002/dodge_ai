"""
LLM-based graph query planner.

Converts natural language into a GraphQueryPlan by:
  1. Building schema context from the live GraphService
     (entities, relationships, attributes)
  2. Calling Hugging Face Inference API with the schema-aware prompt
  3. Parsing and validating the JSON output against GraphQueryPlan

Supports 6 intent types: lookup, traverse, filter, aggregate, path, anomaly

Falls back to the rule-based parser (query_parser.py) if:
  - HUGGINGFACE_API_KEY is not set
  - LLM returns malformed JSON
  - LLM hallucinates entities not in the schema
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

from app.models.plan import (
    AggregationSpec,
    AnomalySpec,
    GraphQueryPlan,
    PathSpec,
    PlanFilterCondition,
)
from app.models.query import Confidence
from app.services.graph_service import GraphService

logger = logging.getLogger(__name__)

# Ensure HUGGINGFACE_API_KEY is available even when this module is invoked
# directly (tests/scripts), not only through app.main bootstrap.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from app.services.hf_client import hf_chat_completion

# ─────────────────────────────────────────────
# Prompt template (matches the spec exactly)
# ─────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are an LLM-based query planner for a graph-driven data system.

ROLE:
Convert natural language queries into structured, executable graph query specifications.

OBJECTIVE:
Translate the query into a structured plan that supports:
1. lookup
2. traversal
3. filtering
4. aggregation
5. path tracing
6. anomaly detection

OUTPUT FORMAT (JSON only — no prose, no markdown fences):
{
  "type": "lookup | traverse | filter | aggregate | path | anomaly",
  "start_entity": "...",
  "target_entity": "...",
  "aggregation": {
    "metric": "count | sum | avg | max | min",
    "group_by": "...",
    "target": "...",
    "sort": "desc | asc",
    "limit": number
  },
  "path": {
    "sequence": ["EntityA", "EntityB", "EntityC"],
    "direction": "forward"
  },
  "filters": [
    {
      "entity": "...",
      "field": "...",
      "operator": "...",
      "value": "..."
    }
  ],
  "anomaly": {
    "type": "missing_link | broken_flow | inconsistency",
    "description": "..."
  },
  "confidence": "HIGH | MEDIUM | LOW"
}

RULES:
- ONLY use entities and relationships from the schema provided.
- DO NOT hallucinate entities or attributes.
- ALWAYS extract explicit IDs/numbers from the query into filters.
  For example: "Find journal entries for billing document 91150187"
  → type: "traverse", start_entity: "BillingDocument", target_entity: "JournalEntry",
    filters: [{"entity": "BillingDocument", "field": "id", "operator": "=", "value": "91150187"}]
  This is CRITICAL — without the filter, the system returns ALL records instead of the specific one.
- Infer aggregation from: "highest number", "top", "most", "count", "total", "average", "sum".
- Infer anomaly detection from: "missing", "incomplete", "broken", "without", "no matching", "unmatched".
- Infer path tracing from: "trace", "flow", "end-to-end", "full path", "journey".
- Omit fields that are not relevant to the query type (use null for unused optional fields).
- Output ONLY the JSON object. No explanation, no markdown.
"""

_USER_TEMPLATE = """\
User query:
"{user_query}"

Available entities:
{entities}

Available relationships:
{relationships}

Available attributes per entity:
{attributes_per_entity}
"""


# ─────────────────────────────────────────────
# Schema context builder
# ─────────────────────────────────────────────

def _build_schema_context(svc: GraphService) -> dict[str, Any]:
    """Extract entities, relationships, and attributes from the live graph."""
    entities = [n.name for n in svc._graph.nodes]

    relationships = []
    for edge in svc._edges:
        relationships.append(
            f"{edge.from_node} --[{edge.relationship}]--> {edge.to_node}"
        )

    attributes_per_entity: dict[str, list[str]] = {}
    for node in svc._graph.nodes:
        pks = node.primary_key if isinstance(node.primary_key, list) else [node.primary_key]
        attributes_per_entity[node.name] = pks + node.attributes

    return {
        "entities": entities,
        "relationships": relationships,
        "attributes_per_entity": attributes_per_entity,
    }


def _entity_aliases(svc: GraphService) -> dict[str, str]:
    """
    Lightweight alias map for question-time entity extraction.
    Example: "sales order item" -> SalesOrderItem, "delivery" -> OutboundDelivery.
    """
    aliases: dict[str, str] = {}
    for node in svc._graph.nodes:
        name = node.name
        low = name.lower()
        words = re.sub(r"([a-z])([A-Z])", r"\1 \2", name).lower()
        aliases[low] = name
        aliases[words] = name
        aliases[words + "s"] = name
        parts = words.split()
        if parts:
            aliases.setdefault(parts[-1], name)
            aliases.setdefault(parts[-1] + "s", name)

    # Domain-friendly shortcuts
    if "OutboundDelivery" in {n.name for n in svc._graph.nodes}:
        aliases["delivery"] = "OutboundDelivery"
        aliases["deliveries"] = "OutboundDelivery"
    if "OutboundDeliveryItem" in {n.name for n in svc._graph.nodes}:
        aliases["delivery item"] = "OutboundDeliveryItem"
        aliases["delivery items"] = "OutboundDeliveryItem"
    return aliases


def _entities_from_question(question: str, svc: GraphService) -> list[str]:
    text = question.lower()
    aliases = _entity_aliases(svc)
    found: list[str] = []
    seen: set[str] = set()
    for alias in sorted(aliases, key=len, reverse=True):
        if alias in text:
            entity = aliases[alias]
            if entity not in seen:
                found.append(entity)
                seen.add(entity)
    return found


def _coerce_missing_link_intent(
    question: str,
    plan: GraphQueryPlan,
    svc: GraphService,
) -> GraphQueryPlan:
    """
    Force anomaly planning for questions like "without delivery" or "missing invoice".
    This prevents generic traverse answers for absence checks.
    """
    q = question.lower()
    has_missing_intent = bool(
        re.search(r"\b(without|missing|unmatched|no matching|not linked|no)\b", q)
    )
    if not has_missing_intent:
        return plan
    if plan.type == "anomaly":
        return plan

    mentioned = _entities_from_question(question, svc)
    start = plan.start_entity or (mentioned[0] if mentioned else None)
    target = plan.target_entity or (mentioned[1] if len(mentioned) > 1 else None)

    # Delivery wording is common and often needs disambiguation to item-level delivery.
    if "deliver" in q:
        if start == "SalesOrderItem":
            target = "OutboundDeliveryItem"
        elif start == "SalesOrder":
            target = "OutboundDelivery"
        elif not target and "OutboundDelivery" in {n.name for n in svc._graph.nodes}:
            target = "OutboundDelivery"

    return GraphQueryPlan(
        type="anomaly",
        start_entity=start,
        target_entity=target,
        aggregation=None,
        path=None,
        filters=plan.filters or [],
        anomaly=AnomalySpec(
            type="missing_link",
            description=f"Missing-link check inferred from query: {question}",
        ),
        confidence=Confidence.MEDIUM if not (start and target) else plan.confidence,
    )


# ─────────────────────────────────────────────
# JSON extraction + validation
# ─────────────────────────────────────────────

def _extract_json(text: str) -> Optional[dict]:
    """Extract JSON object from LLM output, stripping markdown fences if present."""
    # Strip ```json ... ``` fences
    text = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()
    # Find first { ... } block
    start = text.find("{")
    end = text.rfind("}") + 1
    if start == -1 or end == 0:
        return None
    try:
        return json.loads(text[start:end])
    except json.JSONDecodeError:
        return None


def _validate_plan(raw: dict, valid_entities: set[str]) -> Optional[GraphQueryPlan]:
    """
    Parse raw JSON into GraphQueryPlan, enforcing schema constraints.
    Returns None if validation fails.
    """
    try:
        plan_type = raw.get("type")
        valid_types = {"lookup", "traverse", "filter", "aggregate", "path", "anomaly"}
        if plan_type not in valid_types:
            logger.warning("LLM returned invalid plan type: %s", plan_type)
            return None

        start_entity = raw.get("start_entity")
        target_entity = raw.get("target_entity")

        # Validate entity names — reject hallucinations
        if start_entity and start_entity not in valid_entities:
            logger.warning("LLM hallucinated start_entity: %s", start_entity)
            start_entity = None
        if target_entity and target_entity not in valid_entities:
            logger.warning("LLM hallucinated target_entity: %s", target_entity)
            target_entity = None

        # Aggregation
        aggregation = None
        if raw.get("aggregation"):
            agg = raw["aggregation"]
            metric = agg.get("metric", "count")
            if metric in {"count", "sum", "avg", "max", "min"}:
                limit_raw = agg.get("limit", 10)
                try:
                    limit = int(limit_raw) if limit_raw is not None else 10
                except (TypeError, ValueError):
                    limit = 10
                aggregation = AggregationSpec(
                    metric=metric,
                    group_by=agg.get("group_by"),
                    target=agg.get("target"),
                    sort=agg.get("sort", "desc"),
                    limit=limit,
                )

        # Path
        path = None
        if raw.get("path"):
            p = raw["path"]
            seq = [e for e in p.get("sequence", []) if e in valid_entities]
            path = PathSpec(
                sequence=seq,
                direction=p.get("direction", "forward"),
            )

        # Filters
        filters = []
        for f in raw.get("filters") or []:
            if isinstance(f, dict) and f.get("field") and f.get("value") is not None:
                entity = f.get("entity")
                if entity and entity not in valid_entities:
                    entity = None
                filters.append(PlanFilterCondition(
                    entity=entity,
                    field=str(f["field"]),
                    operator=str(f.get("operator", "=")),
                    value=str(f["value"]),
                ))

        # Anomaly
        anomaly = None
        if raw.get("anomaly"):
            a = raw["anomaly"]
            a_type = a.get("type", "inconsistency")
            if a_type not in {"missing_link", "broken_flow", "inconsistency"}:
                a_type = "inconsistency"
            anomaly = AnomalySpec(type=a_type, description=a.get("description", ""))

        # Confidence
        conf_raw = str(raw.get("confidence", "MEDIUM")).upper()
        confidence = Confidence.HIGH if conf_raw == "HIGH" else (
            Confidence.LOW if conf_raw == "LOW" else Confidence.MEDIUM
        )

        return GraphQueryPlan(
            type=plan_type,
            start_entity=start_entity,
            target_entity=target_entity,
            aggregation=aggregation,
            path=path,
            filters=filters,
            anomaly=anomaly,
            confidence=confidence,
        )

    except Exception as exc:
        logger.exception("Plan validation error: %s", exc)
        return None


# ─────────────────────────────────────────────
# Rule-based fallback
# ─────────────────────────────────────────────

def _rule_based_fallback(question: str, svc: GraphService) -> GraphQueryPlan:
    """
    Delegate to the existing rule-based parser and adapt its output to
    GraphQueryPlan. Used when LLM is unavailable or produces invalid output.
    """
    from app.services.query_parser import parse_structured_graph_query

    parsed = parse_structured_graph_query(question, svc)

    # Map ParsedGraphQuery → GraphQueryPlan
    type_map = {"lookup": "lookup", "traverse": "traverse", "filter": "filter"}
    plan_type = type_map.get(parsed.type, "lookup")

    filters = [
        PlanFilterCondition(
            entity=parsed.start_node.entity,
            field=f.field,
            operator=f.operator,
            value=f.value,
        )
        for f in parsed.filters
    ]

    # Add ID filter if present
    if parsed.start_node.id and parsed.start_node.entity:
        filters.insert(0, PlanFilterCondition(
            entity=parsed.start_node.entity,
            field="id",
            operator="=",
            value=parsed.start_node.id,
        ))

    fallback = GraphQueryPlan(
        type=plan_type,
        start_entity=parsed.start_node.entity,
        target_entity=parsed.target_entity,
        filters=filters,
        confidence=parsed.confidence,
    )
    return _coerce_missing_link_intent(question, fallback, svc)


# ─────────────────────────────────────────────
# Public entrypoint
# ─────────────────────────────────────────────

def plan_query(
    question: str,
    svc: GraphService,
    api_key: Optional[str] = None,
    model: str = "meta-llama/Llama-3.1-8B-Instruct",
) -> GraphQueryPlan:
    """
    Translate a natural-language question into a GraphQueryPlan.

    Uses Hugging Face when HUGGINGFACE_API_KEY is available; falls back to the
    rule-based parser otherwise.

    Args:
        question: The natural-language user query.
        svc:      Live GraphService (provides schema context).
        api_key:  Hugging Face API key (falls back to env var).
        model:    Hugging Face model ID.

    Returns:
        A validated GraphQueryPlan — never raises.
    """
    key = api_key or os.getenv("HUGGINGFACE_API_KEY", "")
    if not key:
        logger.info("No API key — using rule-based fallback planner")
        return _rule_based_fallback(question, svc)

    schema = _build_schema_context(svc)
    valid_entities = set(schema["entities"])

    user_message = _USER_TEMPLATE.format(
        user_query=question,
        entities=json.dumps(schema["entities"], indent=2),
        relationships="\n".join(schema["relationships"]),
        attributes_per_entity=json.dumps(schema["attributes_per_entity"], indent=2),
    )

    try:
        raw_text = hf_chat_completion(
            api_key=key,
            model=model,
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_message,
            max_tokens=1024,
            temperature=0.0,
            endpoint=os.getenv("HUGGINGFACE_API_URL", "https://router.huggingface.co/v1/chat/completions"),
            provider=os.getenv("HUGGINGFACE_PROVIDER", ""),
        )
        logger.debug("LLM planner raw output: %s", raw_text[:500])

        raw_json = _extract_json(raw_text)
        if raw_json is None:
            logger.warning("LLM returned non-JSON output — falling back")
            return _rule_based_fallback(question, svc)

        plan = _validate_plan(raw_json, valid_entities)
        if plan is None:
            logger.warning("LLM plan failed validation — falling back")
            return _rule_based_fallback(question, svc)

        plan = _coerce_missing_link_intent(question, plan, svc)

        logger.info(
            "LLM plan: type=%s start=%s target=%s confidence=%s",
            plan.type, plan.start_entity, plan.target_entity, plan.confidence,
        )
        return plan

    except Exception as exc:
        err_name = type(exc).__name__
        err_text = str(exc)
        if "401" in err_text or "403" in err_text:
            logger.error("Hugging Face authentication/permission failed for planner (%s)", err_text)
        elif "429" in err_text:
            logger.error("Hugging Face rate limit exceeded for planner (%s)", err_text)
        elif err_name == "ConnectionError":
            logger.error("Hugging Face connection failed for planner (%s)", err_text)
        else:
            logger.exception("LLM planner error: %s", exc)
        return _rule_based_fallback(question, svc)
