"""
Graph loader — reads graph_final.json, validates structure,
and returns a parsed RawGraph ready for indexing.
"""
import json
import logging
from pathlib import Path
from typing import Optional, Union

from app.models.graph import RawGraph

logger = logging.getLogger(__name__)

# Default path relative to the project root (dodge_ai/)
DEFAULT_GRAPH_PATH = Path(__file__).resolve().parents[3] / "data" / "graph_final.json"


def load_graph(path: Union[Path, str, None] = None) -> RawGraph:
    graph_path = Path(path) if path else DEFAULT_GRAPH_PATH

    if not graph_path.exists():
        raise FileNotFoundError(f"Graph file not found: {graph_path}")

    logger.info("Loading graph from %s", graph_path)
    raw = json.loads(graph_path.read_text(encoding="utf-8"))

    graph = RawGraph.model_validate(raw)
    _validate(graph)

    logger.info(
        "Graph loaded: %d nodes, %d edges, %d derived relationships",
        len(graph.nodes),
        len(graph.edges),
        len(graph.derived_relationships),
    )
    return graph


def _validate(graph: RawGraph) -> None:
    node_names = {n.name for n in graph.nodes}
    errors: list[str] = []

    # Every edge must reference known nodes
    for edge in graph.edges:
        if edge.from_node not in node_names:
            errors.append(f"Edge '{edge.relationship}': unknown from-node '{edge.from_node}'")
        if edge.to_node not in node_names:
            errors.append(f"Edge '{edge.relationship}': unknown to-node '{edge.to_node}'")

    # Duplicate node names
    seen: set[str] = set()
    for node in graph.nodes:
        if node.name in seen:
            errors.append(f"Duplicate node name: '{node.name}'")
        seen.add(node.name)

    if errors:
        raise ValueError("Graph validation failed:\n" + "\n".join(f"  • {e}" for e in errors))
