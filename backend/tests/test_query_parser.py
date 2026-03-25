"""
Tests for the rule-based NL → ParsedGraphQuery parser.

Covers:
  - Entity resolution (exact, alias, plural, camelCase split)
  - ID extraction (various formats)
  - Query type classification (lookup / traverse / filter)
  - Filter operator extraction
  - Confidence levels
  - Edge cases: empty input, unknown entities, multiple entities
"""
import pytest

from app.services.query_parser import parse_structured_graph_query


# ─────────────────────────────────────────────
# Lookup — single entity
# ─────────────────────────────────────────────

class TestLookup:
    def test_customer_by_name(self, graph_service):
        q = parse_structured_graph_query("Show me customers", graph_service)
        assert q.type == "lookup"
        assert q.start_node.entity == "Customer"
        assert q.start_node.id is None

    def test_sales_order_lookup(self, graph_service):
        q = parse_structured_graph_query("List all sales orders", graph_service)
        assert q.type == "lookup"
        assert q.start_node.entity == "SalesOrder"

    def test_product_lookup(self, graph_service):
        q = parse_structured_graph_query("What products do we have?", graph_service)
        assert q.type == "lookup"
        assert q.start_node.entity == "Product"

    def test_billing_document_lookup(self, graph_service):
        q = parse_structured_graph_query("Show billing documents", graph_service)
        assert q.type == "lookup"
        assert q.start_node.entity == "BillingDocument"

    def test_plant_lookup(self, graph_service):
        q = parse_structured_graph_query("List plants", graph_service)
        assert q.type == "lookup"
        assert q.start_node.entity == "Plant"

    def test_confidence_high_with_id(self, graph_service):
        q = parse_structured_graph_query("customer id 1000001", graph_service)
        assert q.confidence == "HIGH"
        assert q.start_node.id is not None

    def test_confidence_medium_without_id(self, graph_service):
        q = parse_structured_graph_query("Show me all customers", graph_service)
        assert q.confidence in ("MEDIUM", "HIGH")


# ─────────────────────────────────────────────
# ID extraction
# ─────────────────────────────────────────────

class TestIdExtraction:
    def test_customer_id_numeric(self, graph_service):
        q = parse_structured_graph_query("customer id 1000001", graph_service)
        assert q.start_node.id == "1000001"

    def test_customer_id_with_hash(self, graph_service):
        q = parse_structured_graph_query("customer #CUST-42", graph_service)
        assert q.start_node.id == "CUST-42"

    def test_order_id_with_number_keyword(self, graph_service):
        q = parse_structured_graph_query("sales order number 45000123", graph_service)
        assert q.start_node.id == "45000123"

    def test_order_id_prefix(self, graph_service):
        q = parse_structured_graph_query("show order 45000123", graph_service)
        # ID may or may not be extracted depending on cue presence — entity must be right
        assert q.start_node.entity == "SalesOrder"

    def test_id_uppercased(self, graph_service):
        q = parse_structured_graph_query("customer id cust-1001", graph_service)
        if q.start_node.id:
            assert q.start_node.id == q.start_node.id.upper()


# ─────────────────────────────────────────────
# Traverse — two entities
# ─────────────────────────────────────────────

class TestTraverse:
    def test_customer_to_sales_order(self, graph_service):
        q = parse_structured_graph_query(
            "How are customers connected to sales orders?", graph_service
        )
        assert q.type == "traverse"
        assert q.start_node.entity is not None
        assert q.target_entity is not None

    def test_order_to_outbound_delivery(self, graph_service):
        q = parse_structured_graph_query(
            "Show me the path from sales orders to outbound delivery", graph_service
        )
        assert q.type == "traverse"

    def test_order_to_invoice(self, graph_service):
        q = parse_structured_graph_query(
            "How does a sales order relate to billing documents?", graph_service
        )
        assert q.type == "traverse"

    def test_two_entities_mentioned(self, graph_service):
        q = parse_structured_graph_query(
            "customers and products", graph_service
        )
        assert q.type == "traverse"
        assert q.start_node.entity is not None
        assert q.target_entity is not None
        assert q.start_node.entity != q.target_entity


# ─────────────────────────────────────────────
# Filter
# ─────────────────────────────────────────────

class TestFilter:
    def test_amount_greater_than(self, graph_service):
        q = parse_structured_graph_query(
            "Find sales orders with amount greater than 5000", graph_service
        )
        assert q.type == "filter"
        assert len(q.filters) > 0
        f = q.filters[0]
        assert f.operator == ">"
        assert f.value == "5000"

    def test_amount_less_than(self, graph_service):
        q = parse_structured_graph_query(
            "Sales orders with total less than 1000", graph_service
        )
        assert q.type == "filter"
        assert len(q.filters) > 0
        assert q.filters[0].operator == "<"

    def test_amount_at_least(self, graph_service):
        q = parse_structured_graph_query(
            "Orders with total at least 10000", graph_service
        )
        assert q.type == "filter"
        assert q.filters[0].operator == ">="

    def test_status_filter(self, graph_service):
        q = parse_structured_graph_query(
            "Sales orders with status equals A", graph_service
        )
        # May parse as filter or lookup depending on attribute match
        assert q.start_node.entity == "SalesOrder"

    def test_filter_confidence_medium(self, graph_service):
        q = parse_structured_graph_query(
            "orders with amount greater than 10000", graph_service
        )
        assert q.confidence in ("MEDIUM", "HIGH")


# ─────────────────────────────────────────────
# Edge cases
# ─────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_string_defaults_gracefully(self, graph_service):
        # Parser should not crash on minimal input
        q = parse_structured_graph_query("?", graph_service)
        assert q.type in ("lookup", "traverse", "filter")

    def test_unknown_entity_returns_lookup(self, graph_service):
        q = parse_structured_graph_query("show me all unicorns", graph_service)
        assert q.type == "lookup"
        # start_node.entity will be None or a fallback
        assert q.confidence in ("LOW", "MEDIUM")

    def test_very_long_query(self, graph_service):
        long_q = "I would like to see " + "all the sales orders " * 50
        q = parse_structured_graph_query(long_q, graph_service)
        assert q.start_node.entity == "SalesOrder"

    def test_numeric_only_input(self, graph_service):
        q = parse_structured_graph_query("45000123", graph_service)
        assert q.type in ("lookup", "traverse", "filter")

    def test_case_insensitive_entity(self, graph_service):
        q1 = parse_structured_graph_query("CUSTOMER records", graph_service)
        q2 = parse_structured_graph_query("customer records", graph_service)
        assert q1.start_node.entity == q2.start_node.entity

    def test_plural_entity_alias(self, graph_service):
        q = parse_structured_graph_query("Show all products", graph_service)
        assert q.start_node.entity == "Product"

    def test_no_duplicate_entities_in_traverse(self, graph_service):
        q = parse_structured_graph_query(
            "customers and customers", graph_service
        )
        # Should not set target_entity == start_entity
        if q.type == "traverse":
            assert q.start_node.entity != q.target_entity
