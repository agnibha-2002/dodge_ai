"""
Guardrails for LLM planner/response calls.

These checks ensure model inputs/outputs stay scoped to ERP graph querying only.
"""
from __future__ import annotations

import copy
import re
from typing import Any

from app.models.query import Confidence

MAX_QUESTION_LEN = 800
MAX_FILTER_VALUE_LEN = 256
MAX_FILTERS = 12
MAX_ROWS_FOR_LLM = 20
MAX_FIELDS_PER_ROW = 20
ALLOWED_OPERATORS = {"=", "!=", "contains", ">", "<", ">=", "<="}

_BLOCKED_PATTERNS = [
    r"\bignore (all|any|previous) instructions\b",
    r"\bsystem prompt\b",
    r"\bdeveloper message\b",
    r"\b(api[_ -]?key|secret|token|password|private key)\b",
    r"\b(os\.environ|process\.env|printenv|cat /etc/passwd)\b",
]


def sanitize_question(question: str) -> str:
    q = " ".join((question or "").split())
    return q[:MAX_QUESTION_LEN]


def is_blocked_question(question: str) -> bool:
    q = (question or "").lower()
    return any(re.search(p, q) for p in _BLOCKED_PATTERNS)


def downgrade_confidence(conf: Confidence) -> Confidence:
    if conf == Confidence.HIGH:
        return Confidence.MEDIUM
    return Confidence.LOW


def sanitize_filter_value(value: Any) -> str:
    return str(value)[:MAX_FILTER_VALUE_LEN]


def sanitize_operator(op: Any) -> str:
    op_str = str(op or "=").strip()
    return op_str if op_str in ALLOWED_OPERATORS else "="


def redact_execution_for_llm(execution_result: dict[str, Any]) -> dict[str, Any]:
    """
    Limit record payload size before sending to LLM.
    Prevents unnecessary exposure of full datasets.
    """
    payload = copy.deepcopy(execution_result)
    result = payload.get("result")
    if not isinstance(result, dict):
        return payload

    def _trim_records(rows: list[dict]) -> list[dict]:
        trimmed = []
        for row in rows[:MAX_ROWS_FOR_LLM]:
            if not isinstance(row, dict):
                continue
            keys = list(row.keys())[:MAX_FIELDS_PER_ROW]
            trimmed.append({k: row.get(k) for k in keys})
        return trimmed

    if isinstance(result.get("records"), list):
        result["records"] = _trim_records(result["records"])
    if isinstance(result.get("target_records"), list):
        result["target_records"] = _trim_records(result["target_records"])
    if isinstance(result.get("flagged"), list):
        result["flagged"] = result["flagged"][:MAX_ROWS_FOR_LLM]
    if isinstance(result.get("entity_records"), dict):
        entity_records = result["entity_records"]
        for entity, rows in list(entity_records.items()):
            if isinstance(rows, list):
                entity_records[entity] = _trim_records(rows)

    return payload
