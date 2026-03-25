"""
NL → Graph Query Intent parser.

Uses the loaded graph schema (entities, relationships, attributes) to
parse natural-language questions into structured QueryPlan objects.
No LLM dependency — pure rule-based extraction so results are
deterministic and never hallucinate entities.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Literal, Optional

from app.models.query import (
    Confidence,
    FilterCondition,
    ParsedFilterCondition,
    ParsedGraphQuery,
    ParsedStartNode,
    QueryIntent,
    QueryPlan,
)
from app.services.graph_service import GraphService


# ─────────────────────────────────────────────
# Schema introspection helpers
# ─────────────────────────────────────────────

def _build_entity_aliases(svc: GraphService) -> dict[str, str]:
    """Map lowercased aliases → canonical entity name."""
    aliases: dict[str, str] = {}
    for node in svc._graph.nodes:
        name = node.name
        low = name.lower()
        aliases[low] = name
        # Split camelCase → words: "SalesOrder" → "sales order"
        words = re.sub(r"([a-z])([A-Z])", r"\1 \2", name).lower()
        aliases[words] = name
        # Plural forms
        aliases[words + "s"] = name
        aliases[low + "s"] = name
        # Generic short aliases (e.g. "orders" → SalesOrder), only when not already mapped.
        parts = words.split()
        if parts:
            last = parts[-1]
            aliases.setdefault(last, name)
            aliases.setdefault(last + "s", name)
        # Common abbreviations
        if "item" in low:
            aliases[low.replace("item", "line item")] = name
            aliases[low.replace("item", "line items")] = name
        if "outbound" in low:
            aliases[low.replace("outbound", "")] = name
            aliases[words.replace("outbound ", "")] = name
        if "document" in low:
            aliases[low.replace("document", "doc")] = name
            aliases[words.replace("document", "doc")] = name
    return aliases


def _build_relationship_index(svc: GraphService) -> dict[str, list[tuple[str, str, str]]]:
    """Map entity name → list of (target_entity, relationship, direction)."""
    idx: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for edge in svc._edges:
        idx[edge.from_node].append((edge.to_node, edge.relationship, "outgoing"))
        idx[edge.to_node].append((edge.from_node, edge.relationship, "incoming"))
    return idx


def _build_attribute_index(svc: GraphService) -> dict[str, list[str]]:
    """Map entity name → list of attribute column names."""
    idx: dict[str, list[str]] = {}
    for node in svc._graph.nodes:
        pks = node.primary_key if isinstance(node.primary_key, list) else [node.primary_key]
        idx[node.name] = pks + node.attributes
    return idx


# ─────────────────────────────────────────────
# Entity resolution
# ─────────────────────────────────────────────

def _resolve_entity(text: str, aliases: dict[str, str]) -> Optional[str]:
    """Find the best-matching entity in the query text."""
    text_low = text.lower()
    # Try longest alias first to prefer "sales order item" over "sales order"
    for alias in sorted(aliases, key=len, reverse=True):
        if alias in text_low:
            return aliases[alias]
    return None


def _resolve_all_entities(text: str, aliases: dict[str, str]) -> list[str]:
    """Find ALL entity mentions in the query, longest-match-first."""
    text_low = text.lower()
    found: list[str] = []
    seen: set[str] = set()
    for alias in sorted(aliases, key=len, reverse=True):
        if alias in text_low and aliases[alias] not in seen:
            found.append(aliases[alias])
            seen.add(aliases[alias])
    return found


def _extract_entity_id(text: str, entity: str, aliases: dict[str, str]) -> Optional[str]:
    """
    Extract an entity ID from text if present.
    Examples:
    - "customer CUST-1001"
    - "order id 45000123"
    - "invoice #INV-77"
    """
    text_low = text.lower()
    entity_aliases = sorted(
        {alias for alias, canonical in aliases.items() if canonical == entity},
        key=len,
        reverse=True,
    )

    for alias in entity_aliases:
        alias_pattern = re.escape(alias)
        pattern = (
            rf"\b{alias_pattern}\b\s*"
            rf"(?:(id|number|no|#)\s*[:#-]?\s*)?"
            rf"([a-z0-9][a-z0-9._-]{{1,}})"
        )
        match = re.search(pattern, text_low, flags=re.IGNORECASE)
        if match:
            cue = match.group(1)
            candidate = match.group(2).strip(" .,:;")
            if cue:
                return candidate.upper()
            # Without an explicit cue like "id", require an ID-ish token.
            if any(ch.isdigit() for ch in candidate) or "-" in candidate or "_" in candidate:
                return candidate.upper()

    # Fallback generic ID extraction when entity is known
    generic = re.search(r"\b(?:id|number|no|#)\s*[:#-]?\s*([a-z0-9][a-z0-9._-]{1,})", text_low, flags=re.IGNORECASE)
    if generic:
        return generic.group(1).strip(" .,:;").upper()

    return None


# ─────────────────────────────────────────────
# Filter extraction
# ─────────────────────────────────────────────

_OPERATOR_PATTERNS = [
    (r"(?:greater|more|above|over|>)\s*(?:than\s+)?(\d[\d,.]*)", ">"),
    (r"(?:less|below|under|fewer|<)\s*(?:than\s+)?(\d[\d,.]*)", "<"),
    (r"(?:at least|>=)\s*(\d[\d,.]*)", ">="),
    (r"(?:at most|<=)\s*(\d[\d,.]*)", "<="),
    (r"(?:equals?|=|is)\s+[\"']?([^\"']+)[\"']?", "="),
]

_FIELD_KEYWORDS = {
    "amount": "amount",
    "price": "price",
    "total": "total_net_amount",
    "quantity": "quantity",
    "status": "status",
    "type": "type",
    "name": "name",
    "currency": "currency",
    "country": "country",
    "city": "city",
    "date": "date",
    "blocked": "is_blocked",
    "archived": "is_archived",
    "delivery status": "overall_delivery_status",
    "payment terms": "payment_terms",
}


def _extract_filters(
    text: str,
    entity: str,
    attr_index: dict[str, list[str]],
) -> list[FilterCondition]:
    """Best-effort filter extraction from natural language."""
    filters: list[FilterCondition] = []
    text_low = text.lower()
    entity_attrs = attr_index.get(entity, [])

    # Try to match field keywords from the query
    matched_field: Optional[str] = None
    for keyword, field in sorted(_FIELD_KEYWORDS.items(), key=lambda x: len(x[0]), reverse=True):
        if keyword in text_low:
            # Verify field exists on the entity (or a close match)
            for attr in entity_attrs:
                if field in attr.lower() or attr.lower() in field:
                    matched_field = attr
                    break
            if matched_field:
                break

    if not matched_field:
        return filters

    # Try operator patterns
    for pattern, operator in _OPERATOR_PATTERNS:
        m = re.search(pattern, text_low)
        if m:
            value = m.group(1).strip().rstrip(".,")
            filters.append(FilterCondition(field=matched_field, operator=operator, value=value))
            break

    return filters


# ─────────────────────────────────────────────
# Aggregation detection
# ─────────────────────────────────────────────

_AGG_PATTERNS = {
    "count": r"\b(?:how many|count|number of|total number)\b",
    "sum": r"\b(?:total|sum of|combined)\b",
    "avg": r"\b(?:average|mean|avg)\b",
    "max": r"\b(?:max|maximum|highest|largest|biggest|most expensive)\b",
    "min": r"\b(?:min|minimum|lowest|smallest|cheapest|least)\b",
}


def _detect_aggregation(text: str) -> Optional[str]:
    text_low = text.lower()
    for agg, pattern in _AGG_PATTERNS.items():
        if re.search(pattern, text_low):
            return agg
    return None


# ─────────────────────────────────────────────
# Traversal path finder (BFS)
# ─────────────────────────────────────────────

def _find_path(
    start: str,
    end: str,
    rel_index: dict[str, list[tuple[str, str, str]]],
) -> list[str]:
    """BFS shortest path between two entities."""
    if start == end:
        return [start]

    visited = {start}
    queue: list[tuple[str, list[str]]] = [(start, [start])]

    while queue:
        current, path = queue.pop(0)
        for neighbor, _rel, _dir in rel_index.get(current, []):
            if neighbor in visited:
                continue
            new_path = path + [neighbor]
            if neighbor == end:
                return new_path
            visited.add(neighbor)
            queue.append((neighbor, new_path))

    return []  # no path found


# ─────────────────────────────────────────────
# Main parser
# ─────────────────────────────────────────────

def parse_query(question: str, svc: GraphService) -> QueryPlan:
    """
    Parse a natural-language question into a QueryPlan.
    Uses ONLY entities and relationships from the loaded graph schema.
    """
    aliases = _build_entity_aliases(svc)
    rel_index = _build_relationship_index(svc)
    attr_index = _build_attribute_index(svc)

    entities = _resolve_all_entities(question, aliases)
    aggregation = _detect_aggregation(question)

    # ── No entities found ──────────────────────
    if not entities:
        return QueryPlan(
            intent=QueryIntent.LOOKUP,
            start_entity="Customer",  # default entry point
            confidence=Confidence.LOW,
            explanation="Could not identify a specific entity in the question. Defaulting to Customer.",
        )

    start_entity = entities[0]
    target_entity = entities[1] if len(entities) > 1 else None

    # ── Extract filters ────────────────────────
    filters = _extract_filters(question, start_entity, attr_index)

    # ── Determine intent ───────────────────────
    if aggregation:
        intent = QueryIntent.AGGREGATE
        agg_field = None
        for keyword, field in _FIELD_KEYWORDS.items():
            if keyword in question.lower():
                for attr in attr_index.get(start_entity, []):
                    if field in attr.lower():
                        agg_field = attr
                        break
                if agg_field:
                    break

        traversal_path = (
            _find_path(start_entity, target_entity, rel_index) if target_entity else [start_entity]
        )

        return QueryPlan(
            intent=intent,
            start_entity=start_entity,
            target_entity=target_entity,
            filters=filters,
            traversal_path=traversal_path,
            aggregation=aggregation,
            aggregation_field=agg_field,
            confidence=Confidence.HIGH if target_entity or filters else Confidence.MEDIUM,
            explanation=_build_explanation(intent, start_entity, target_entity, filters, aggregation, traversal_path),
        )

    if target_entity:
        # Two entities mentioned → traversal
        traversal_path = _find_path(start_entity, target_entity, rel_index)
        confidence = Confidence.HIGH if traversal_path else Confidence.LOW

        return QueryPlan(
            intent=QueryIntent.TRAVERSE,
            start_entity=start_entity,
            target_entity=target_entity,
            filters=filters,
            traversal_path=traversal_path,
            confidence=confidence,
            explanation=_build_explanation(QueryIntent.TRAVERSE, start_entity, target_entity, filters, None, traversal_path),
        )

    if filters:
        return QueryPlan(
            intent=QueryIntent.FILTER,
            start_entity=start_entity,
            filters=filters,
            traversal_path=[start_entity],
            confidence=Confidence.MEDIUM,
            explanation=_build_explanation(QueryIntent.FILTER, start_entity, None, filters, None, [start_entity]),
        )

    # Single entity, no filters → lookup
    return QueryPlan(
        intent=QueryIntent.LOOKUP,
        start_entity=start_entity,
        traversal_path=[start_entity],
        confidence=Confidence.HIGH,
        explanation=_build_explanation(QueryIntent.LOOKUP, start_entity, None, [], None, [start_entity]),
    )


def _build_explanation(
    intent: QueryIntent,
    start: str,
    target: Optional[str],
    filters: list[FilterCondition],
    agg: Optional[str],
    path: list[str],
) -> str:
    parts: list[str] = []

    if intent == QueryIntent.LOOKUP:
        parts.append(f"Look up **{start}** records")
    elif intent == QueryIntent.TRAVERSE:
        parts.append(f"Traverse from **{start}** to **{target}**")
        if path:
            parts.append(f"via path: {' → '.join(path)}")
    elif intent == QueryIntent.FILTER:
        parts.append(f"Filter **{start}** records")
    elif intent == QueryIntent.AGGREGATE:
        parts.append(f"**{agg.upper() if agg else 'COUNT'}** on **{start}**")
        if target:
            parts.append(f"related to **{target}**")

    if filters:
        conds = ", ".join(f"{f.field} {f.operator} {f.value}" for f in filters)
        parts.append(f"where {conds}")

    return " ".join(parts)


def parse_structured_graph_query(question: str, svc: GraphService) -> ParsedGraphQuery:
    """
    Parse natural language into a strict graph query object:
    {
      "type": "lookup|traverse|filter",
      "start_node": {"entity": "...", "id": "..."},
      "target_entity": "...",
      "filters": [],
      "confidence": "HIGH|MEDIUM|LOW"
    }
    """
    aliases = _build_entity_aliases(svc)
    attr_index = _build_attribute_index(svc)

    entities = _resolve_all_entities(question, aliases)
    start_entity = entities[0] if entities else None
    target_entity = entities[1] if len(entities) > 1 else None

    if start_entity:
        raw_filters = _extract_filters(question, start_entity, attr_index)
    else:
        raw_filters = []

    parsed_filters = [
        ParsedFilterCondition(field=f.field, operator=f.operator, value=f.value)
        for f in raw_filters
    ]

    start_id = _extract_entity_id(question, start_entity, aliases) if start_entity else None

    query_type: Literal["lookup", "traverse", "filter"]
    if target_entity:
        query_type = "traverse"
    elif parsed_filters:
        query_type = "filter"
    else:
        query_type = "lookup"

    if not start_entity:
        confidence = Confidence.LOW
    elif start_id:
        confidence = Confidence.HIGH
    else:
        confidence = Confidence.MEDIUM

    return ParsedGraphQuery(
        type=query_type,
        start_node=ParsedStartNode(entity=start_entity, id=start_id),
        target_entity=target_entity,
        filters=parsed_filters,
        confidence=confidence,
    )
