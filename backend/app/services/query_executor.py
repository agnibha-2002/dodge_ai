"""
Execute a QueryPlan against the in-memory graph and synthetic records.

Returns a human-readable answer string plus supporting data.
"""
from __future__ import annotations

from typing import Any, Optional

from app.models.query import (
    FilterCondition,
    QueryIntent,
    QueryPlan,
    QueryResponse,
)
from app.services.graph_service import GraphService


def execute_query(plan: QueryPlan, svc: GraphService) -> QueryResponse:
    """Execute a parsed QueryPlan and return a structured response."""

    if plan.intent == QueryIntent.LOOKUP:
        return _execute_lookup(plan, svc)
    elif plan.intent == QueryIntent.TRAVERSE:
        return _execute_traverse(plan, svc)
    elif plan.intent == QueryIntent.FILTER:
        return _execute_filter(plan, svc)
    elif plan.intent == QueryIntent.AGGREGATE:
        return _execute_aggregate(plan, svc)
    else:
        return QueryResponse(
            answer="I couldn't understand the query type.",
            query_plan=plan,
        )


# ─────────────────────────────────────────────
# Lookup: single entity info + sample records
# ─────────────────────────────────────────────

def _execute_lookup(plan: QueryPlan, svc: GraphService) -> QueryResponse:
    node = svc.get_node(plan.start_entity)
    if not node:
        return QueryResponse(
            answer=f"Entity **{plan.start_entity}** not found in the graph.",
            query_plan=plan,
        )

    # Get sample records
    records_resp = svc.get_node_records(plan.start_entity, limit=5)
    records = records_resp.records if records_resp else []

    # Build answer
    lines = [
        f"**{node.name}**",
        f"- Source table: `{node.source_table or 'N/A'}`",
        f"- Primary key: `{node.primary_key}`",
        f"- Record count: **{node.record_count:,}**" if node.record_count else "- Record count: unknown",
        f"- Connections: {len(node.connected_node_names)} entities ({', '.join(node.connected_node_names[:5])})",
    ]

    if node.attributes:
        cols = ", ".join(f"`{a}`" for a in node.attributes[:8])
        lines.append(f"- Attributes: {cols}")

    if records:
        lines.append(f"\nShowing **{len(records)}** sample records.")

    return QueryResponse(
        answer="\n".join(lines),
        query_plan=plan,
        records=records[:5],
        record_count=node.record_count,
        traversal_path_used=plan.traversal_path,
    )


# ─────────────────────────────────────────────
# Traverse: follow path between two entities
# ─────────────────────────────────────────────

def _execute_traverse(plan: QueryPlan, svc: GraphService) -> QueryResponse:
    if not plan.traversal_path:
        return QueryResponse(
            answer=f"No path found between **{plan.start_entity}** and **{plan.target_entity}** in the graph.",
            query_plan=plan,
        )

    # Describe each hop
    lines = [
        f"**Path from {plan.start_entity} to {plan.target_entity}** ({len(plan.traversal_path) - 1} hops):",
        "",
    ]

    for i, entity in enumerate(plan.traversal_path):
        node = svc.get_node(entity)
        count_str = f"{node.record_count:,}" if node and node.record_count else "?"
        prefix = "→ " if i > 0 else ""
        lines.append(f"{prefix}**{entity}** ({count_str} records)")

        # Find the relationship for this hop
        if i > 0:
            prev = plan.traversal_path[i - 1]
            rel = _find_relationship(prev, entity, svc)
            if rel:
                lines.append(f"  relationship: *{rel}*")

    # Get target records
    target = plan.target_entity or plan.start_entity
    records_resp = svc.get_node_records(target, limit=5)
    records = records_resp.records if records_resp else []

    if records:
        lines.append(f"\nShowing **{len(records)}** sample records from **{target}**.")

    return QueryResponse(
        answer="\n".join(lines),
        query_plan=plan,
        records=records[:5],
        record_count=records_resp.total_count if records_resp else None,
        traversal_path_used=plan.traversal_path,
    )


# ─────────────────────────────────────────────
# Filter: apply conditions to entity records
# ─────────────────────────────────────────────

def _execute_filter(plan: QueryPlan, svc: GraphService) -> QueryResponse:
    records_resp = svc.get_node_records(plan.start_entity, limit=50)
    if not records_resp or not records_resp.records:
        return QueryResponse(
            answer=f"No records found for **{plan.start_entity}**.",
            query_plan=plan,
        )

    filtered = _apply_filters(records_resp.records, plan.filters)

    if not filtered:
        conds = ", ".join(f"{f.field} {f.operator} {f.value}" for f in plan.filters)
        return QueryResponse(
            answer=f"No **{plan.start_entity}** records match the condition: {conds}.",
            query_plan=plan,
            records=[],
            record_count=0,
        )

    conds = ", ".join(f"`{f.field}` {f.operator} {f.value}" for f in plan.filters)
    lines = [
        f"Found **{len(filtered)}** {plan.start_entity} records where {conds}.",
    ]

    return QueryResponse(
        answer="\n".join(lines),
        query_plan=plan,
        records=filtered[:10],
        record_count=len(filtered),
    )


# ─────────────────────────────────────────────
# Aggregate: count / sum / avg / min / max
# ─────────────────────────────────────────────

def _execute_aggregate(plan: QueryPlan, svc: GraphService) -> QueryResponse:
    entity = plan.start_entity
    node = svc.get_node(entity)

    if plan.aggregation == "count" and not plan.aggregation_field:
        # Simple count — use record_count from metadata
        count = node.record_count if node else None
        if count is not None:
            answer = f"**{entity}** has **{count:,}** records."
        else:
            answer = f"Record count for **{entity}** is unknown."

        # If traversal to another entity, also show that count
        if plan.target_entity and plan.target_entity != entity:
            target_node = svc.get_node(plan.target_entity)
            if target_node and target_node.record_count is not None:
                answer += f"\n**{plan.target_entity}** has **{target_node.record_count:,}** records."
            if plan.traversal_path:
                answer += f"\nPath: {' → '.join(plan.traversal_path)}"

        return QueryResponse(
            answer=answer,
            query_plan=plan,
            record_count=count,
            traversal_path_used=plan.traversal_path,
        )

    # Aggregation on a specific field
    records_resp = svc.get_node_records(entity, limit=50)
    if not records_resp or not records_resp.records:
        return QueryResponse(
            answer=f"No records found for **{entity}**.",
            query_plan=plan,
        )

    records = records_resp.records
    if plan.filters:
        records = _apply_filters(records, plan.filters)

    field = plan.aggregation_field
    if not field:
        # Fallback: try to find a numeric field
        for col in records_resp.columns:
            if any(k in col.lower() for k in ("amount", "total", "price", "quantity", "net")):
                field = col
                break

    if not field:
        return QueryResponse(
            answer=f"Could not determine which field to aggregate on **{entity}**.",
            query_plan=plan,
        )

    values = _extract_numeric_values(records, field)
    if not values:
        return QueryResponse(
            answer=f"No numeric values found in `{field}` for **{entity}**.",
            query_plan=plan,
        )

    agg = plan.aggregation or "count"
    result = _compute_aggregate(values, agg)

    return QueryResponse(
        answer=f"**{agg.upper()}** of `{field}` across {len(values)} **{entity}** records: **{result:,.2f}**",
        query_plan=plan,
        records=records[:5],
        record_count=len(records),
    )


# ─────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────

def _find_relationship(from_entity: str, to_entity: str, svc: GraphService) -> Optional[str]:
    for edge in svc._edges:
        if edge.from_node == from_entity and edge.to_node == to_entity:
            return edge.relationship
        if edge.from_node == to_entity and edge.to_node == from_entity:
            return edge.relationship
    return None


def _apply_filters(records: list[dict], filters: list[FilterCondition]) -> list[dict]:
    result = list(records)
    for f in filters:
        result = [r for r in result if _matches_filter(r, f)]
    return result


def _matches_filter(record: dict, f: FilterCondition) -> bool:
    val = record.get(f.field)
    if val is None:
        return False

    try:
        if f.operator == "=":
            return str(val).lower() == f.value.lower()
        elif f.operator == "!=":
            return str(val).lower() != f.value.lower()
        elif f.operator == "contains":
            return f.value.lower() in str(val).lower()

        # Numeric comparisons
        num_val = float(val) if not isinstance(val, (int, float)) else val
        num_cmp = float(f.value)

        if f.operator == ">":
            return num_val > num_cmp
        elif f.operator == "<":
            return num_val < num_cmp
        elif f.operator == ">=":
            return num_val >= num_cmp
        elif f.operator == "<=":
            return num_val <= num_cmp
    except (ValueError, TypeError):
        return False

    return False


def _extract_numeric_values(records: list[dict], field: str) -> list[float]:
    values: list[float] = []
    for r in records:
        v = r.get(field)
        if v is None:
            continue
        try:
            values.append(float(v))
        except (ValueError, TypeError):
            continue
    return values


def _compute_aggregate(values: list[float], agg: str) -> float:
    if agg == "count":
        return float(len(values))
    elif agg == "sum":
        return sum(values)
    elif agg == "avg":
        return sum(values) / len(values) if values else 0.0
    elif agg == "max":
        return max(values)
    elif agg == "min":
        return min(values)
    return float(len(values))
