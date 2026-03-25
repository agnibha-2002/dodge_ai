from __future__ import annotations
from typing import Any, List, Optional, Union
from pydantic import BaseModel, Field


# ─────────────────────────────────────────────
# Raw graph file models (mirrors graph_final.json)
# ─────────────────────────────────────────────

class RawNode(BaseModel):
    name: str
    source_table: Optional[str] = None
    primary_key: Union[str, List[str]]
    attributes: List[str] = []
    filters: List[str] = []
    record_count: Optional[int] = None
    alternate_keys: Optional[List[str]] = None
    junction_table: Optional[bool] = None
    note: Optional[str] = None
    document_type_breakdown: Optional[dict[str, Any]] = None
    query_guidance: Optional[str] = None

    model_config = {"extra": "allow"}


class RawEdge(BaseModel):
    from_node: str = Field(..., alias="from")
    to_node: str = Field(..., alias="to")
    relationship: str
    type: str = "STRUCTURAL"
    join_condition: str
    cardinality: str
    confidence: str = "HIGH"
    optional: bool = False
    completeness: str = "FULL"
    filters: List[str] = []
    data_stats: Optional[dict[str, Any]] = None
    join_key_type: Optional[str] = None
    schema_note: Optional[str] = None
    replaces_invalid_edge: Optional[str] = None

    model_config = {"extra": "allow", "populate_by_name": True}


class RawDerivedRelationship(BaseModel):
    from_node: str = Field(..., alias="from")
    to_node: str = Field(..., alias="to")
    relationship: str
    logic: str
    confidence: str = "LOW"
    optional: bool = True
    note: Optional[str] = None

    model_config = {"extra": "allow", "populate_by_name": True}


class RawGraph(BaseModel):
    version: Optional[str] = None
    description: Optional[str] = None
    nodes: List[RawNode]
    edges: List[RawEdge]
    derived_relationships: List[RawDerivedRelationship] = []
    removed_edges: List[dict[str, Any]] = []

    model_config = {"extra": "allow"}


# ─────────────────────────────────────────────
# API Response models
# ─────────────────────────────────────────────

class NodeSummary(BaseModel):
    name: str
    source_table: Optional[str]
    primary_key: Union[str, List[str]]
    record_count: Optional[int]
    outgoing_edge_count: int
    incoming_edge_count: int
    total_edge_count: int


class NodeDetail(BaseModel):
    name: str
    source_table: Optional[str]
    primary_key: Union[str, List[str]]
    alternate_keys: List[str]
    attributes: List[str]
    filters: List[str]
    record_count: Optional[int]
    query_guidance: Optional[str]
    outgoing_edges: List[EdgeSummary]
    incoming_edges: List[EdgeSummary]
    connected_node_names: List[str]


class EdgeSummary(BaseModel):
    from_node: str = Field(..., serialization_alias="from")
    to_node: str = Field(..., serialization_alias="to")
    relationship: str
    type: str
    join_condition: str
    cardinality: str
    confidence: str
    optional: bool
    completeness: str
    filters: List[str]

    model_config = {"populate_by_name": True}


class ExpandResponse(BaseModel):
    center_node: NodeSummary
    nodes: List[NodeSummary]
    edges: List[EdgeSummary]
    ui_graph: UIGraph


class UINode(BaseModel):
    id: str
    label: str
    source_table: Optional[str] = None
    record_count: Optional[int] = None
    primary_key: Optional[Union[str, List[str]]] = None
    attributes: List[str] = []


class UILink(BaseModel):
    source: str
    target: str
    label: str
    type: str
    cardinality: str
    confidence: str
    optional: bool


class UIGraph(BaseModel):
    nodes: List[UINode]
    links: List[UILink]


class SearchResult(BaseModel):
    name: str
    source_table: Optional[str]
    record_count: Optional[int]
    match_score: int
    primary_key: Union[str, List[str]]


class RecordsResponse(BaseModel):
    node_name: str
    source_table: Optional[str]
    columns: List[str]
    column_types: dict[str, str]
    primary_key: Union[str, List[str]]
    records: List[dict[str, Any]]
    total_count: int
    offset: int
    limit: int


class RecordGraphNode(BaseModel):
    """A single record (row) represented as a graph node."""
    id: str                          # "EntityName:pk_value"
    entity: str                      # parent entity name
    primary_key_value: str           # display label
    fields: dict[str, Any]           # all column values


class RecordGraphEdge(BaseModel):
    """A join-based edge between two record nodes."""
    source: str                      # source record node id
    target: str                      # target record node id
    relationship: str                # e.g. "Order → Delivery"


class RecordGraphResponse(BaseModel):
    """Full record-level graph payload."""
    nodes: List[RecordGraphNode]
    edges: List[RecordGraphEdge]
    entity_colors: dict[str, str]    # entity name → hex colour for rendering


NodeDetail.model_rebuild()
ExpandResponse.model_rebuild()
