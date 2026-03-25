from fastapi import APIRouter, Depends, HTTPException, Query

from app.models.graph import RecordsResponse
from app.services.graph_service import GraphService
from app.dependencies import get_graph_service

router = APIRouter(prefix="/nodes", tags=["Records"])


@router.get(
    "/{node_name}/records",
    response_model=RecordsResponse,
    summary="Get sample records for a node",
)
def get_node_records(
    node_name: str,
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    search: str = Query(default=""),
    svc: GraphService = Depends(get_graph_service),
):
    """
    Return sample records for a node, generated from the schema.
    Supports pagination (limit/offset) and text search across all fields.
    """
    result = svc.get_node_records(
        name=node_name,
        limit=limit,
        offset=offset,
        search=search.strip() or None,
    )
    if result is None:
        raise HTTPException(status_code=404, detail=f"Node '{node_name}' not found")
    return result
