"""
Models for NL → Graph Query Intent parsing.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class QueryIntent(str, Enum):
    LOOKUP = "lookup"          # find a specific entity / record
    TRAVERSE = "traverse"      # follow a path through the graph
    FILTER = "filter"          # filter records by field conditions
    AGGREGATE = "aggregate"    # count, sum, etc.


class Confidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class FilterCondition(BaseModel):
    field: str
    operator: str = "="       # =, !=, >, <, >=, <=, contains, in
    value: str


class QueryPlan(BaseModel):
    """Structured query plan extracted from natural language."""
    intent: QueryIntent
    start_entity: str
    target_entity: Optional[str] = None
    filters: List[FilterCondition] = []
    traversal_path: List[str] = []
    aggregation: Optional[str] = None      # count, sum, avg, min, max
    aggregation_field: Optional[str] = None
    confidence: Confidence = Confidence.MEDIUM
    explanation: str = ""                   # human-readable plan summary


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)


class QueryResponse(BaseModel):
    answer: str
    query_plan: Optional[QueryPlan] = None
    records: List[dict[str, Any]] = []
    record_count: Optional[int] = None
    traversal_path_used: List[str] = []


class ParsedStartNode(BaseModel):
    entity: Optional[str] = None
    id: Optional[str] = None


class ParsedFilterCondition(BaseModel):
    field: str
    operator: str = "="
    value: str


class ParsedGraphQuery(BaseModel):
    type: Literal["lookup", "traverse", "filter"]
    start_node: ParsedStartNode
    target_entity: Optional[str] = None
    filters: List[ParsedFilterCondition] = []
    confidence: Confidence = Confidence.MEDIUM


class QueryParseResponse(BaseModel):
    answer: str
    parsed_query: ParsedGraphQuery


class QueryValidationRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    structured_query: Dict[str, Any]


class ValidationIssue(BaseModel):
    type: Literal[
        "ENTITY_ERROR",
        "RELATION_ERROR",
        "ID_ERROR",
        "CONFIDENCE_ERROR",
        "HALLUCINATION",
    ]
    message: str


class QueryValidationResponse(BaseModel):
    status: Literal["PASS", "FAIL"]
    issues: List[ValidationIssue] = []
    corrected_query: Optional[ParsedGraphQuery] = None
