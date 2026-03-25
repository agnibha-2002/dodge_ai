from fastapi import APIRouter, Depends, Query

from app.models.graph import SearchResult
from app.services.graph_service import GraphService
from app.dependencies import get_graph_service

router = APIRouter(tags=["Search"])


@router.get("/search", response_model=list[SearchResult], summary="Search nodes")
def search_nodes(
    q: str = Query(..., min_length=1, description="Search term (fuzzy match on node names)"),
    limit: int = Query(10, ge=1, le=50, description="Maximum results to return"),
    svc: GraphService = Depends(get_graph_service),
):
    """
    Fuzzy-search node names. Returns results ordered by match score (highest first).

    Match scoring:
    - **100** — exact match
    - **90** — starts with query
    - **75** — query is a substring
    - **60** — a word in the name starts with query
    - **50** — query is substring of any word
    - **30** — query is a subsequence of the name
    """
    return svc.search_nodes(q, limit=limit)
