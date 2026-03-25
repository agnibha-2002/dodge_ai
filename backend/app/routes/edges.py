from fastapi import APIRouter, Depends, Query
from typing import Literal, Optional

from app.models.graph import EdgeSummary
from app.services.graph_service import GraphService
from app.dependencies import get_graph_service

router = APIRouter(prefix="/edges", tags=["Edges"])


@router.get("", response_model=list[EdgeSummary], summary="List edges")
def list_edges(
    type: Optional[str] = Query(
        None,
        description="Filter by edge type: STRUCTURAL, FILTERED, or DERIVED",
        pattern="^(STRUCTURAL|FILTERED|DERIVED)$",
    ),
    confidence: Optional[str] = Query(
        None,
        description="Filter by confidence: HIGH, MEDIUM, or LOW",
        pattern="^(HIGH|MEDIUM|LOW)$",
    ),
    include_derived: bool = Query(
        True,
        description="Set false to exclude DERIVED edges",
    ),
    svc: GraphService = Depends(get_graph_service),
):
    """
    Return edges with optional filters:
    - **type**: STRUCTURAL | FILTERED | DERIVED
    - **confidence**: HIGH | MEDIUM | LOW
    - **include_derived**: exclude derived relationships (default: true)
    """
    return svc.get_edges(
        edge_type=type,
        confidence=confidence,
        include_derived=include_derived,
    )
