from fastapi import APIRouter, Depends, HTTPException, Query

from app.models.graph import ExpandResponse
from app.services.graph_service import GraphService
from app.dependencies import get_graph_service

router = APIRouter(tags=["Graph Exploration"])


@router.get("/expand", response_model=ExpandResponse, summary="Expand a node")
def expand_node(
    node: str = Query(..., description="Node name to expand"),
    svc: GraphService = Depends(get_graph_service),
):
    """
    Return the immediate neighbourhood of a node:
    - **center_node**: metadata for the requested node
    - **nodes**: directly connected neighbour nodes
    - **edges**: all edges touching this node (incoming + outgoing)
    - **ui_graph**: ready-to-render format `{nodes, links}` for Cytoscape.js / vis-network

    Empty `nodes` and `edges` arrays are returned for isolated nodes (no error).
    """
    result = svc.expand_node(node)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Node '{node}' not found")
    return result
