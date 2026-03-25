"""
Dependency injection — provides a single GraphService instance
throughout the app lifecycle.
"""
from typing import Optional

from app.services.graph_service import GraphService

_service: Optional[GraphService] = None


def init_service(service: GraphService) -> None:
    global _service
    _service = service


def get_graph_service() -> GraphService:
    assert _service is not None, "GraphService not initialised"
    return _service
