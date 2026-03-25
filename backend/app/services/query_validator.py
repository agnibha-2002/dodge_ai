from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.models.query import (
    Confidence,
    ParsedGraphQuery,
    QueryValidationResponse,
    ValidationIssue,
)
from app.services.graph_service import GraphService
from app.services.query_parser import parse_structured_graph_query


def _build_rel_index(svc: GraphService) -> dict[str, set[str]]:
    idx: dict[str, set[str]] = defaultdict(set)
    for edge in svc._edges:
        idx[edge.from_node].add(edge.to_node)
        idx[edge.to_node].add(edge.from_node)
    return idx


def _has_path(start: str, end: str, rel_index: dict[str, set[str]]) -> bool:
    if start == end:
        return True

    visited = {start}
    queue: list[str] = [start]
    while queue:
        current = queue.pop(0)
        for nxt in rel_index.get(current, set()):
            if nxt in visited:
                continue
            if nxt == end:
                return True
            visited.add(nxt)
            queue.append(nxt)
    return False


def _entity_attrs(svc: GraphService, entity: str) -> set[str]:
    for node in svc._graph.nodes:
        if node.name == entity:
            pks = node.primary_key if isinstance(node.primary_key, list) else [node.primary_key]
            return {*(a for a in node.attributes), *(p for p in pks)}
    return set()


def validate_structured_query(
    user_query: str,
    structured_query: dict[str, Any],
    svc: GraphService,
) -> QueryValidationResponse:
    """
    Strict validation for natural-language -> graph-query parser output.
    """
    issues: list[ValidationIssue] = []
    entities = {node.name for node in svc._graph.nodes}
    rel_index = _build_rel_index(svc)

    corrected = parse_structured_graph_query(user_query, svc)

    query_type = structured_query.get("type")
    start_node = structured_query.get("start_node") if isinstance(structured_query.get("start_node"), dict) else {}
    start_entity = start_node.get("entity")
    start_id = start_node.get("id")
    target_entity = structured_query.get("target_entity")
    filters = structured_query.get("filters") if isinstance(structured_query.get("filters"), list) else []
    confidence_raw = structured_query.get("confidence")

    allowed_types = {"lookup", "traverse", "filter"}
    if query_type not in allowed_types:
        issues.append(
            ValidationIssue(
                type="HALLUCINATION",
                message=f"Invalid query type '{query_type}'. Allowed: lookup, traverse, filter.",
            )
        )

    if start_entity not in entities:
        issues.append(
            ValidationIssue(
                type="ENTITY_ERROR",
                message="start_node.entity is missing or not in available entities.",
            )
        )

    if target_entity is not None and target_entity not in entities:
        issues.append(
            ValidationIssue(
                type="ENTITY_ERROR",
                message="target_entity is not in available entities.",
            )
        )

    if query_type == "traverse":
        if not start_entity or not target_entity:
            issues.append(
                ValidationIssue(
                    type="RELATION_ERROR",
                    message="Traverse query must include both start_node.entity and target_entity.",
                )
            )
        elif start_entity in entities and target_entity in entities and not _has_path(start_entity, target_entity, rel_index):
            issues.append(
                ValidationIssue(
                    type="RELATION_ERROR",
                    message=f"No valid traversal path exists between {start_entity} and {target_entity}.",
                )
            )

    # Intent/type alignment: compare against deterministic parser baseline.
    if query_type in allowed_types and query_type != corrected.type:
        issues.append(
            ValidationIssue(
                type="CONFIDENCE_ERROR",
                message=f"Intent mismatch: expected '{corrected.type}' from the user query, got '{query_type}'.",
            )
        )

    expected_id = corrected.start_node.id
    if expected_id:
        if not start_id:
            issues.append(
                ValidationIssue(
                    type="ID_ERROR",
                    message=f"ID present in query but missing in parser output. Expected '{expected_id}'.",
                )
            )
        elif str(start_id).upper() != expected_id:
            issues.append(
                ValidationIssue(
                    type="ID_ERROR",
                    message=f"Incorrect ID extraction. Expected '{expected_id}', got '{start_id}'.",
                )
            )

    # If no ID appears in user query, HIGH confidence is too strong by requirement.
    if not expected_id and confidence_raw == Confidence.HIGH.value:
        issues.append(
            ValidationIssue(
                type="CONFIDENCE_ERROR",
                message="Confidence cannot be HIGH when no explicit ID is present in the user query.",
            )
        )

    if confidence_raw not in {Confidence.HIGH.value, Confidence.MEDIUM.value, Confidence.LOW.value}:
        issues.append(
            ValidationIssue(
                type="HALLUCINATION",
                message=f"Invalid confidence '{confidence_raw}'. Allowed: HIGH, MEDIUM, LOW.",
            )
        )

    if start_entity in entities and isinstance(filters, list):
        valid_fields = {a.lower() for a in _entity_attrs(svc, start_entity)}
        for idx, f in enumerate(filters):
            if not isinstance(f, dict):
                issues.append(
                    ValidationIssue(
                        type="HALLUCINATION",
                        message=f"Filter at index {idx} is not a valid object.",
                    )
                )
                continue
            field = str(f.get("field", "")).lower()
            if field and field not in valid_fields:
                issues.append(
                    ValidationIssue(
                        type="HALLUCINATION",
                        message=f"Filter field '{f.get('field')}' is not valid for entity '{start_entity}'.",
                    )
                )

    # HIGH confidence is only valid when there are no issues.
    if confidence_raw == Confidence.HIGH.value and issues:
        issues.append(
            ValidationIssue(
                type="CONFIDENCE_ERROR",
                message="Confidence is HIGH but validation found one or more critical issues.",
            )
        )

    status = "PASS" if not issues else "FAIL"
    return QueryValidationResponse(
        status=status,
        issues=issues,
        corrected_query=None if status == "PASS" else corrected,
    )
