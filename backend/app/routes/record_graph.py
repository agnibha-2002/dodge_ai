from fastapi import APIRouter, Depends, Query

from app.models.graph import RecordGraphResponse
from app.services.graph_service import GraphService
from app.dependencies import get_graph_service

router = APIRouter(tags=["Record Graph"])


@router.get(
    "/record-graph",
    response_model=RecordGraphResponse,
    summary="Get record-level graph (instance nodes + FK edges)",
)
def get_record_graph(
    records_per_entity: int = Query(default=5, ge=1, le=20),
    svc: GraphService = Depends(get_graph_service),
):
    """
    Build a record-level graph where nodes are individual rows
    and edges are real FK joins between records.
    """
    return svc.get_record_graph(records_per_entity=records_per_entity)
