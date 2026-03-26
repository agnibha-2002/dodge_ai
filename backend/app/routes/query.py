import json

from fastapi import APIRouter, Depends

from app.dependencies import get_graph_service
from app.models.execution import GraphExecRequest, GraphExecResult
from app.models.plan import PlanRequest, PlanResponse
from app.models.query import (
    QueryParseResponse,
    QueryRequest,
    QueryValidationRequest,
    QueryValidationResponse,
)
from app.services.graph_analytics import (
    build_analytics,
    cluster_context_for_entities,
    suggest_related_entities,
)
from app.services.graph_executor import execute_graph_query, execute_plan
from app.services.graph_service import GraphService
from app.services.llm_query_planner import plan_query, plan_query_v1
from app.services.query_parser import parse_structured_graph_query
from app.services.query_validator import validate_structured_query
from app.services.query_logger import log_query_lifecycle
from app.services.response_generator import generate_response


def _graph_context_for_response(plan_entities: list[str], execution_result, svc: GraphService) -> str:
    """
    Build a concise graph-context string to pass to the response generator.
    Includes cluster membership of involved entities and, for empty results,
    suggestions of related entities in the same cluster.
    """
    try:
        analytics = build_analytics(svc)
        parts: list[str] = []

        cluster_ctx = cluster_context_for_entities(plan_entities, analytics)
        if cluster_ctx:
            parts.append(cluster_ctx)

        # For empty results, suggest cluster peers as alternatives
        status = getattr(execution_result, "status", None) or (
            execution_result.get("status") if isinstance(execution_result, dict) else None
        )
        if status == "empty" and plan_entities:
            suggestions = suggest_related_entities(plan_entities[0], analytics)
            if suggestions:
                parts.append(
                    f"Related entities to explore: {', '.join(suggestions[:4])}"
                )

        return "\n".join(parts)
    except Exception:
        return ""

router = APIRouter(tags=["Query"])


@router.post("/query", response_model=QueryParseResponse, summary="Parse natural language query")
def parse_query(
    request: QueryRequest,
    svc: GraphService = Depends(get_graph_service),
):
    """
    Convert natural language into a structured graph query object.
    """
    parsed = parse_structured_graph_query(request.question, svc)
    return QueryParseResponse(
        answer=json.dumps(parsed.model_dump(), indent=2),
        parsed_query=parsed,
    )


@router.post(
    "/query/execute",
    response_model=GraphExecResult,
    summary="Execute a structured graph query (deterministic)",
)
def execute_query(
    request: GraphExecRequest,
    svc: GraphService = Depends(get_graph_service),
):
    """
    Execute a ParsedGraphQuery against the graph using deterministic traversal logic.

    - No LLM involved at this stage.
    - All entity names must be valid graph entities.
    - Traversal uses BFS shortest path.
    - Filters use exact / numeric comparisons only.
    - Returns { result, status } where status is 'success', 'empty', or 'error'.

    Pass an optional `graph` snapshot to run against caller-supplied data instead
    of the live loaded graph.
    """
    snapshot = request.graph  # may be None → executor uses live svc
    return execute_graph_query(query=request.query, svc=svc, snapshot=snapshot)


@router.post(
    "/query/parse-and-execute",
    summary="Parse NL query then execute deterministically",
)
def parse_and_execute(
    request: QueryRequest,
    svc: GraphService = Depends(get_graph_service),
):
    """
    Full pipeline:
      1. Parse natural language → ParsedGraphQuery  (rule-based, no LLM)
      2. Execute the parsed query deterministically  (no LLM)

    Returns a combined object so the frontend can render both the
    parsed intent and the actual graph results in one round-trip.
    """
    parsed = parse_structured_graph_query(request.question, svc)
    execution = execute_graph_query(query=parsed, svc=svc)

    return {
        "parsed_query": parsed.model_dump(),
        "execution": execution.model_dump(),
    }


@router.post(
    "/query/answer",
    summary="Full pipeline: parse → execute → LLM answer",
)
def answer_query(
    request: QueryRequest,
    svc: GraphService = Depends(get_graph_service),
):
    """
    Complete three-stage pipeline:
      1. Parse NL → ParsedGraphQuery          (rule-based, deterministic)
      2. Execute parsed query → GraphExecResult (deterministic graph traversal)
      3. Generate natural-language answer       (LLM, strictly grounded in result)

    Returns:
      {
        "answer":       str,               — LLM-generated natural language response
        "parsed_query": ParsedGraphQuery,  — what the parser understood
        "execution":    GraphExecResult,   — raw deterministic execution output
      }

    Falls back to a deterministic answer if HUGGINGFACE_API_KEY is not set.
    """
    parsed = parse_structured_graph_query(request.question, svc)
    execution = execute_graph_query(query=parsed, svc=svc)

    answer_entities = [e for e in [parsed.start_node.entity, parsed.target_entity] if e]
    graph_context = _graph_context_for_response(answer_entities, execution, svc)

    answer = generate_response(
        user_query=request.question,
        execution_result=execution.model_dump(),
        graph_context=graph_context,
    )

    log_query_lifecycle(
        query=request.question,
        plan=parsed,
        execution_result=execution.model_dump(),
        answer=answer,
        planner="fallback",
    )
    return {
        "answer": answer,
        "parsed_query": parsed.model_dump(),
        "execution": execution.model_dump(),
    }


@router.post(
    "/query/plan",
    response_model=PlanResponse,
    summary="LLM query planner: NL → plan → execute → answer",
)
def plan_and_execute(
    request: PlanRequest,
    svc: GraphService = Depends(get_graph_service),
):
    """
    Full LLM-powered pipeline:
      1. Build schema context (entities, relationships, attributes)
      2. Call OpenAI → GraphQueryPlan (6 types: lookup, traverse, filter,
                                       aggregate, path, anomaly)
      3. Execute the plan deterministically on the graph
      4. Generate a grounded natural-language answer

    Falls back to the rule-based parser if no API key is configured.
    """
    plan = plan_query_v1(request.question, svc)
    execution = execute_plan(plan=plan, svc=svc)

    # Build cluster/hub context from the entities involved in this plan
    plan_entities = [e for e in [plan.start_entity, plan.target_entity] if e]
    if plan.type == "path" and plan.path and plan.path.sequence:
        plan_entities = list(plan.path.sequence)
    graph_context = _graph_context_for_response(plan_entities, execution, svc)

    answer = generate_response(
        user_query=request.question,
        execution_result=execution.model_dump(),
        graph_context=graph_context,
    )
    log_query_lifecycle(
        query=request.question,
        plan=plan,
        execution_result=execution.model_dump(),
        answer=answer,
        planner="v1",
    )
    return PlanResponse(
        plan=plan,
        execution=execution.model_dump(),
        answer=answer,
    )


@router.post("/query/validate", response_model=QueryValidationResponse, summary="Validate parsed graph query")
def validate_query(
    request: QueryValidationRequest,
    svc: GraphService = Depends(get_graph_service),
):
    """
    Strictly validate parser output for correctness, safety, and schema alignment.
    """
    return validate_structured_query(
        user_query=request.question,
        structured_query=request.structured_query,
        svc=svc,
    )
