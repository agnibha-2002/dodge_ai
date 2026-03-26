"""
LLM-based response generator.

Converts a structured graph execution result into a natural-language answer
using Hugging Face Inference API. Strictly grounded — the model is instructed to use ONLY the
data present in the result, never hallucinate, and say "No results found"
when the execution returned empty.

Pipeline position:
  NL query
    → [query_parser]      ParsedGraphQuery       (deterministic)
    → [graph_executor]    GraphExecResult         (deterministic)
    → [response_generator] str                   (LLM, grounded)
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Ensure HUGGINGFACE_API_KEY is available even when this module is used
# outside the FastAPI app bootstrap path.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from app.services.hf_client import hf_chat_completion
from app.services.llm_guardrails import redact_execution_for_llm, sanitize_question

_SYSTEM_PROMPT = """\
You are an intelligent assistant for a graph-based ERP system.

YOUR JOB:
Answer the user's question clearly and directly. The frontend will display \
any supporting data tables separately — you only need to provide the answer \
and context.

MANDATORY RULES:

1. ANSWER FIRST — your very first sentence MUST directly answer the question.
   - Do NOT start with "Found X records" or "Path found" or "Based on the data".
   - Start with the actual answer. Example: "Order ORD-001 is linked to \
delivery DEL-005, which was shipped on 2024-03-15."

2. EXPLAIN RELATIONSHIPS — after the answer, briefly explain how entities \
connect in plain English. Example: "This order generated a delivery, which \
produced an invoice that has been fully paid."

3. HANDLE MULTIPLE RESULTS — if there are many records:
   - Summarize the top results (mention up to 3 specific IDs or values).
   - Explain WHY there are multiple. Example: "There are 12 invoices because \
each delivery can generate separate invoices for different line items."

4. GROUNDED ONLY — use ONLY data from the execution result. Never hallucinate.

5. FORBIDDEN:
   - Do NOT output raw JSON, table formatting, or data dumps.
   - Do NOT use internal terms: TRAVERSE, LOOKUP, FILTER, BFS, hop, node, edge.
   - Do NOT mention confidence levels or query plan details.
   - Do NOT say "Query executed successfully" — answer the question instead.

6. EMPTY RESULTS — say "I couldn't find any matching records for that query." \
then use the Graph context section (if present) to suggest related entities \
in the same cluster the user might explore instead.

9. GRAPH CONTEXT — if a "Graph context" section is present in the input, use \
it to: (a) explain how queried entities relate structurally, (b) mention the \
cluster they belong to when relevant, (c) suggest bridge entities for \
cross-cluster questions.

7. ERRORS — report clearly: "Something went wrong: [brief reason]."

8. LENGTH — keep it concise. Two to four sentences. No filler.

The user sees your text as a chat message. Write naturally, not like a report.
"""

_USER_TEMPLATE = """\
User query:
"{user_query}"

Execution result:
{result_json}
{graph_context_section}"""


def generate_response(
    user_query: str,
    execution_result: dict[str, Any],
    api_key: Optional[str] = None,
    model: str = "meta-llama/Llama-3.1-8B-Instruct",
    graph_context: str = "",
) -> str:
    """
    Call Hugging Face to generate a grounded natural-language answer.

    Args:
        user_query:       The original natural-language question.
        execution_result: The serialised GraphExecResult dict.
        api_key:          Hugging Face API key (falls back to HUGGINGFACE_API_KEY env var).
        model:            Hugging Face model ID.
        graph_context:    Optional cluster/hub context from graph_analytics.  When
                          provided the model can reference cluster membership, suggest
                          related entities for empty results, and explain cross-cluster
                          traversals more naturally.

    Returns:
        A natural-language answer string. Never raises — returns a fallback
        string on any error so the pipeline degrades gracefully.
    """
    user_query = sanitize_question(user_query)
    key = api_key or os.getenv("HUGGINGFACE_API_KEY", "")
    if not key:
        logger.warning("HUGGINGFACE_API_KEY not set — returning deterministic fallback answer")
        return _fallback_answer(execution_result)

    try:
        safe_execution = redact_execution_for_llm(execution_result)
        graph_context_section = (
            f"\nGraph context:\n{graph_context}" if graph_context else ""
        )
        user_message = _USER_TEMPLATE.format(
            user_query=user_query,
            result_json=json.dumps(safe_execution, indent=2, default=str),
            graph_context_section=graph_context_section,
        )

        answer = hf_chat_completion(
            api_key=key,
            model=model,
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_message,
            max_tokens=512,
            temperature=0.2,
            endpoint=os.getenv("HUGGINGFACE_API_URL", "https://router.huggingface.co/v1/chat/completions"),
            provider=os.getenv("HUGGINGFACE_PROVIDER", ""),
        ).strip()

        logger.info("LLM response generated (%d chars)", len(answer))
        return answer

    except Exception as exc:  # noqa: BLE001
        err_name = type(exc).__name__
        err_text = str(exc)
        if "401" in err_text or "403" in err_text:
            logger.error("Hugging Face authentication/permission failed for response generation (%s)", err_text)
        elif "429" in err_text:
            logger.error("Hugging Face rate limit exceeded for response generation (%s)", err_text)
        elif err_name == "ConnectionError":
            logger.error("Hugging Face connection failed for response generation (%s)", err_text)
        else:
            logger.exception("LLM response generation failed: %s", exc)
        return _fallback_answer(execution_result)


# ─────────────────────────────────────────────
# Deterministic fallback (no LLM / API error)
# ─────────────────────────────────────────────

def _fallback_answer(execution_result: dict[str, Any]) -> str:
    """
    Build a plain-text answer purely from the execution result structure.
    Used when the Hugging Face API is unavailable.
    Follows answer-first pattern — never starts with "Found X records".
    """
    status = execution_result.get("status", "error")
    result = execution_result.get("result")

    if status == "error":
        error = execution_result.get("error") or "unknown error"
        return f"Something went wrong: {error}"

    if status == "empty" or not result:
        return "I couldn't find any matching records for that query. Try rephrasing or checking entity names."

    rtype = result.get("type")

    if rtype == "lookup":
        entity = _humanize(result.get("entity", "entity"))
        record_count = result.get("record_count")
        record_id = result.get("id")
        if record_id and result.get("record"):
            # Single record lookup — answer with the specific record
            record = result["record"]
            key_fields = list(record.items())[:3]
            details = ", ".join(f"**{_humanize(k)}**: {v}" for k, v in key_fields)
            return f"Here's the **{entity}** record for **{record_id}**: {details}."
        if record_count is not None:
            connected = result.get("connected_entities", [])
            conn_str = ""
            if connected:
                friendly = [_humanize(c) for c in connected[:3]]
                conn_str = f" Each one connects to {', '.join(friendly)}."
            return f"There are **{record_count:,}** **{entity}** records in the system.{conn_str}"
        return f"Here are the **{entity}** records."

    if rtype == "traverse":
        start = _humanize(result.get("start_entity", ""))
        target = _humanize(result.get("target_entity", ""))
        target_count = result.get("target_record_count")
        target_records = result.get("target_records", [])
        path = result.get("path", [])

        # Build the connection description
        if len(path) > 2:
            middle = [_humanize(p) for p in path[1:-1]]
            via = f" through {', '.join(middle)}"
        else:
            via = ""

        # If we have a small number of target records, summarize key fields
        if target_records and len(target_records) <= 3:
            first = target_records[0]
            key_fields = list(first.items())[:3]
            details = ", ".join(f"**{_humanize(k)}**: {v}" for k, v in key_fields)
            if len(target_records) == 1:
                return f"The linked **{target}** record{via}: {details}."
            return f"There are **{len(target_records)}** linked **{target}** records{via}. The first one: {details}."

        # Many records — give a count-based answer
        if target_count:
            return f"There are **{target_count:,}** **{target.lower()}** records linked to **{start.lower()}**{via}. Here are the details."
        return f"**{start}** is linked to **{target}**{via}."

    if rtype == "filter":
        entity = _humanize(result.get("entity", "entity"))
        record_count = result.get("record_count", 0)
        filters = result.get("filters_applied", [])
        if filters:
            conds = [f"{_humanize(f['field'])} {f['operator']} {f['value']}" for f in filters]
            criteria = " and ".join(conds)
            return f"**{record_count}** **{entity}** record{'s' if record_count != 1 else ''} matched where {criteria}."
        return f"**{record_count}** **{entity}** record{'s' if record_count != 1 else ''} matched your criteria."

    if rtype == "aggregate":
        metric = result.get("metric", "count")
        value = result.get("value")
        field = _humanize(result.get("field", ""))
        entity = _humanize(result.get("entity", ""))
        if value is not None:
            label = f"the {metric}" if metric != "count" else "the total"
            of_what = f" of {field}" if field else f" for {entity}" if entity else ""
            return f"Based on the data, {label}{of_what} is **{value:,.2f}**." if isinstance(value, float) and not value.is_integer() else f"Based on the data, {label}{of_what} is **{int(value):,}**."
        rows = result.get("rows", [])
        if rows:
            top = rows[:3]
            summaries = [f"**{r.get('group') or r.get('entity', '?')}**: {r.get('count', '?')}" for r in top]
            more = f" (and {len(rows) - 3} more)" if len(rows) > 3 else ""
            return f"Here's the breakdown: {', '.join(summaries)}{more}."
        return "Here are the aggregated results."

    if rtype == "path":
        sequence = result.get("sequence", [])
        if sequence:
            flow = " → ".join(_humanize(s) for s in sequence)
            return f"The data flows through: {flow}."
        return "Here's the data flow path."

    if rtype == "anomaly":
        flagged_count = result.get("flagged_count", 0)
        checked = result.get("checked", 0)
        if flagged_count == 0:
            return f"Everything looks good — checked **{checked}** records and found no issues."
        flagged = result.get("flagged", [])
        top_issues = [f.get("issue", "unknown issue") for f in flagged[:2]]
        return f"**{flagged_count}** issue{'s' if flagged_count != 1 else ''} detected out of **{checked}** records checked. For example: {'; '.join(top_issues)}."

    return "Here are your results."


def _humanize(s: str) -> str:
    """Convert snake_case, UPPER_SNAKE, or PascalCase to Title Case.

    Examples:
        BillingDocument   → Billing Document
        accounting_doc_id → Accounting Doc Id
        SALES_ORDER       → Sales Order
        JournalEntry      → Journal Entry
    """
    if not s:
        return ""
    import re
    # Insert space before uppercase letters that follow a lowercase letter or
    # before an uppercase letter followed by a lowercase (handles "HTMLParser" → "HTML Parser")
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s)
    spaced = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", spaced)
    # Replace underscores with spaces
    spaced = spaced.replace("_", " ")
    # Title-case each word
    return spaced.title()
