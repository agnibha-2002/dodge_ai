"""
Models for the deterministic graph execution engine.

Input  : ParsedGraphQuery + optional raw nodes/edges snapshot
Output : GraphExecResult { result, status }
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.models.query import ParsedGraphQuery


# ─────────────────────────────────────────────
# Raw graph snapshot (optional caller-supplied)
# ─────────────────────────────────────────────

class RawNodeSnapshot(BaseModel):
    name: str
    source_table: Optional[str] = None
    primary_key: Any = None
    attributes: List[str] = []
    record_count: Optional[int] = None


class RawEdgeSnapshot(BaseModel):
    from_node: str
    to_node: str
    relationship: str
    join_condition: str = ""


class GraphSnapshot(BaseModel):
    """Caller-supplied nodes and edges. If omitted, the live GraphService is used."""
    nodes: List[RawNodeSnapshot] = []
    edges: List[RawEdgeSnapshot] = []


# ─────────────────────────────────────────────
# Request
# ─────────────────────────────────────────────

class GraphExecRequest(BaseModel):
    query: ParsedGraphQuery
    graph: Optional[GraphSnapshot] = Field(
        default=None,
        description="Optional graph snapshot. If absent, the loaded graph is used.",
    )


# ─────────────────────────────────────────────
# Result sub-shapes
# ─────────────────────────────────────────────

class TraversalHop(BaseModel):
    from_entity: str
    to_entity: str
    relationship: str


class LookupResult(BaseModel):
    type: Literal["lookup"] = "lookup"
    entity: str
    id: Optional[str] = None
    record: Optional[Dict[str, Any]] = None       # matched row (when id given)
    records: List[Dict[str, Any]] = []             # sample rows (when no id)
    record_count: Optional[int] = None
    attributes: List[str] = []
    connected_entities: List[str] = []


class TraverseResult(BaseModel):
    type: Literal["traverse"] = "traverse"
    start_entity: str
    target_entity: str
    path: List[str] = []
    hops: List[TraversalHop] = []
    path_length: int = 0
    target_records: List[Dict[str, Any]] = []
    target_record_count: Optional[int] = None


class FilterResult(BaseModel):
    type: Literal["filter"] = "filter"
    entity: str
    filters_applied: List[Dict[str, str]] = []
    records: List[Dict[str, Any]] = []
    record_count: int = 0


# ─────────────────────────────────────────────
# Top-level response
# ─────────────────────────────────────────────

class GraphExecResult(BaseModel):
    result: Optional[Dict[str, Any]] = None
    status: Literal["success", "empty", "error"]
    error: Optional[str] = None
