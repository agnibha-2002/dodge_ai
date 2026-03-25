# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Project Overview

**ContextGraph AI** — a graph-based ERP query system that:
1. Ingests fragmented tabular ERP data (CSV/JSON)
2. Constructs a connected entity graph
3. Serves a React UI for graph exploration
4. Accepts natural language queries, translates them to SQL via Claude, and returns grounded responses

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend API | Python 3.11+, FastAPI |
| Database | PostgreSQL (primary), NetworkX (in-memory graph) |
| LLM | Anthropic Claude API (`claude-sonnet-4-6`) |
| Frontend | React + TypeScript, Cytoscape.js (graph viz) |
| ORM | SQLAlchemy (async) |
| Testing | pytest (backend), Vitest (frontend) |
| Package mgr | `uv` (backend), `npm` (frontend) |

---

## Project Structure

```
dodge_ai/
├── backend/
│   ├── main.py              # FastAPI app entrypoint
│   ├── api/                 # Route handlers (graph, query, ingest)
│   ├── ingestion/           # CSV/JSON loading, normalization, dedup
│   ├── graph/               # Graph construction (nodes/edges), NetworkX logic
│   ├── llm/                 # Claude API client, prompt templates, guardrails
│   ├── query/               # NL→SQL translation, query validation, execution
│   ├── models/              # SQLAlchemy ORM models
│   ├── db.py                # DB session, connection pool
│   └── config.py            # Settings (env vars via pydantic-settings)
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── Graph/       # Cytoscape.js graph panel
│   │   │   └── Chat/        # NL query input + response display
│   │   ├── api/             # Typed API client (fetch wrappers)
│   │   └── App.tsx
│   └── package.json
├── data/                    # Sample ERP CSVs (orders, deliveries, invoices, etc.)
├── tests/
│   ├── backend/
│   └── frontend/
└── docker-compose.yml       # PostgreSQL + backend + frontend
```

---

## Development Commands

### Backend

```bash
# Install dependencies
cd backend && uv sync

# Run dev server (hot reload)
uv run uvicorn main:app --reload --port 8000

# Run all tests
uv run pytest

# Run a single test file
uv run pytest tests/backend/test_query.py

# Run a single test by name
uv run pytest tests/backend/test_query.py::test_nl_to_sql_basic -v

# DB migrations (Alembic)
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "description"
```

### Frontend

```bash
cd frontend && npm install

# Dev server
npm run dev

# Build
npm run build

# Tests
npm run test

# Run a single test file
npx vitest run src/components/Chat/Chat.test.tsx
```

### Full stack

```bash
# Start PostgreSQL + backend + frontend together
docker-compose up
```

---

## Architecture: Key Data Flows

### 1. Data Ingestion → Graph Construction
- Raw CSVs loaded in `ingestion/` → normalized into ORM models → persisted to PostgreSQL
- `graph/` layer reads from DB and builds a `networkx.DiGraph` with entity nodes (Orders, Deliveries, Invoices, Payments, Customers, Products) and typed edges
- Graph is serialized to JSON for the frontend via `GET /api/graph`

### 2. Natural Language Query Flow
```
User input → POST /api/query
  → llm/guardrails.py: check if in-scope (ERP domain only)
  → llm/translator.py: schema-aware prompt → Claude → SQL string
  → query/validator.py: validate SQL (no destructive ops, restricted to read-only)
  → query/executor.py: execute against PostgreSQL
  → llm/responder.py: structured results → Claude → natural language summary
  → response returned to frontend
```

### 3. Guardrails
- `llm/guardrails.py` runs a fast classification prompt before translation
- Rejects queries outside ERP domain with a fixed message
- Never passes out-of-scope content to the SQL translator

---

## LLM Integration Patterns

- All Claude calls go through `llm/client.py` — never call the Anthropic SDK directly from other modules
- Prompts are stored as string templates in `llm/prompts/` (not hardcoded inline)
- Schema context (table names, column names, FK relationships) is injected into every NL→SQL prompt
- Claude model: `claude-sonnet-4-6` by default; configurable via `CLAUDE_MODEL` env var
- All LLM inputs/outputs are logged for observability

---

## Database Schema (Entity Relationships)

Core tables and their graph edges:
- `customers` → `orders` (Customer → Order)
- `orders` → `order_items` → `products` (Order → Product)
- `orders` → `deliveries` (Order → Delivery)
- `deliveries` → `invoices` (Delivery → Invoice)
- `invoices` → `payments` (Invoice → Payment)

All FK columns are indexed. Queries use joins across these tables.

---

## Environment Variables

Set in `.env` (never committed):

```
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/contextgraph
ANTHROPIC_API_KEY=sk-...
CLAUDE_MODEL=claude-sonnet-4-6
```

---

## Security Rules

- LLM-generated SQL is validated before execution: only `SELECT` statements allowed, no dynamic table/column names from user input passed unsanitized
- DB connection uses a read-only PostgreSQL role for query execution
- Never expose raw SQL errors to the frontend — log internally, return sanitized messages
