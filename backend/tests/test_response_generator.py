"""
Tests for the LLM response generator (grounding, fallback, edge cases).

The LLM call is mocked so tests run without an API key and stay fast.
One integration test fires a real call if HUGGINGFACE_API_KEY is set.
"""
import os
from unittest.mock import MagicMock, patch

import pytest

from app.services.response_generator import _fallback_answer, generate_response


# ─────────────────────────────────────────────
# Deterministic fallback (no API key needed)
# ─────────────────────────────────────────────

class TestFallbackAnswer:
    def test_empty_status_returns_no_results(self):
        answer = _fallback_answer({"status": "empty", "result": None})
        assert "couldn't find any matching records" in answer.lower()

    def test_error_status_returns_error_message(self):
        answer = _fallback_answer({"status": "error", "result": None, "error": "Entity not found"})
        assert "Entity not found" in answer

    def test_error_without_message_returns_generic(self):
        answer = _fallback_answer({"status": "error", "result": None})
        assert answer  # not empty

    def test_lookup_with_count(self):
        result = {
            "status": "success",
            "result": {
                "type": "lookup",
                "entity": "Customer",
                "id": None,
                "record": None,
                "records": [],
                "record_count": 8,
                "attributes": [],
                "connected_entities": ["SalesOrder", "CustomerAddress"],
            },
        }
        answer = _fallback_answer(result)
        assert "Customer" in answer
        assert "8" in answer

    def test_lookup_with_id_match(self):
        result = {
            "status": "success",
            "result": {
                "type": "lookup",
                "entity": "Customer",
                "id": "CUST-1",
                "record": {"customer_id": "CUST-1", "customer_name": "Acme"},
                "records": [],
                "record_count": 1,
                "attributes": [],
                "connected_entities": [],
            },
        }
        answer = _fallback_answer(result)
        assert "Customer" in answer
        assert "CUST-1" in answer

    def test_traverse_with_path(self):
        result = {
            "status": "success",
            "result": {
                "type": "traverse",
                "start_entity": "Customer",
                "target_entity": "SalesOrder",
                "path": ["Customer", "SalesOrder"],
                "hops": [{"from_entity": "Customer", "to_entity": "SalesOrder", "relationship": "HAS_ORDER"}],
                "path_length": 1,
                "target_records": [],
                "target_record_count": 100,
            },
        }
        answer = _fallback_answer(result)
        assert "customer" in answer.lower()
        assert "sales order" in answer.lower()
        assert "1" in answer  # hop count

    def test_traverse_empty_path(self):
        result = {
            "status": "empty",
            "result": {
                "type": "traverse",
                "start_entity": "Customer",
                "target_entity": "Ghost",
                "path": [],
                "hops": [],
                "path_length": 0,
                "target_records": [],
            },
        }
        answer = _fallback_answer(result)
        assert answer  # not empty string

    def test_filter_with_matches(self):
        result = {
            "status": "success",
            "result": {
                "type": "filter",
                "entity": "SalesOrder",
                "filters_applied": [{"field": "total_net_amount", "operator": ">", "value": "5000"}],
                "records": [],
                "record_count": 12,
            },
        }
        answer = _fallback_answer(result)
        assert "12" in answer
        assert "sales order" in answer.lower()

    def test_filter_no_matches(self):
        result = {
            "status": "empty",
            "result": {
                "type": "filter",
                "entity": "SalesOrder",
                "filters_applied": [],
                "records": [],
                "record_count": 0,
            },
        }
        answer = _fallback_answer(result)
        assert answer

    def test_unknown_type_returns_generic(self):
        answer = _fallback_answer({"status": "success", "result": {"type": "magic"}})
        assert answer


# ─────────────────────────────────────────────
# generate_response — mocked LLM
# ─────────────────────────────────────────────

class TestGenerateResponseMocked:
    def _exec_result(self):
        return {
            "status": "success",
            "result": {
                "type": "lookup",
                "entity": "Customer",
                "id": None,
                "record": None,
                "records": [{"customer_id": "0000000001", "customer_name": "Acme Corp"}],
                "record_count": 8,
                "attributes": ["customer_name", "is_blocked"],
                "connected_entities": ["SalesOrder"],
            },
        }

    def test_uses_llm_when_key_present(self):
        with patch(
            "app.services.response_generator.hf_chat_completion",
            return_value="There are 8 Customer records in the system.",
        ):
            answer = generate_response(
                user_query="Show customers",
                execution_result=self._exec_result(),
                api_key="sk-fake-key",
            )

        assert answer == "There are 8 Customer records in the system."

    def test_falls_back_when_no_key(self):
        with patch.dict(os.environ, {}, clear=True):
            # Ensure key not in env
            os.environ.pop("HUGGINGFACE_API_KEY", None)
            answer = generate_response(
                user_query="Show customers",
                execution_result=self._exec_result(),
                api_key=None,
            )
        assert "Customer" in answer
        assert answer  # non-empty

    def test_falls_back_on_api_exception(self):
        with patch(
            "app.services.response_generator.hf_chat_completion",
            side_effect=Exception("network timeout"),
        ):
            answer = generate_response(
                user_query="Show customers",
                execution_result=self._exec_result(),
                api_key="sk-fake-key",
            )

        # Should return fallback, not raise
        assert answer
        assert "Customer" in answer

    def test_prompt_includes_user_query(self):
        """Verify the user query is injected into the message sent to the LLM."""
        with patch(
            "app.services.response_generator.hf_chat_completion",
            return_value="Found it.",
        ) as mock_hf:
            generate_response(
                user_query="MY UNIQUE QUERY STRING",
                execution_result=self._exec_result(),
                api_key="sk-fake-key",
            )

        call_kwargs = mock_hf.call_args
        user_content = call_kwargs.kwargs.get("user_prompt") or call_kwargs[1].get("user_prompt")
        assert "MY UNIQUE QUERY STRING" in user_content

    def test_prompt_includes_execution_result(self):
        """The execution result JSON must be in the message content."""
        exec_result = self._exec_result()

        with patch(
            "app.services.response_generator.hf_chat_completion",
            return_value="ok",
        ) as mock_hf:
            generate_response(
                user_query="show customers",
                execution_result=exec_result,
                api_key="sk-fake-key",
            )

        call_kwargs = mock_hf.call_args
        user_content = call_kwargs.kwargs.get("user_prompt") or call_kwargs[1].get("user_prompt")
        assert "Customer" in user_content

    def test_uses_configured_model(self):
        with patch(
            "app.services.response_generator.hf_chat_completion",
            return_value="ok",
        ) as mock_hf:
            generate_response(
                user_query="q",
                execution_result=self._exec_result(),
                api_key="sk-fake",
                model="Qwen/Qwen2.5-7B-Instruct",
            )

        call_kwargs = mock_hf.call_args
        model_used = call_kwargs.kwargs.get("model") or call_kwargs[1].get("model")
        assert model_used == "Qwen/Qwen2.5-7B-Instruct"

    def test_response_is_stripped(self):
        with patch(
            "app.services.response_generator.hf_chat_completion",
            return_value="  Found 8 customers.  \n",
        ):
            answer = generate_response("q", self._exec_result(), api_key="sk-fake")

        assert answer == "Found 8 customers."


# ─────────────────────────────────────────────
# Live integration test (skipped without API key)
# ─────────────────────────────────────────────

@pytest.mark.skipif(
    not os.getenv("HUGGINGFACE_API_KEY"),
    reason="HUGGINGFACE_API_KEY not set — skipping live LLM test",
)
class TestGenerateResponseLive:
    def test_live_customer_lookup(self):
        result = {
            "status": "success",
            "result": {
                "type": "lookup",
                "entity": "Customer",
                "id": None,
                "record": None,
                "records": [{"customer_id": "0000000001", "customer_name": "Acme Corp"}],
                "record_count": 8,
                "attributes": ["customer_name", "is_blocked"],
                "connected_entities": ["SalesOrder", "CustomerAddress"],
            },
        }
        answer = generate_response("Show me customers", result)
        assert isinstance(answer, str)
        assert len(answer) > 10
        # Must mention Customer or customer
        assert "customer" in answer.lower() or "Customer" in answer

    def test_live_no_results_case(self):
        result = {"status": "empty", "result": None}
        answer = generate_response("find unicorns", result)
        assert isinstance(answer, str)
        # Model should say no results — grounded behaviour
        assert len(answer) > 0
