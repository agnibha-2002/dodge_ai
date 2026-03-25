from fastapi import APIRouter, Depends, HTTPException, Query

from app.models.graph import NodeDetail, NodeSummary
from app.services.graph_service import GraphService
from app.dependencies import get_graph_service

router = APIRouter(prefix="/nodes", tags=["Nodes"])


@router.get("", response_model=list[NodeSummary], summary="List all nodes")
def list_nodes(svc: GraphService = Depends(get_graph_service)):
    """Return all graph nodes with basic metadata and edge counts."""
    return svc.get_all_nodes()


@router.get("/{node_name}", response_model=NodeDetail, summary="Get node details")
def get_node(
    node_name: str,
    svc: GraphService = Depends(get_graph_service),
):
    """
    Return full details for a single node:
    - attributes, filters, record count
    - all outgoing and incoming edges
    - list of directly connected node names
    """
    detail = svc.get_node(node_name)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Node '{node_name}' not found")
    return detail
