from fastapi import APIRouter, Depends, Query
from typing import Optional

from app.models.graph import UIGraph
from app.services.graph_service import GraphService
from app.dependencies import get_graph_service

router = APIRouter(prefix="/graph", tags=["Graph"])


@router.get("/ui", response_model=UIGraph, summary="Full graph in UI format")
def get_ui_graph(
    type: Optional[str] = Query(
        None,
        description="Filter edges by type: STRUCTURAL, FILTERED, or DERIVED",
        pattern="^(STRUCTURAL|FILTERED|DERIVED)$",
    ),
    confidence: Optional[str] = Query(
        None,
        description="Filter edges by confidence: HIGH, MEDIUM, or LOW",
        pattern="^(HIGH|MEDIUM|LOW)$",
    ),
    include_derived: bool = Query(
        False,
        description="Include DERIVED edges (default: false)",
    ),
    svc: GraphService = Depends(get_graph_service),
):
    """
    Return the full graph in UI-ready format:
    ```json
    {
      "nodes": [{"id": "Customer", "label": "Customer", ...}],
      "links": [{"source": "SalesOrder", "target": "Customer", "label": "placed_by", ...}]
    }
    ```
    Compatible with **Cytoscape.js**, **vis-network**, and **react-force-graph**.
    """
    return svc.get_ui_graph(
        edge_type=type,
        confidence=confidence,
        include_derived=include_derived,
    )


@router.get("/adjacency", summary="Adjacency list")
def get_adjacency(svc: GraphService = Depends(get_graph_service)):
    """Return the full outgoing adjacency list: `{NodeName: [connected_node, ...]}`"""
    return svc.get_adjacency()


@router.get("/stats", summary="Graph statistics")
def get_stats(svc: GraphService = Depends(get_graph_service)):
    """Return node/edge counts and graph metadata."""
    return svc.get_graph_stats()
