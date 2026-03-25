"""
GraphService — in-memory graph index and all business logic.

Indexes built at startup:
  _nodes          : name → RawNode
  _edges          : list[RawEdge]
  _adj            : name → set of outgoing neighbour names
  _rev_adj        : name → set of incoming neighbour names
  _edge_by_node   : name → list[RawEdge] (both directions)
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Literal, Optional, Set

from app.models.graph import (
    EdgeSummary,
    ExpandResponse,
    NodeDetail,
    NodeSummary,
    RawEdge,
    RawGraph,
    RawNode,
    RecordGraphEdge,
    RecordGraphNode,
    RecordGraphResponse,
    RecordsResponse,
    SearchResult,
    UIGraph,
    UILink,
    UINode,
)


class GraphService:
    def __init__(self, graph: RawGraph, schema: Optional[dict] = None) -> None:
        self._graph = graph
        self._schema = schema  # normalized_schema.json data
        self._nodes: dict[str, RawNode] = {}
        self._edges: list[RawEdge] = graph.edges
        self._adj: dict[str, set[str]] = defaultdict(set)
        self._rev_adj: dict[str, set[str]] = defaultdict(set)
        self._edge_by_node: dict[str, list[RawEdge]] = defaultdict(list)
        self._build_index()

    # ─────────────────────────────────────────
    # Index construction
    # ─────────────────────────────────────────

    def _build_index(self) -> None:
        for node in self._graph.nodes:
            self._nodes[node.name] = node

        for edge in self._edges:
            f, t = edge.from_node, edge.to_node
            self._adj[f].add(t)
            self._rev_adj[t].add(f)
            self._edge_by_node[f].append(edge)
            self._edge_by_node[t].append(edge)

    # ─────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────

    def _node_summary(self, node: RawNode) -> NodeSummary:
        name = node.name
        return NodeSummary(
            name=name,
            source_table=node.source_table,
            primary_key=node.primary_key,
            record_count=node.record_count,
            outgoing_edge_count=sum(1 for e in self._edges if e.from_node == name),
            incoming_edge_count=sum(1 for e in self._edges if e.to_node == name),
            total_edge_count=len(self._edge_by_node.get(name, [])),
        )

    @staticmethod
    def _edge_summary(edge: RawEdge) -> EdgeSummary:
        return EdgeSummary(
            from_node=edge.from_node,
            to_node=edge.to_node,
            relationship=edge.relationship,
            type=edge.type,
            join_condition=edge.join_condition,
            cardinality=edge.cardinality,
            confidence=edge.confidence,
            optional=edge.optional,
            completeness=edge.completeness,
            filters=edge.filters,
        )

    # ─────────────────────────────────────────
    # Public API — Nodes
    # ─────────────────────────────────────────

    def get_all_nodes(self) -> list[NodeSummary]:
        return [self._node_summary(n) for n in self._graph.nodes]

    def get_node(self, name: str) -> Optional[NodeDetail]:
        node = self._nodes.get(name)
        if not node:
            return None

        outgoing = [self._edge_summary(e) for e in self._edges if e.from_node == name]
        incoming = [self._edge_summary(e) for e in self._edges if e.to_node == name]

        connected = sorted(
            {e.to_node for e in outgoing} | {e.from_node for e in incoming} - {name}
        )

        return NodeDetail(
            name=node.name,
            source_table=node.source_table,
            primary_key=node.primary_key,
            alternate_keys=node.alternate_keys or [],
            attributes=node.attributes,
            filters=node.filters,
            record_count=node.record_count,
            query_guidance=node.query_guidance,
            outgoing_edges=outgoing,
            incoming_edges=incoming,
            connected_node_names=connected,
        )

    # ─────────────────────────────────────────
    # Public API — Edges
    # ─────────────────────────────────────────

    def get_edges(
        self,
        edge_type: Optional[str] = None,
        confidence: Optional[str] = None,
        include_derived: bool = True,
    ) -> list[EdgeSummary]:
        edges = list(self._edges)

        if not include_derived:
            edges = [e for e in edges if e.type != "DERIVED"]

        if edge_type:
            edges = [e for e in edges if e.type.upper() == edge_type.upper()]

        if confidence:
            edges = [e for e in edges if e.confidence.upper() == confidence.upper()]

        return [self._edge_summary(e) for e in edges]

    # ─────────────────────────────────────────
    # Public API — Expand
    # ─────────────────────────────────────────

    def expand_node(self, name: str) -> Optional[ExpandResponse]:
        node = self._nodes.get(name)
        if not node:
            return None

        # All edges touching this node (both directions)
        touching_edges = self._edge_by_node.get(name, [])

        # Neighbour node names (excluding center)
        neighbour_names = set()
        for e in touching_edges:
            neighbour_names.add(e.from_node)
            neighbour_names.add(e.to_node)
        neighbour_names.discard(name)

        neighbour_nodes = [
            self._node_summary(self._nodes[n])
            for n in sorted(neighbour_names)
            if n in self._nodes
        ]

        edge_summaries = [self._edge_summary(e) for e in touching_edges]

        # Build UI-friendly sub-graph
        all_node_names = neighbour_names | {name}
        ui_nodes = [
            UINode(
                id=n,
                label=n,
                source_table=self._nodes[n].source_table,
                record_count=self._nodes[n].record_count,
                primary_key=self._nodes[n].primary_key,
                attributes=self._nodes[n].attributes,
            )
            for n in sorted(all_node_names)
            if n in self._nodes
        ]
        ui_links = [
            UILink(
                source=e.from_node,
                target=e.to_node,
                label=e.relationship,
                type=e.type,
                cardinality=e.cardinality,
                confidence=e.confidence,
                optional=e.optional,
            )
            for e in touching_edges
        ]

        return ExpandResponse(
            center_node=self._node_summary(node),
            nodes=neighbour_nodes,
            edges=edge_summaries,
            ui_graph=UIGraph(nodes=ui_nodes, links=ui_links),
        )

    # ─────────────────────────────────────────
    # Public API — Search
    # ─────────────────────────────────────────

    def search_nodes(self, query: str, limit: int = 10) -> list[SearchResult]:
        q = query.strip().lower()
        if not q:
            return []

        results: list[SearchResult] = []
        for node in self._graph.nodes:
            score = _match_score(node.name.lower(), q)
            if score > 0:
                results.append(
                    SearchResult(
                        name=node.name,
                        source_table=node.source_table,
                        record_count=node.record_count,
                        match_score=score,
                        primary_key=node.primary_key,
                    )
                )

        results.sort(key=lambda r: r.match_score, reverse=True)
        return results[:limit]

    # ─────────────────────────────────────────
    # Public API — Full UI graph
    # ─────────────────────────────────────────

    def get_ui_graph(
        self,
        edge_type: Optional[str] = None,
        confidence: Optional[str] = None,
        include_derived: bool = False,
    ) -> UIGraph:
        filtered_edges = self.get_edges(
            edge_type=edge_type,
            confidence=confidence,
            include_derived=include_derived,
        )

        # Only include nodes referenced by filtered edges (or all if no filter)
        if edge_type or confidence or not include_derived:
            referenced = {e.from_node for e in filtered_edges} | {e.to_node for e in filtered_edges}
            nodes_to_show = [n for n in self._graph.nodes if n.name in referenced]
        else:
            nodes_to_show = self._graph.nodes

        ui_nodes = [
            UINode(
                id=n.name,
                label=n.name,
                source_table=n.source_table,
                record_count=n.record_count,
                primary_key=n.primary_key,
                attributes=n.attributes,
            )
            for n in nodes_to_show
        ]

        ui_links = [
            UILink(
                source=e.from_node,
                target=e.to_node,
                label=e.relationship,
                type=e.type,
                cardinality=e.cardinality,
                confidence=e.confidence,
                optional=e.optional,
            )
            for e in filtered_edges
        ]

        return UIGraph(nodes=ui_nodes, links=ui_links)

    # ─────────────────────────────────────────
    # Public API — Adjacency info
    # ─────────────────────────────────────────

    def get_adjacency(self) -> dict[str, list[str]]:
        return {name: sorted(neighbours) for name, neighbours in self._adj.items()}

    # ─────────────────────────────────────────
    # Public API — Records (synthetic sample data)
    # ─────────────────────────────────────────

    def get_node_records(
        self,
        name: str,
        limit: int = 20,
        offset: int = 0,
        search: Optional[str] = None,
    ) -> Optional[RecordsResponse]:
        node = self._nodes.get(name)
        if not node:
            return None

        # Find schema info for this node's source table
        schema_info = self._find_schema(node.source_table)
        columns = schema_info["columns"] if schema_info else (
            _ensure_list(node.primary_key) + node.attributes
        )
        column_types = schema_info.get("column_types", {}) if schema_info else {}

        total = node.record_count or 20
        records = _generate_sample_records(
            columns=columns,
            column_types=column_types,
            primary_key=node.primary_key,
            total=total,
            search=search,
        )

        # Apply search filter
        if search:
            q = search.lower()
            records = [
                r for r in records
                if any(q in str(v).lower() for v in r.values())
            ]

        total_filtered = len(records)
        page = records[offset : offset + limit]

        return RecordsResponse(
            node_name=name,
            source_table=node.source_table,
            columns=columns,
            column_types=column_types,
            primary_key=node.primary_key,
            records=page,
            total_count=total_filtered,
            offset=offset,
            limit=limit,
        )

    def _find_schema(self, source_table: Optional[str]) -> Optional[dict]:
        if not source_table or not self._schema:
            return None
        schemas = self._schema.get("normalized_schema", [])
        for s in schemas:
            if s.get("table_name") == source_table:
                return s
        return None

    # ─────────────────────────────────────────
    # Public API — Record-level graph
    # ─────────────────────────────────────────

    _ENTITY_COLORS = [
        "#e8a0a0", "#93c5fd", "#86efac", "#fde68a", "#c4b5fd",
        "#f9a8d4", "#67e8f9", "#fdba74", "#a5b4fc", "#6ee7b7",
    ]

    def get_record_graph(self, records_per_entity: int = 5) -> RecordGraphResponse:
        """Build a record-level graph: nodes are rows, edges are FK joins."""

        # Assign a colour to each entity for frontend rendering
        entity_colors: dict[str, str] = {}
        for i, node in enumerate(self._graph.nodes):
            entity_colors[node.name] = self._ENTITY_COLORS[i % len(self._ENTITY_COLORS)]

        # Generate sample records per entity
        entity_records: dict[str, list[dict]] = {}
        for node in self._graph.nodes:
            schema_info = self._find_schema(node.source_table)
            columns = schema_info["columns"] if schema_info else (
                _ensure_list(node.primary_key) + node.attributes
            )
            column_types = schema_info.get("column_types", {}) if schema_info else {}
            rows = _generate_sample_records(
                columns=columns,
                column_types=column_types,
                primary_key=node.primary_key,
                total=records_per_entity,
            )
            entity_records[node.name] = rows

        # Build record graph nodes
        graph_nodes: list[RecordGraphNode] = []
        node_ids_by_entity: dict[str, list[str]] = defaultdict(list)

        for entity_name, rows in entity_records.items():
            node = self._nodes[entity_name]
            pks = _ensure_list(node.primary_key)
            for i, row in enumerate(rows):
                pk_val = "_".join(str(row.get(pk, i)) for pk in pks)
                node_id = f"{entity_name}:{pk_val}"
                graph_nodes.append(RecordGraphNode(
                    id=node_id,
                    entity=entity_name,
                    primary_key_value=pk_val,
                    fields=row,
                ))
                node_ids_by_entity[entity_name].append(node_id)

        # Build record graph edges based on schema-level FK joins
        graph_edges: list[RecordGraphEdge] = []
        for edge in self._edges:
            src_entity = edge.from_node
            tgt_entity = edge.to_node
            src_ids = node_ids_by_entity.get(src_entity, [])
            tgt_ids = node_ids_by_entity.get(tgt_entity, [])
            if not src_ids or not tgt_ids:
                continue

            # Try to parse join condition to find matching FK columns
            fk_col = _parse_join_column(edge.join_condition)

            src_rows = entity_records.get(src_entity, [])
            tgt_rows = entity_records.get(tgt_entity, [])

            if fk_col:
                # Match records by FK value
                tgt_index: dict[str, list[int]] = defaultdict(list)
                for j, tgt_row in enumerate(tgt_rows):
                    val = str(tgt_row.get(fk_col, ""))
                    if val:
                        tgt_index[val].append(j)

                for i, src_row in enumerate(src_rows):
                    val = str(src_row.get(fk_col, ""))
                    if val and val in tgt_index:
                        for j in tgt_index[val]:
                            graph_edges.append(RecordGraphEdge(
                                source=src_ids[i],
                                target=tgt_ids[j],
                                relationship=edge.relationship,
                            ))
                    elif i < len(tgt_ids):
                        # Fallback: pair by index if FK doesn't match
                        graph_edges.append(RecordGraphEdge(
                            source=src_ids[i],
                            target=tgt_ids[min(i, len(tgt_ids) - 1)],
                            relationship=edge.relationship,
                        ))
            else:
                # No parseable FK — pair records by index
                for i, src_id in enumerate(src_ids):
                    tgt_id = tgt_ids[min(i, len(tgt_ids) - 1)]
                    graph_edges.append(RecordGraphEdge(
                        source=src_id,
                        target=tgt_id,
                        relationship=edge.relationship,
                    ))

        return RecordGraphResponse(
            nodes=graph_nodes,
            edges=graph_edges,
            entity_colors=entity_colors,
        )

    def get_graph_stats(self) -> dict:
        structural = sum(1 for e in self._edges if e.type == "STRUCTURAL")
        filtered = sum(1 for e in self._edges if e.type == "FILTERED")
        derived_rel = len(self._graph.derived_relationships)
        return {
            "nodes": len(self._nodes),
            "edges": len(self._edges),
            "structural_edges": structural,
            "filtered_edges": filtered,
            "derived_relationships": derived_rel,
            "version": self._graph.version,
        }


# ─────────────────────────────────────────────
# Fuzzy match scoring (no external deps)
# ─────────────────────────────────────────────

def _match_score(name: str, query: str) -> int:
    """Return match score 0–100. 0 means no match."""
    if name == query:
        return 100
    if name.startswith(query):
        return 90
    if query in name:
        return 75
    # Case-insensitive substring on words
    words = name.replace("_", " ").split()
    if any(w.startswith(query) for w in words):
        return 60
    if any(query in w for w in words):
        return 50
    # Subsequence match
    if _is_subsequence(query, name):
        return 30
    return 0


def _is_subsequence(sub: str, s: str) -> bool:
    it = iter(s)
    return all(c in it for c in sub)


# ─────────────────────────────────────────────
# Synthetic sample data generation
# ─────────────────────────────────────────────

def _ensure_list(val: Union[str, list]) -> list:
    return val if isinstance(val, list) else [val]


import hashlib
import random as _random
from typing import Union

# Deterministic sample data so results are stable across requests
_SAMPLE_NAMES = [
    "Acme Corp", "Global Tech", "Star Industries", "Blue Wave", "Metro Systems",
    "Nordic Solutions", "Alpine Group", "Pacific Trading", "Delta Electronics", "Vertex Labs",
    "Quantum Dynamics", "Horizon Partners", "Atlas Manufacturing", "Pinnacle Logistics", "Evergreen Retail",
    "Summit Financial", "Oceanic Exports", "Titan Engineering", "Nova Biotech", "Radiant Energy",
]
_SAMPLE_CITIES = [
    "Mumbai", "Delhi", "Bangalore", "Chennai", "Hyderabad",
    "Pune", "Kolkata", "Ahmedabad", "Jaipur", "Lucknow",
    "Berlin", "Munich", "Hamburg", "Frankfurt", "Stuttgart",
    "New York", "Chicago", "Houston", "Phoenix", "San Antonio",
]
_SAMPLE_COUNTRIES = ["IN", "DE", "US", "GB", "JP", "SG", "AU", "FR", "CA", "BR"]
_SAMPLE_CURRENCIES = ["INR", "EUR", "USD", "GBP", "JPY", "SGD"]


import re as _re


def _parse_join_column(join_condition: str) -> Optional[str]:
    """Extract the shared column name from a join condition like 'A.col = B.col'."""
    m = _re.search(r"\.(\w+)\s*=\s*\w+\.(\w+)", join_condition)
    if m:
        # Return the column that appears on both sides, or just the first
        return m.group(1)
    return None


def _generate_sample_records(
    columns: list[str],
    column_types: dict[str, str],
    primary_key: Union[str, list[str]],
    total: int,
    search: Optional[str] = None,
) -> list[dict]:
    """Generate deterministic synthetic records based on column types."""
    rng = _random.Random(42)  # deterministic seed
    pks = _ensure_list(primary_key)
    count = min(total, 50)  # cap at 50 synthetic rows

    records = []
    for i in range(count):
        row: dict = {}
        for col in columns:
            col_type = column_types.get(col, "").upper()
            row[col] = _generate_value(col, col_type, i, rng, pks)
        records.append(row)

    return records


def _generate_value(
    col: str, col_type: str, row_idx: int, rng: _random.Random, pks: list[str]
) -> Union[str, int, float, bool, None]:
    """Generate a realistic value based on column name and type heuristics."""
    cl = col.lower()

    # Primary key fields — sequential IDs
    if col in pks:
        if "int" in col_type.lower() or "number" in col_type.lower():
            return 1000000 + row_idx
        return f"{row_idx + 1:010d}"

    # ID/key fields
    if cl.endswith("_id") or cl.endswith("_number") or cl == "id":
        seed = hashlib.md5(f"{col}_{row_idx}".encode()).hexdigest()[:8]
        return f"{int(seed, 16) % 90000000 + 10000000}"

    # Name fields
    if "name" in cl and "customer" in cl:
        return _SAMPLE_NAMES[row_idx % len(_SAMPLE_NAMES)]
    if "name" in cl and "city" in cl:
        return _SAMPLE_CITIES[row_idx % len(_SAMPLE_CITIES)]
    if "name" in cl or "description" in cl:
        return f"{col.replace('_', ' ').title()} {row_idx + 1}"

    # Currency
    if cl in ("currency", "transaction_currency", "company_code_currency"):
        return _SAMPLE_CURRENCIES[row_idx % len(_SAMPLE_CURRENCIES)]

    # Country
    if cl in ("country", "country_code"):
        return _SAMPLE_COUNTRIES[row_idx % len(_SAMPLE_COUNTRIES)]

    # City
    if "city" in cl:
        return _SAMPLE_CITIES[row_idx % len(_SAMPLE_CITIES)]

    # Region / postal code
    if "region" in cl:
        return f"R{(row_idx % 10) + 1:02d}"
    if "postal" in cl or "zip" in cl:
        return f"{10000 + rng.randint(0, 89999)}"

    # Amounts
    if "amount" in cl or "price" in cl or "value" in cl or "total" in cl or "net" in cl:
        sign = -1 if "credit" in cl else 1
        return sign * round(rng.uniform(100, 50000), 2)

    # Quantities
    if "quantity" in cl or "qty" in cl or "count" in cl:
        return rng.randint(1, 500)

    # Boolean flags
    if cl.startswith("is_") or cl.startswith("has_") or "indicator" in cl or "flag" in cl:
        return rng.choice([True, False])
    if "BOOLEAN" in col_type:
        return rng.choice([True, False])

    # Dates
    if "date" in cl or "created_at" in cl or "valid_from" in cl or "valid_to" in cl:
        month = (row_idx % 12) + 1
        day = (row_idx % 28) + 1
        return f"2025-{month:02d}-{day:02d}T00:00:00.000Z"
    if "TIMESTAMP" in col_type or "DATE" in col_type:
        month = (row_idx % 12) + 1
        day = (row_idx % 28) + 1
        return f"2025-{month:02d}-{day:02d}T00:00:00.000Z"

    # Document type codes
    if "type" in cl or "category" in cl or "group" in cl or "code" in cl:
        codes = ["A", "B", "C", "D", "OR", "RE", "RV", "ZF2"]
        return codes[row_idx % len(codes)]

    # Company code
    if "company" in cl:
        return f"{(row_idx % 4) + 1:04d}"

    # Integer types
    if "INT" in col_type or "NUMBER" in col_type:
        return rng.randint(1, 10000)

    # Decimal types
    if "DECIMAL" in col_type or "FLOAT" in col_type or "NUMERIC" in col_type:
        return round(rng.uniform(0, 10000), 2)

    # CHAR(1) — single character codes
    if "CHAR(1)" in col_type:
        return rng.choice(["1", "2", "A", "B", "X"])

    # Fall back to generic string
    if "VARCHAR" in col_type or "CHAR" in col_type or "TEXT" in col_type:
        return f"{col.replace('_', ' ').title()} {row_idx + 1}"

    # Default
    return f"val_{row_idx + 1}"
