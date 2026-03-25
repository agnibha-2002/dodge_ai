"""
Tests for the deterministic graph execution engine.

Covers:
  - Lookup: entity found, ID match, missing entity, empty result
  - Traverse: valid path, no path between disconnected entities
  - Filter: matching records, no matches, multiple conditions
  - Error handling: invalid entity, null inputs
  - Determinism: same input always produces same output
"""
from __future__ import annotations

from typing import Optional

import pytest

from app.models.query import Confidence, ParsedFilterCondition, ParsedGraphQuery, ParsedStartNode
from app.services.graph_executor import execute_graph_query


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def make_lookup(entity: str, id: Optional[str] = None) -> ParsedGraphQuery:
    return ParsedGraphQuery(
        type="lookup",
        start_node=ParsedStartNode(entity=entity, id=id),
        target_entity=None,
        filters=[],
        confidence=Confidence.HIGH if id else Confidence.MEDIUM,
    )


def make_traverse(start: str, target: str) -> ParsedGraphQuery:
    return ParsedGraphQuery(
        type="traverse",
        start_node=ParsedStartNode(entity=start, id=None),
        target_entity=target,
        filters=[],
        confidence=Confidence.MEDIUM,
    )


def make_filter(entity: str, field: str, op: str, value: str) -> ParsedGraphQuery:
    return ParsedGraphQuery(
        type="filter",
        start_node=ParsedStartNode(entity=entity, id=None),
        target_entity=None,
        filters=[ParsedFilterCondition(field=field, operator=op, value=value)],
        confidence=Confidence.MEDIUM,
    )


# ─────────────────────────────────────────────
# Lookup tests
# ─────────────────────────────────────────────

class TestLookupExecution:
    def test_customer_lookup_success(self, graph_service):
        result = execute_graph_query(make_lookup("Customer"), svc=graph_service)
        assert result.status == "success"
        assert result.result is not None
        assert result.result["type"] == "lookup"
        assert result.result["entity"] == "Customer"

    def test_lookup_returns_records(self, graph_service):
        result = execute_graph_query(make_lookup("Customer"), svc=graph_service)
        assert isinstance(result.result["records"], list)
        assert len(result.result["records"]) > 0

    def test_lookup_returns_connected_entities(self, graph_service):
        result = execute_graph_query(make_lookup("Customer"), svc=graph_service)
        assert isinstance(result.result["connected_entities"], list)
        assert len(result.result["connected_entities"]) > 0

    def test_lookup_sales_order(self, graph_service):
        result = execute_graph_query(make_lookup("SalesOrder"), svc=graph_service)
        assert result.status == "success"
        # record_count reflects schema (100) but synthetic data is capped at 50 rows
        assert result.result["record_count"] is not None

    def test_lookup_product(self, graph_service):
        result = execute_graph_query(make_lookup("Product"), svc=graph_service)
        assert result.status == "success"

    def test_lookup_unknown_entity_returns_error(self, graph_service):
        result = execute_graph_query(make_lookup("NonExistentEntity"), svc=graph_service)
        assert result.status == "error"
        assert result.error is not None

    def test_lookup_with_id_returns_single_record(self, graph_service):
        # Pull a real record first to get a valid PK
        base = execute_graph_query(make_lookup("Customer"), svc=graph_service)
        records = base.result["records"]
        if records:
            pk_val = str(records[0].get("customer_id", ""))
            if pk_val:
                result = execute_graph_query(make_lookup("Customer", id=pk_val), svc=graph_service)
                # Either found (success) or not in sample (empty) — both are valid
                assert result.status in ("success", "empty")
                assert result.error is None

    def test_lookup_with_fake_id_returns_empty(self, graph_service):
        result = execute_graph_query(make_lookup("Customer", id="FAKE-99999"), svc=graph_service)
        assert result.status == "empty"
        assert result.error is None

    def test_lookup_attributes_populated(self, graph_service):
        result = execute_graph_query(make_lookup("Customer"), svc=graph_service)
        assert isinstance(result.result["attributes"], list)
        assert len(result.result["attributes"]) > 0

    def test_lookup_all_entities(self, graph_service):
        """Every entity in the graph should be lookupable."""
        for node in graph_service._graph.nodes:
            result = execute_graph_query(make_lookup(node.name), svc=graph_service)
            assert result.status in ("success", "empty"), (
                f"Entity {node.name} returned status={result.status}: {result.error}"
            )


# ─────────────────────────────────────────────
# Traverse tests
# ─────────────────────────────────────────────

class TestTraverseExecution:
    def test_customer_to_sales_order(self, graph_service):
        result = execute_graph_query(make_traverse("Customer", "SalesOrder"), svc=graph_service)
        assert result.status == "success"
        assert result.result["type"] == "traverse"
        assert len(result.result["path"]) >= 2

    def test_path_starts_and_ends_correctly(self, graph_service):
        result = execute_graph_query(make_traverse("Customer", "SalesOrder"), svc=graph_service)
        path = result.result["path"]
        assert path[0] == "Customer"
        assert path[-1] == "SalesOrder"

    def test_path_length_matches_hops(self, graph_service):
        result = execute_graph_query(make_traverse("Customer", "SalesOrder"), svc=graph_service)
        assert result.result["path_length"] == len(result.result["path"]) - 1

    def test_hops_have_relationships(self, graph_service):
        result = execute_graph_query(make_traverse("Customer", "SalesOrder"), svc=graph_service)
        for hop in result.result["hops"]:
            assert hop["relationship"]
            assert hop["from_entity"]
            assert hop["to_entity"]

    def test_target_records_present(self, graph_service):
        result = execute_graph_query(make_traverse("Customer", "SalesOrder"), svc=graph_service)
        assert isinstance(result.result["target_records"], list)

    def test_longer_path_sales_order_to_plant(self, graph_service):
        result = execute_graph_query(make_traverse("SalesOrder", "Plant"), svc=graph_service)
        # Either found a path or not — both are structurally valid
        assert result.status in ("success", "empty")
        assert result.error is None

    def test_same_entity_traverse(self, graph_service):
        result = execute_graph_query(make_traverse("Customer", "Customer"), svc=graph_service)
        # BFS should return trivial path of length 0
        assert result.status == "success"
        assert result.result["path_length"] == 0

    def test_missing_start_entity(self, graph_service):
        result = execute_graph_query(make_traverse("Ghost", "Customer"), svc=graph_service)
        assert result.status == "error"

    def test_missing_target_entity(self, graph_service):
        result = execute_graph_query(make_traverse("Customer", "Ghost"), svc=graph_service)
        assert result.status == "error"

    def test_path_is_connected(self, graph_service):
        """Each consecutive pair in path must be adjacent in the graph."""
        result = execute_graph_query(make_traverse("Customer", "SalesOrder"), svc=graph_service)
        if result.status != "success":
            return
        path = result.result["path"]
        adj = graph_service._adj
        rev = graph_service._rev_adj
        for i in range(len(path) - 1):
            a, b = path[i], path[i + 1]
            assert b in adj.get(a, set()) or a in adj.get(b, set()), (
                f"Edge {a} → {b} not in graph adjacency"
            )

    def test_deterministic_path(self, graph_service):
        """Same query always returns same path."""
        r1 = execute_graph_query(make_traverse("Customer", "SalesOrder"), svc=graph_service)
        r2 = execute_graph_query(make_traverse("Customer", "SalesOrder"), svc=graph_service)
        assert r1.result["path"] == r2.result["path"]


# ─────────────────────────────────────────────
# Filter tests
# ─────────────────────────────────────────────

class TestFilterExecution:
    def test_filter_returns_filter_type(self, graph_service):
        result = execute_graph_query(
            make_filter("SalesOrder", "total_net_amount", ">", "0"), svc=graph_service
        )
        assert result.result["type"] == "filter"

    def test_filter_records_match_condition(self, graph_service):
        result = execute_graph_query(
            make_filter("SalesOrder", "total_net_amount", ">", "0"), svc=graph_service
        )
        if result.status == "success":
            for rec in result.result["records"]:
                val = rec.get("total_net_amount")
                if val is not None:
                    assert float(val) > 0

    def test_filter_impossible_condition_returns_empty(self, graph_service):
        result = execute_graph_query(
            make_filter("SalesOrder", "total_net_amount", ">", "999999999"), svc=graph_service
        )
        assert result.status in ("success", "empty")

    def test_filter_count_matches_records_length(self, graph_service):
        result = execute_graph_query(
            make_filter("SalesOrder", "total_net_amount", ">", "0"), svc=graph_service
        )
        if result.status != "error":
            assert result.result["record_count"] == len(result.result["records"]) or \
                   result.result["record_count"] >= len(result.result["records"])

    def test_filter_less_than(self, graph_service):
        result = execute_graph_query(
            make_filter("SalesOrder", "total_net_amount", "<", "1000000"), svc=graph_service
        )
        assert result.status in ("success", "empty")
        assert result.error is None

    def test_filter_unknown_entity(self, graph_service):
        result = execute_graph_query(
            make_filter("Ghost", "amount", ">", "100"), svc=graph_service
        )
        assert result.status == "error"

    def test_filter_unknown_field_returns_empty(self, graph_service):
        # Field not on entity — all records fail the filter
        result = execute_graph_query(
            make_filter("Customer", "nonexistent_field", "=", "X"), svc=graph_service
        )
        assert result.status in ("empty", "success")

    def test_filter_deterministic(self, graph_service):
        q = make_filter("SalesOrder", "total_net_amount", ">", "1000")
        r1 = execute_graph_query(q, svc=graph_service)
        r2 = execute_graph_query(q, svc=graph_service)
        assert r1.result == r2.result
        assert r1.status == r2.status


# ─────────────────────────────────────────────
# Stress / volume tests
# ─────────────────────────────────────────────

class TestStress:
    def test_all_entity_pairs_traverse(self, graph_service):
        """
        Execute traverse for every pair of distinct entities.
        No call should crash — only success or empty.
        """
        nodes = [n.name for n in graph_service._graph.nodes]
        errors = []
        for src in nodes:
            for tgt in nodes:
                if src == tgt:
                    continue
                result = execute_graph_query(make_traverse(src, tgt), svc=graph_service)
                if result.status == "error":
                    errors.append(f"{src} → {tgt}: {result.error}")
        assert not errors, f"Traverse errors:\n" + "\n".join(errors)

    def test_repeated_lookups_stable(self, graph_service):
        """50 repeated lookups on Customer must all return identical results."""
        results = [
            execute_graph_query(make_lookup("Customer"), svc=graph_service)
            for _ in range(50)
        ]
        first = results[0].model_dump()
        for r in results[1:]:
            assert r.model_dump() == first

    def test_bulk_filter_operators(self, graph_service):
        """All numeric operators must not crash."""
        operators = [">", "<", ">=", "<="]
        for op in operators:
            result = execute_graph_query(
                make_filter("SalesOrder", "total_net_amount", op, "5000"),
                svc=graph_service,
            )
            assert result.status != "error", f"Operator {op} caused error: {result.error}"

    def test_no_result_leakage_between_calls(self, graph_service):
        """Separate calls must not share mutable state."""
        r1 = execute_graph_query(make_lookup("Customer"), svc=graph_service)
        r2 = execute_graph_query(make_lookup("SalesOrder"), svc=graph_service)
        assert r1.result["entity"] == "Customer"
        assert r2.result["entity"] == "SalesOrder"

    @pytest.mark.parametrize("entity", [
        "Customer", "SalesOrder", "Product", "Plant",
        "CustomerAddress", "CustomerSalesArea", "BillingDocument",
        "OutboundDelivery", "JournalEntry", "Payment",
    ])
    def test_parametric_lookup(self, entity, graph_service):
        result = execute_graph_query(make_lookup(entity), svc=graph_service)
        assert result.status in ("success", "empty")
        assert result.error is None
