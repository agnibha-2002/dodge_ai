"""
Graph Analytics — pure-Python structural analysis of the entity graph.

Computes:
  1. Degree centrality   — how many entities each entity connects to (hub detection)
  2. Label-propagation communities — clusters of closely related entities
  3. Articulation points — bridge entities whose removal disconnects the graph

These analytics are injected into the LLM planner prompt and response generator
to improve intent classification, traversal path selection, and answer quality.

All algorithms run in O(V + E) or O(V²) time and are safe for ERP graphs
with ~20 entities.  Results are cached per GraphService instance.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.graph_service import GraphService

# Module-level cache: id(svc) → GraphAnalytics
_cache: dict[int, "GraphAnalytics"] = {}


# ─────────────────────────────────────────────
# Data model
# ─────────────────────────────────────────────

@dataclass
class GraphAnalytics:
    """Structural analytics for an entity graph."""

    # entity → number of bidirectional neighbors
    degree: dict[str, int] = field(default_factory=dict)

    # entity → community index (0-based, largest cluster = 0)
    entity_to_community: dict[str, int] = field(default_factory=dict)

    # list[list[entity]] — each inner list is one community, sorted by size desc
    communities: list[list[str]] = field(default_factory=list)

    # entities whose removal disconnects the graph (Tarjan articulation points)
    bridge_entities: list[str] = field(default_factory=list)

    # [(entity, degree)] sorted descending by degree
    hub_entities: list[tuple[str, int]] = field(default_factory=list)


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────

def build_analytics(svc: "GraphService") -> GraphAnalytics:
    """
    Compute (or return cached) graph analytics for a GraphService instance.
    Safe to call on every request — O(1) after first call per service instance.
    """
    key = id(svc)
    if key in _cache:
        return _cache[key]
    result = _compute(svc)
    _cache[key] = result
    return result


def format_analytics_for_prompt(analytics: GraphAnalytics) -> str:
    """
    Render graph analytics as a concise, structured string for the LLM prompt.
    Focuses only on information that improves planning decisions.
    """
    lines: list[str] = []

    # ── Communities ───────────────────────────
    if analytics.communities:
        lines.append("Entity communities (closely related groups — prefer intra-cluster traversals):")
        for i, members in enumerate(analytics.communities):
            if members:
                lines.append(f"  Cluster {i + 1}: {', '.join(members)}")

    # ── Hub entities (top 5) ──────────────────
    if analytics.hub_entities:
        lines.append(
            "Hub entities (most connected — use as traversal anchors for ambiguous queries):"
        )
        for entity, deg in analytics.hub_entities[:5]:
            lines.append(f"  {entity}: {deg} direct connection{'s' if deg != 1 else ''}")

    # ── Bridge entities ───────────────────────
    if analytics.bridge_entities:
        lines.append(
            "Bridge entities (sole connectors between clusters — required for cross-cluster traversals):"
        )
        for entity in analytics.bridge_entities:
            community_idx = analytics.entity_to_community.get(entity, -1)
            parts = []
            for ci, members in enumerate(analytics.communities):
                if entity in members and any(
                    analytics.entity_to_community.get(n, -1) != community_idx
                    for n in _get_neighbors_from_analytics(entity, analytics)
                ):
                    parts.append(f"Cluster {ci + 1}")
            lines.append(f"  {entity}")

    return "\n".join(lines)


def cluster_context_for_entities(
    entities: list[str],
    analytics: GraphAnalytics,
) -> str:
    """
    Describe which clusters the given entities belong to.
    Used by the response generator to enrich answers.
    """
    if not entities or not analytics.communities:
        return ""
    seen: set[int] = set()
    parts: list[str] = []
    for entity in entities:
        ci = analytics.entity_to_community.get(entity, -1)
        if ci != -1 and ci not in seen:
            seen.add(ci)
            members = analytics.communities[ci]
            parts.append(
                f"Cluster {ci + 1} ({', '.join(m for m in members if m != entity or len(members) == 1)})"
            )
    if not parts:
        return ""
    return "Involved clusters: " + "; ".join(parts)


def suggest_related_entities(
    entity: str,
    analytics: GraphAnalytics,
) -> list[str]:
    """
    Return other entities in the same cluster as `entity`.
    Used to suggest alternatives when a query returns empty results.
    """
    ci = analytics.entity_to_community.get(entity, -1)
    if ci == -1:
        return []
    return [e for e in analytics.communities[ci] if e != entity]


# ─────────────────────────────────────────────
# Internal: compute analytics
# ─────────────────────────────────────────────

def _compute(svc: "GraphService") -> GraphAnalytics:
    entities = [n.name for n in svc._graph.nodes]

    # Build undirected (bidirectional) adjacency
    adj: dict[str, set[str]] = defaultdict(set)
    for edge in svc._edges:
        adj[edge.from_node].add(edge.to_node)
        adj[edge.to_node].add(edge.from_node)

    # 1. Degree centrality
    degree = {e: len(adj.get(e, set())) for e in entities}
    hub_entities = sorted(degree.items(), key=lambda x: x[1], reverse=True)

    # 2. Community detection
    entity_to_community, communities = _label_propagation(entities, adj)

    # 3. Articulation points
    bridge_entities = _find_articulation_points(entities, adj)

    return GraphAnalytics(
        degree=degree,
        hub_entities=hub_entities,
        entity_to_community=entity_to_community,
        communities=communities,
        bridge_entities=bridge_entities,
    )


def _label_propagation(
    entities: list[str],
    adj: dict[str, set[str]],
) -> tuple[dict[str, int], list[list[str]]]:
    """
    Label propagation community detection.

    Each entity starts with its own label.  On each iteration every entity
    adopts the most common label among its neighbors.  Converges in < 20
    rounds for typical ERP graphs.  Processing order is sorted for
    deterministic output.
    """
    if not entities:
        return {}, []

    # Isolated entities (no edges) stay in their own singleton community
    labels: dict[str, str] = {e: e for e in entities}

    for _ in range(20):
        changed = False
        for entity in sorted(entities):
            neighbors = adj.get(entity, set())
            if not neighbors:
                continue
            label_count: dict[str, int] = {}
            for n in neighbors:
                lbl = labels.get(n, n)
                label_count[lbl] = label_count.get(lbl, 0) + 1
            # Most-frequent label; break ties lexicographically for determinism
            best = max(label_count, key=lambda l: (label_count[l], l))
            if best != labels[entity]:
                labels[entity] = best
                changed = True
        if not changed:
            break

    # Group entities by community label
    community_groups: dict[str, list[str]] = defaultdict(list)
    for entity in entities:
        community_groups[labels[entity]].append(entity)

    # Sort communities by size desc; sort members within each community
    sorted_communities = sorted(
        [sorted(members) for members in community_groups.values()],
        key=len,
        reverse=True,
    )

    entity_to_community: dict[str, int] = {}
    for idx, members in enumerate(sorted_communities):
        for entity in members:
            entity_to_community[entity] = idx

    return entity_to_community, sorted_communities


def _find_articulation_points(
    entities: list[str],
    adj: dict[str, set[str]],
) -> list[str]:
    """
    Tarjan's algorithm for articulation points (cut vertices).

    An articulation point is an entity whose removal increases the number of
    connected components — i.e., it is the sole bridge between sub-graphs.
    These entities are critical routing nodes for cross-cluster queries.

    Iterative DFS to avoid Python recursion limit.
    """
    if len(entities) <= 2:
        return []

    disc: dict[str, int] = {}
    low: dict[str, int] = {}
    parent: dict[str, str | None] = {}
    aps: set[str] = set()
    timer = [0]

    def _dfs_iterative(root: str) -> None:
        # Stack entries: (entity, iterator_over_children, child_count)
        stack: list[tuple[str, list[str], list[int]]] = []
        parent[root] = None
        disc[root] = low[root] = timer[0]
        timer[0] += 1
        stack.append((root, sorted(adj.get(root, [])), [0]))

        while stack:
            u, children, child_count = stack[-1]

            # Find next unvisited child
            advanced = False
            while children:
                v = children[0]
                if v not in disc:
                    # Tree edge: visit v
                    children.pop(0)
                    child_count[0] += 1
                    parent[v] = u
                    disc[v] = low[v] = timer[0]
                    timer[0] += 1
                    stack.append((v, sorted(adj.get(v, [])), [0]))
                    advanced = True
                    break
                elif v != parent.get(u):
                    # Back edge: update low
                    low[u] = min(low[u], disc[v])
                    children.pop(0)
                else:
                    children.pop(0)

            if not advanced:
                # Done with u — propagate low upward
                stack.pop()
                if stack:
                    p = stack[-1][0]
                    # Update parent's low
                    low[p] = min(low[p], low[u])
                    # Check articulation point conditions
                    if parent.get(p) is None:
                        # Root AP condition: root with 2+ children
                        if stack[-1][2][0] > 1:
                            aps.add(p)
                    else:
                        if low[u] >= disc[p]:
                            aps.add(p)

    for entity in sorted(entities):
        if entity not in disc:
            _dfs_iterative(entity)

    return sorted(aps)


def _get_neighbors_from_analytics(
    entity: str, analytics: GraphAnalytics
) -> list[str]:
    """Helper: infer neighbors from hub_entities and community data."""
    # Used only for formatting — return community peers as a proxy
    ci = analytics.entity_to_community.get(entity, -1)
    if ci == -1:
        return []
    return [e for e in analytics.communities[ci] if e != entity]
