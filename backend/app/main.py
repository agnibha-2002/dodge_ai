"""
ContextGraph AI — Graph Service Layer
FastAPI application entry point.
"""
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.dependencies import init_service
from app.services.loader import load_graph
from app.services.graph_service import GraphService
from app.routes import nodes, edges, expand, search, graph, records, record_graph, query

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Lifespan: load graph once at startup
# ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    graph_path = os.getenv("GRAPH_PATH")  # optional override via env var
    raw_graph = load_graph(graph_path)

    # Load normalized schema for sample record generation
    schema_path = Path(__file__).resolve().parents[2] / "data" / "normalized_schema.json"
    schema_data = None
    if schema_path.exists():
        import json
        schema_data = json.loads(schema_path.read_text(encoding="utf-8"))
        logger.info("Loaded normalized schema from %s", schema_path)

    svc = GraphService(raw_graph, schema=schema_data)
    init_service(svc)
    stats = svc.get_graph_stats()
    logger.info(
        "Graph ready — nodes=%d, edges=%d (structural=%d, filtered=%d)",
        stats["nodes"], stats["edges"],
        stats["structural_edges"], stats["filtered_edges"],
    )

    # Validate record graph is buildable at startup
    try:
        rg = svc.get_record_graph(records_per_entity=2)
        logger.info(
            "Record graph OK — %d record nodes, %d edges, %d entity colors",
            len(rg.nodes), len(rg.edges), len(rg.entity_colors),
        )
    except Exception:
        logger.exception("Record graph build FAILED at startup")

    yield
    logger.info("Shutting down Graph Service")


# ─────────────────────────────────────────────
# App
# ─────────────────────────────────────────────

app = FastAPI(
    title="ContextGraph AI — Graph Service",
    description=(
        "Backend API for exploring the SAP Order-to-Cash graph. "
        "Serves nodes, edges, and neighbourhood expansions for the visualization UI."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS — allow the React UI (default Vite port) and any localhost
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────
# Global exception handler
# ─────────────────────────────────────────────

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "type": type(exc).__name__},
    )


# ─────────────────────────────────────────────
# Routers
# ─────────────────────────────────────────────

app.include_router(nodes.router)
app.include_router(edges.router)
app.include_router(expand.router)
app.include_router(search.router)
app.include_router(graph.router)
app.include_router(records.router)
app.include_router(record_graph.router)
app.include_router(query.router)


# ─────────────────────────────────────────────
# Health check
# ─────────────────────────────────────────────

@app.get("/health", tags=["Health"], summary="Health check")
def health():
    return {"status": "ok"}


@app.get("/", tags=["Health"], include_in_schema=False)
def root():
    return {
        "service": "ContextGraph AI — Graph Service Layer",
        "docs": "/docs",
        "health": "/health",
    }
