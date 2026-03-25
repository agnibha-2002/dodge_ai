"""
Models for the LLM-based graph query planner.

Supports 6 intent types:
  lookup    — find a specific entity / record
  traverse  — follow a path between two entities
  filter    — apply field conditions
  aggregate — count / sum / avg / max / min, optionally grouped
  path      — end-to-end flow trace (explicit sequence)
  anomaly   — detect missing links, broken flows, inconsistencies
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.models.query import Confidence


# ─────────────────────────────────────────────
# Sub-specs
# ─────────────────────────────────────────────

class AggregationSpec(BaseModel):
    metric: Literal["count", "sum", "avg", "max", "min"]
    group_by: Optional[str] = None
    target: Optional[str] = None      # field or entity to aggregate on
    sort: Optional[Literal["asc", "desc"]] = "desc"
    limit: Optional[int] = 10


class PathSpec(BaseModel):
    sequence: List[str] = []          # ordered entity names
    direction: Literal["forward", "backward"] = "forward"


class AnomalySpec(BaseModel):
    type: Literal["missing_link", "broken_flow", "inconsistency"]
    description: str


class PlanFilterCondition(BaseModel):
    entity: Optional[str] = None      # which entity this filter applies to
    field: str
    operator: str = "="
    value: str


# ─────────────────────────────────────────────
# Top-level plan
# ─────────────────────────────────────────────

class GraphQueryPlan(BaseModel):
    """
    Structured query plan produced by the LLM planner.
    Not all fields are populated for every type.
    """
    type: Literal["lookup", "traverse", "filter", "aggregate", "path", "anomaly"]
    start_entity: Optional[str] = None
    target_entity: Optional[str] = None

    aggregation: Optional[AggregationSpec] = None
    path: Optional[PathSpec] = None
    filters: List[PlanFilterCondition] = []
    anomaly: Optional[AnomalySpec] = None

    confidence: Confidence = Confidence.MEDIUM


# ─────────────────────────────────────────────
# Request / Response
# ─────────────────────────────────────────────

class PlanRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)


class PlanResponse(BaseModel):
    plan: GraphQueryPlan
    execution: Dict[str, Any]
    answer: str
