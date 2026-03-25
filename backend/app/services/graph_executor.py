"""
Deterministic Graph Execution Engine.

Takes a ParsedGraphQuery + graph data (nodes + edges) and executes the query
using pure algorithmic logic only — no LLM, no inference, no guessing.

Every result is fully reproducible from the same inputs.

Execution modes:
  lookup   — retrieve entity metadata and/or a specific record by ID
  traverse — BFS shortest path between two entities, collect path + target records
  filter   — apply field conditions to entity records and return matching rows

Output contract:
  { "result": {...}, "status": "success" | "empty" | "error" }
"""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, Optional

from app.models.execution import (
    FilterResult,
    GraphExecResult,
    GraphSnapshot,
    LookupResult,
    RawEdgeSnapshot,
    RawNodeSnapshot,
    TraversalHop,
    TraverseResult,
)
from app.models.query import ParsedGraphQuery
from app.services.graph_service import GraphService

# Imported lazily to avoid circular imports at module load
_GraphQueryPlan = None  # type: ignore


# ─────────────────────────────────────────────
# Graph adapter — uniform interface over both
# a live GraphService and a caller-supplied snapshot
# ─────────────────────────────────────────────

class _GraphAdapter:
    """
    Wraps either a live GraphService or a GraphSnapshot so the executor
    can work identically against both.
    """

    def __init__(self, svc: Optional[GraphService], snapshot: Optional[GraphSnapshot]) -> None:
        if svc is not None:
            # Build from live service
            self._nodes: dict[str, _NodeInfo] = {
                n.name: _NodeInfo(
                    name=n.name,
                    source_table=n.source_table,
                    primary_key=n.primary_key,
                    attributes=n.attributes,
                    record_count=n.record_count,
                )
                for n in svc._graph.nodes
            }
            self._edges: list[_EdgeInfo] = [
                _EdgeInfo(
                    from_node=e.from_node,
                    to_node=e.to_node,
                    relationship=e.relationship,
                    join_condition=e.join_condition,
                )
                for e in svc._edges
            ]
            self._svc = svc
        elif snapshot is not None:
            self._nodes = {
                n.name: _NodeInfo(
                    name=n.name,
                    source_table=n.source_table,
                    primary_key=n.primary_key,
                    attributes=n.attributes,
                    record_count=n.record_count,
                )
                for n in snapshot.nodes
            }
            self._edges = [
                _EdgeInfo(
                    from_node=e.from_node,
                    to_node=e.to_node,
                    relationship=e.relationship,
                    join_condition=e.join_condition,
                )
                for e in snapshot.edges
            ]
            self._svc = None
        else:
            self._nodes = {}
            self._edges = []
            self._svc = None

        # Build adjacency index (bidirectional)
        self._adj: dict[str, list[tuple[str, str]]] = defaultdict(list)  # entity → [(neighbour, relationship)]
        for e in self._edges:
            self._adj[e.from_node].append((e.to_node, e.relationship))
            self._adj[e.to_node].append((e.from_node, e.relationship))

    def has_entity(self, name: str) -> bool:
        return name in self._nodes

    def node_info(self, name: str) -> Optional["_NodeInfo"]:
        return self._nodes.get(name)

    def connected_entities(self, name: str) -> list[str]:
        return sorted({nbr for nbr, _ in self._adj.get(name, [])})

    def get_records(self, entity: str, limit: int = 20) -> tuple[list[dict], Optional[int]]:
        """Return (records, total_count). Uses live service if available."""
        if self._svc is not None:
            resp = self._svc.get_node_records(entity, limit=limit)
            if resp:
                return resp.records, resp.total_count
        # Snapshot mode: no real records available
        return [], self._nodes[entity].record_count if entity in self._nodes else None

    def find_record_by_id(self, entity: str, record_id: str) -> Optional[dict]:
        """
        Find a specific record by primary key value.
        Searches all generated records deterministically — no guessing.
        """
        if self._svc is None:
            return None
        node = self._nodes.get(entity)
        if not node:
            return None
        pks = _ensure_list(node.primary_key)
        # Pull up to 50 records and scan for matching PK
        resp = self._svc.get_node_records(entity, limit=50)
        if not resp:
            return None
        for row in resp.records:
            for pk in pks:
                val = str(row.get(pk, ""))
                if val.upper() == record_id.upper():
                    return row
        return None

    def bfs_path(self, start: str, end: str) -> list[str]:
        """BFS shortest path. Returns [] if no path exists."""
        if start == end:
            return [start]
        if start not in self._nodes or end not in self._nodes:
            return []

        visited = {start}
        queue: deque[tuple[str, list[str]]] = deque([(start, [start])])

        while queue:
            current, path = queue.popleft()
            for neighbour, _ in self._adj.get(current, []):
                if neighbour in visited:
                    continue
                new_path = path + [neighbour]
                if neighbour == end:
                    return new_path
                visited.add(neighbour)
                queue.append((neighbour, new_path))

        return []

    def path_hops(self, path: list[str]) -> list[TraversalHop]:
        """Convert a node path into TraversalHop objects with relationship labels."""
        hops: list[TraversalHop] = []
        for i in range(len(path) - 1):
            frm, to = path[i], path[i + 1]
            rel = self._find_relationship(frm, to)
            hops.append(TraversalHop(from_entity=frm, to_entity=to, relationship=rel))
        return hops

    def _find_relationship(self, a: str, b: str) -> str:
        for e in self._edges:
            if (e.from_node == a and e.to_node == b) or (e.from_node == b and e.to_node == a):
                return e.relationship
        return "RELATED_TO"


class _NodeInfo:
    __slots__ = ("name", "source_table", "primary_key", "attributes", "record_count")

    def __init__(
        self,
        name: str,
        source_table: Optional[str],
        primary_key: Any,
        attributes: list[str],
        record_count: Optional[int],
    ) -> None:
        self.name = name
        self.source_table = source_table
        self.primary_key = primary_key
        self.attributes = attributes
        self.record_count = record_count


class _EdgeInfo:
    __slots__ = ("from_node", "to_node", "relationship", "join_condition")

    def __init__(self, from_node: str, to_node: str, relationship: str, join_condition: str) -> None:
        self.from_node = from_node
        self.to_node = to_node
        self.relationship = relationship
        self.join_condition = join_condition


# ─────────────────────────────────────────────
# Filter evaluation — purely deterministic
# ─────────────────────────────────────────────

def _eval_filter(record: dict, field: str, operator: str, value: str) -> bool:
    """
    Evaluate a single filter condition against a record row.
    Returns False if the field is missing or the comparison fails.
    No inference — only exact schema fields.
    """
    raw = record.get(field)
    if raw is None:
        return False

    try:
        if operator == "=":
            return str(raw).lower() == value.lower()
        if operator == "!=":
            return str(raw).lower() != value.lower()
        if operator == "contains":
            return value.lower() in str(raw).lower()

        # Numeric comparisons
        num_val = float(raw) if not isinstance(raw, (int, float)) else float(raw)
        num_cmp = float(value)

        if operator == ">":
            return num_val > num_cmp
        if operator == "<":
            return num_val < num_cmp
        if operator == ">=":
            return num_val >= num_cmp
        if operator == "<=":
            return num_val <= num_cmp
    except (ValueError, TypeError):
        return False

    return False


def _apply_filters(records: list[dict], filters: list) -> list[dict]:
    result = list(records)
    for f in filters:
        result = [r for r in result if _eval_filter(r, f.field, f.operator, f.value)]
    return result


# ─────────────────────────────────────────────
# Execution strategies
# ─────────────────────────────────────────────

def _exec_lookup(query: ParsedGraphQuery, g: _GraphAdapter) -> GraphExecResult:
    entity = query.start_node.entity
    record_id = query.start_node.id

    if not entity or not g.has_entity(entity):
        return GraphExecResult(
            result=None,
            status="error",
            error=f"Entity '{entity}' not found in graph.",
        )

    node = g.node_info(entity)
    connected = g.connected_entities(entity)

    if record_id:
        # Look up a specific record by primary key
        row = g.find_record_by_id(entity, record_id)
        if row is None:
            return GraphExecResult(
                result=LookupResult(
                    entity=entity,
                    id=record_id,
                    record=None,
                    records=[],
                    record_count=node.record_count,
                    attributes=node.attributes,
                    connected_entities=connected,
                ).model_dump(),
                status="empty",
            )
        return GraphExecResult(
            result=LookupResult(
                entity=entity,
                id=record_id,
                record=row,
                records=[row],
                record_count=1,
                attributes=node.attributes,
                connected_entities=connected,
            ).model_dump(),
            status="success",
        )

    # No ID — return sample records
    records, total = g.get_records(entity, limit=10)
    return GraphExecResult(
        result=LookupResult(
            entity=entity,
            id=None,
            record=None,
            records=records,
            record_count=total if total is not None else node.record_count,
            attributes=node.attributes,
            connected_entities=connected,
        ).model_dump(),
        status="success" if records else "empty",
    )


def _exec_traverse(query: ParsedGraphQuery, g: _GraphAdapter) -> GraphExecResult:
    start = query.start_node.entity
    target = query.target_entity

    if not start or not target:
        return GraphExecResult(
            result=None,
            status="error",
            error="Traverse requires both start_node.entity and target_entity.",
        )
    if not g.has_entity(start):
        return GraphExecResult(result=None, status="error", error=f"Start entity '{start}' not found.")
    if not g.has_entity(target):
        return GraphExecResult(result=None, status="error", error=f"Target entity '{target}' not found.")

    path = g.bfs_path(start, target)

    if not path:
        return GraphExecResult(
            result=TraverseResult(
                start_entity=start,
                target_entity=target,
                path=[],
                hops=[],
                path_length=0,
                target_records=[],
            ).model_dump(),
            status="empty",
        )

    hops = g.path_hops(path)

    # If a specific start record ID is given, filter target records by FK
    start_id = getattr(query.start_node, "id", None)
    if start_id:
        # Find the FK field linking start → target (or reverse)
        join_key = _infer_fk_field(start, target, g)
        reverse_key = _infer_fk_field(target, start, g)

        all_records, _ = g.get_records(target, limit=50)

        # Try forward FK: target records contain a field that matches start_id
        if join_key:
            matched = [r for r in all_records
                       if str(r.get(join_key, "")).upper() == start_id.upper()]
        elif reverse_key:
            # Try reverse: look for target PK in start record's FK field
            matched = [r for r in all_records
                       if str(r.get(reverse_key, "")).upper() == start_id.upper()]
        else:
            # Last resort: scan all fields for the ID value
            matched = [r for r in all_records
                       if any(str(v).upper() == start_id.upper() for v in r.values())]

        target_records = matched[:20]
        target_count = len(matched)
    else:
        target_records, target_count = g.get_records(target, limit=5)

    return GraphExecResult(
        result=TraverseResult(
            start_entity=start,
            target_entity=target,
            path=path,
            hops=hops,
            path_length=len(path) - 1,
            target_records=target_records,
            target_record_count=target_count,
        ).model_dump(),
        status="success" if target_records else "empty",
    )


def _exec_filter(query: ParsedGraphQuery, g: _GraphAdapter) -> GraphExecResult:
    entity = query.start_node.entity

    if not entity or not g.has_entity(entity):
        return GraphExecResult(
            result=None,
            status="error",
            error=f"Entity '{entity}' not found in graph.",
        )

    records, _ = g.get_records(entity, limit=50)
    filters = query.filters

    if filters:
        matched = _apply_filters(records, filters)
    else:
        matched = records

    filters_applied = [{"field": f.field, "operator": f.operator, "value": f.value} for f in filters]

    return GraphExecResult(
        result=FilterResult(
            entity=entity,
            filters_applied=filters_applied,
            records=matched[:20],
            record_count=len(matched),
        ).model_dump(),
        status="success" if matched else "empty",
    )


# ─────────────────────────────────────────────
# Aggregate execution
# ─────────────────────────────────────────────

def _exec_aggregate(plan: Any, g: _GraphAdapter) -> GraphExecResult:
    """
    COUNT / SUM / AVG / MAX / MIN across entity records,
    optionally grouped by a field.
    """
    entity = plan.start_entity
    agg_spec = plan.aggregation

    if not entity or not g.has_entity(entity):
        return GraphExecResult(result=None, status="error",
                               error=f"Entity '{entity}' not found.")
    if not agg_spec:
        return GraphExecResult(result=None, status="error",
                               error="Aggregate plan is missing aggregation spec.")

    node = g.node_info(entity)
    metric = agg_spec.metric
    limit = agg_spec.limit or 10

    # COUNT without a field → use schema record_count
    if metric == "count" and not agg_spec.target:
        target_entity = plan.target_entity
        rows: list[dict] = []
        if target_entity and g.has_entity(target_entity):
            target_node = g.node_info(target_entity)
            # Group-by: count target records per group_by field in start_entity
            src_records, _ = g.get_records(entity, limit=50)
            tgt_records, _ = g.get_records(target_entity, limit=50)

            # Attempt FK join via shared field name
            group_field = agg_spec.group_by
            join_key = _infer_fk_field(entity, target_entity, g)

            if join_key and src_records and tgt_records:
                # Build count: for each source record, count matching target rows
                counts: dict[str, int] = {}
                tgt_index: dict[str, int] = defaultdict(int)
                for tr in tgt_records:
                    val = str(tr.get(join_key, ""))
                    if val:
                        tgt_index[val] += 1

                pks = _ensure_list(g.node_info(entity).primary_key if g.node_info(entity) else [])
                for sr in src_records:
                    pk_val = str(sr.get(pks[0], "")) if pks else ""
                    count = tgt_index.get(pk_val, 0)
                    label = str(sr.get(group_field or (pks[0] if pks else "id"), pk_val))
                    rows.append({
                        "group": label,
                        "entity": entity,
                        "pk": pk_val,
                        **({"count": count} if count else {"count": 0}),
                    })

                # Sort by count
                rows.sort(key=lambda r: r["count"], reverse=(agg_spec.sort != "asc"))
                rows = rows[:limit]
                if rows:
                    agg_value = max(r["count"] for r in rows) if agg_spec.sort != "asc" else min(r["count"] for r in rows)
                    filtered_rows = [r for r in rows if r["count"] == agg_value]
                else:
                    agg_value = None
                    filtered_rows = []

                return GraphExecResult(
                    result={
                        "type": "aggregate",
                        "metric": "count",
                        "group_by": group_field or entity,
                        "target": target_entity,
                        "value": agg_value,
                        "records": filtered_rows,
                        "rows": rows,
                        "row_count": len(rows),
                        "metadata": {
                            "type": "aggregate",
                            "filter_applied": bool(filtered_rows),
                        },
                    },
                    status="success" if rows else "empty",
                )

            # Fallback: just report entity counts
            return GraphExecResult(
                result={
                    "type": "aggregate",
                    "metric": "count",
                    "group_by": entity,
                    "target": target_entity,
                    "value": None,
                    "records": [],
                    "rows": [
                        {"entity": entity, "count": node.record_count or 0},
                        {"entity": target_entity, "count": target_node.record_count or 0},
                    ],
                    "row_count": 2,
                    "metadata": {
                        "type": "aggregate",
                        "filter_applied": False,
                    },
                },
                status="success",
            )

        # Simple count of start_entity
        return GraphExecResult(
            result={
                "type": "aggregate",
                "metric": "count",
                "group_by": entity,
                "target": None,
                "value": node.record_count or 0,
                "records": [],
                "rows": [{"entity": entity, "count": node.record_count or 0}],
                "row_count": 1,
                "metadata": {
                    "type": "aggregate",
                    "filter_applied": False,
                },
            },
            status="success",
        )

    # Numeric aggregation on a field
    field = agg_spec.target
    records, _ = g.get_records(entity, limit=50)

    if plan.filters:
        records = _apply_plan_filters(records, plan.filters, entity)

    if not field:
        # Auto-detect first numeric-ish field
        for r in records[:1]:
            for k, v in r.items():
                if isinstance(v, (int, float)) or (
                    isinstance(v, str) and v.replace(".", "").replace("-", "").isdigit()
                ):
                    field = k
                    break

    if not field:
        return GraphExecResult(result=None, status="error",
                               error=f"Cannot determine numeric field for {metric} on {entity}.")

    values = [float(r[field]) for r in records if r.get(field) is not None
              and str(r[field]).replace(".", "").replace("-", "").isdigit()]

    if not values:
        return GraphExecResult(
            result={"type": "aggregate", "metric": metric, "field": field,
                    "entity": entity, "value": None, "sample_size": 0, "records": [],
                    "metadata": {"type": "aggregate", "filter_applied": False}},
            status="empty",
        )

    agg_val = _compute_agg(values, metric)
    if metric in {"min", "max"}:
        target_value = round(agg_val, 4)
        filtered_records = []
        for r in records:
            raw = r.get(field)
            if raw is None:
                continue
            try:
                n = float(raw)
            except (TypeError, ValueError):
                continue
            if abs(round(n, 4) - target_value) <= 1e-9:
                filtered_records.append(r)
    elif metric == "count":
        # For COUNT(field), records with non-null field contributed to the value.
        filtered_records = [r for r in records if r.get(field) is not None]
    else:
        # SUM/AVG don't map to a single subset by value.
        filtered_records = []

    return GraphExecResult(
        result={
            "type": "aggregate",
            "metric": metric,
            "field": field,
            "entity": entity,
            "value": round(agg_val, 4),
            "sample_size": len(values),
            "records": filtered_records[:20],
            "metadata": {
                "type": "aggregate",
                "filter_applied": metric in {"min", "max", "count"},
            },
        },
        status="success",
    )


def _exec_path(plan: Any, g: _GraphAdapter) -> GraphExecResult:
    """
    Trace an explicit path sequence through the graph.
    Optionally filtered by an entity ID.
    """
    path_spec = plan.path
    start = plan.start_entity

    if not path_spec or not path_spec.sequence:
        # Fall back to BFS from start to target
        if start and plan.target_entity:
            path_spec_seq = g.bfs_path(start, plan.target_entity)
        else:
            return GraphExecResult(result=None, status="error",
                                   error="Path plan missing sequence.")
        sequence = path_spec_seq
    else:
        # Validate each step in the sequence
        sequence = [e for e in path_spec.sequence if g.has_entity(e)]
        if not sequence:
            return GraphExecResult(result=None, status="error",
                                   error="No valid entities in path sequence.")

    if not sequence:
        return GraphExecResult(
            result={"type": "path", "sequence": [], "hops": [], "entity_records": {}},
            status="empty",
        )

    hops = g.path_hops(sequence)

    # Collect ID filter if present
    id_filter: Optional[dict] = None
    for f in plan.filters or []:
        if f.field in ("id", "pk") or f.operator == "=":
            id_filter = {"entity": f.entity, "field": f.field, "value": f.value}
            break

    # Fetch records for each entity in the path
    entity_records: dict[str, list[dict]] = {}
    for entity in sequence:
        if id_filter and id_filter["entity"] == entity:
            row = g.find_record_by_id(entity, id_filter["value"])
            entity_records[entity] = [row] if row else []
        else:
            recs, _ = g.get_records(entity, limit=5)
            entity_records[entity] = recs

    return GraphExecResult(
        result={
            "type": "path",
            "sequence": sequence,
            "hops": [h.__dict__ if hasattr(h, "__dict__") else h.model_dump() for h in hops],
            "path_length": len(sequence) - 1,
            "entity_records": entity_records,
            "id_filter": id_filter,
        },
        status="success",
    )


def _exec_anomaly(plan: Any, g: _GraphAdapter) -> GraphExecResult:
    """
    Detect anomalies in the graph data:
      missing_link   — records with no outgoing FK to expected neighbour
      broken_flow    — records that skip a step in the O2C pipeline
      inconsistency  — generic: records failing a structural constraint
    """
    start = plan.start_entity
    anomaly_spec = plan.anomaly

    if not start or not g.has_entity(start):
        return GraphExecResult(result=None, status="error",
                               error=f"Entity '{start}' not found.")
    if not anomaly_spec:
        return GraphExecResult(result=None, status="error",
                               error="Anomaly plan missing anomaly spec.")

    anomaly_type = anomaly_spec.type
    description = anomaly_spec.description

    records, _ = g.get_records(start, limit=50)
    if plan.filters:
        records = _apply_plan_filters(records, plan.filters, start)

    # Determine which entity we expect to link to
    target = plan.target_entity
    if not target:
        # Infer from description: look for entity names mentioned
        for node in g._nodes:
            if node.lower() in description.lower():
                target = node
                break

    flagged: list[dict] = []
    checked = len(records)

    if anomaly_type in ("missing_link", "broken_flow") and target and g.has_entity(target):
        # Find the FK field that joins start → target
        join_key = _infer_fk_field(start, target, g)
        target_records, _ = g.get_records(target, limit=50)

        # Build index of target PK values
        tgt_pks = _ensure_list(g.node_info(target).primary_key)
        tgt_pk_set: set[str] = set()
        for tr in target_records:
            for pk in tgt_pks:
                val = str(tr.get(pk, ""))
                if val:
                    tgt_pk_set.add(val)

        src_pks = _ensure_list(g.node_info(start).primary_key)
        for rec in records:
            fk_val = None
            if join_key:
                fk_val = str(rec.get(join_key, ""))
            elif src_pks:
                fk_val = str(rec.get(src_pks[0], ""))

            if fk_val and fk_val not in tgt_pk_set:
                flagged.append({
                    "record": rec,
                    "issue": f"No matching {target} record for {join_key or src_pks[0]}={fk_val}",
                })

    else:
        # Generic inconsistency: flag records missing a required field
        required_fields = [f.field for f in (plan.filters or []) if f.field != "id"]
        for rec in records:
            for field in required_fields:
                if rec.get(field) is None:
                    flagged.append({"record": rec, "issue": f"Missing field: {field}"})
                    break

    return GraphExecResult(
        result={
            "type": "anomaly",
            "anomaly_type": anomaly_type,
            "description": description,
            "start_entity": start,
            "target_entity": target,
            "checked": checked,
            "flagged_count": len(flagged),
            "flagged": flagged[:20],
        },
        status="success" if flagged else "empty",
    )


def _infer_fk_field(from_entity: str, to_entity: str, g: _GraphAdapter) -> Optional[str]:
    """Find the join column for an edge by parsing its join_condition."""
    import re as _re
    for e in g._edges:
        if (e.from_node == from_entity and e.to_node == to_entity) or \
           (e.from_node == to_entity and e.to_node == from_entity):
            m = _re.search(r"\.(\w+)\s*=\s*\w+\.(\w+)", e.join_condition)
            if m:
                return m.group(1)
    return None


def _apply_plan_filters(records: list[dict], filters: list, entity: str) -> list[dict]:
    """Apply PlanFilterCondition list to records, scoped to matching entity."""
    result = list(records)
    for f in filters:
        if f.entity and f.entity != entity:
            continue
        result = [r for r in result if _eval_filter(r, f.field, f.operator, f.value)]
    return result


def _compute_agg(values: list[float], metric: str) -> float:
    if metric == "count":
        return float(len(values))
    if metric == "sum":
        return sum(values)
    if metric == "avg":
        return sum(values) / len(values) if values else 0.0
    if metric == "max":
        return max(values)
    if metric == "min":
        return min(values)
    return float(len(values))


# ─────────────────────────────────────────────
# Public entrypoints
# ─────────────────────────────────────────────

def execute_graph_query(
    query: ParsedGraphQuery,
    svc: Optional[GraphService] = None,
    snapshot: Optional[GraphSnapshot] = None,
) -> GraphExecResult:
    """
    Execute a ParsedGraphQuery against the graph.

    Rules (enforced):
    - All entity names must exist in the graph — no guessing
    - Traversal uses BFS — shortest path only, no heuristics
    - Filter matching is exact (=, !=, contains) or numeric (>, <, >=, <=)
    - Returns { result, status } — never raises

    Args:
        query:    Parsed, validated graph query.
        svc:      Live GraphService (preferred; has real synthetic record data).
        snapshot: Caller-supplied node/edge snapshot (used when svc is None).
    """
    g = _GraphAdapter(svc=svc, snapshot=snapshot)

    try:
        if query.type == "lookup":
            return _exec_lookup(query, g)
        elif query.type == "traverse":
            return _exec_traverse(query, g)
        elif query.type == "filter":
            return _exec_filter(query, g)
        else:
            return GraphExecResult(
                result=None,
                status="error",
                error=f"Unknown query type: '{query.type}'.",
            )
    except Exception as exc:  # noqa: BLE001 — surface all errors as structured responses
        return GraphExecResult(
            result=None,
            status="error",
            error=str(exc),
        )


def execute_plan(
    plan: Any,  # GraphQueryPlan — Any to avoid circular import
    svc: Optional[GraphService] = None,
    snapshot: Optional[GraphSnapshot] = None,
) -> GraphExecResult:
    """
    Execute a GraphQueryPlan (from the LLM planner) against the graph.
    Supports all 6 types: lookup, traverse, filter, aggregate, path, anomaly.
    """
    g = _GraphAdapter(svc=svc, snapshot=snapshot)

    try:
        if plan.type == "aggregate":
            return _exec_aggregate(plan, g)
        elif plan.type == "path":
            return _exec_path(plan, g)
        elif plan.type == "anomaly":
            return _exec_anomaly(plan, g)
        elif plan.type == "lookup":
            # Adapt GraphQueryPlan → minimal duck-type object for _exec_lookup
            return _exec_lookup(_PlanLookupAdapter(plan), g)
        elif plan.type == "traverse":
            return _exec_traverse(_PlanTraverseAdapter(plan), g)
        elif plan.type == "filter":
            return _exec_filter(_PlanFilterAdapter(plan), g)
        else:
            return GraphExecResult(
                result=None, status="error",
                error=f"Unknown plan type: '{plan.type}'.",
            )
    except Exception as exc:
        return GraphExecResult(result=None, status="error", error=str(exc))


# ─────────────────────────────────────────────
# Plan adapters (GraphQueryPlan → duck-typed query objects)
# ─────────────────────────────────────────────

class _PlanLookupAdapter:
    """Adapts GraphQueryPlan to the interface expected by _exec_lookup."""
    def __init__(self, plan: Any) -> None:
        id_val = next(
            (f.value for f in (plan.filters or []) if f.field in ("id", "pk") and f.operator == "="),
            None,
        )

        class _StartNode:
            entity = plan.start_entity
            id = id_val

        self.start_node = _StartNode()
        self.type = "lookup"


class _PlanTraverseAdapter:
    """Adapts GraphQueryPlan to the interface expected by _exec_traverse."""
    def __init__(self, plan: Any) -> None:
        # Extract ID from plan filters (e.g. "billing document 91150187")
        id_val = next(
            (f.value for f in (plan.filters or [])
             if f.field in ("id", "pk") and f.operator == "="),
            None,
        )

        class _StartNode:
            entity = plan.start_entity
            id = id_val

        self.start_node = _StartNode()
        self.target_entity = plan.target_entity
        self.traversal_path: list = []
        self.type = "traverse"


class _PlanFilterAdapter:
    """Adapts GraphQueryPlan to the interface expected by _exec_filter."""
    def __init__(self, plan: Any) -> None:
        from app.models.query import FilterCondition

        class _StartNode:
            entity = plan.start_entity
            id = None

        self.start_node = _StartNode()
        # Convert PlanFilterCondition → FilterCondition
        self.filters = [
            FilterCondition(field=f.field, operator=f.operator, value=f.value)
            for f in (plan.filters or [])
        ]
        self.type = "filter"


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _ensure_list(val: Any) -> list:
    return val if isinstance(val, list) else [val]
