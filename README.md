# ContextGraph AI: Graph-Based Data Modeling and Query System

## 1. Project Overview
ContextGraph AI solves a common ERP problem: business data is fragmented across multiple entities (orders, deliveries, invoices, payments, customers, products), so answering cross-entity questions is slow and error-prone.

This system models business objects as a graph, adds a natural-language chat interface, and executes queries deterministically.  
What makes it different is the combination of:
- graph-based relationship modeling,
- LLM-assisted query planning,
- deterministic execution for correctness,
- and UI evidence (records shown with each answer).

## 2. System Architecture
High-level components:
- **Data Layer**: ERP-style structured data + normalized schema
- **Graph Layer**: nodes/edges and relationship metadata
- **Backend API (FastAPI)**: planning, execution, graph endpoints
- **LLM Layer**: query planning + response phrasing
- **Execution Engine**: deterministic traversal/filter/aggregate/anomaly logic
- **Frontend (React)**: graph visualization + chat + records

Data flow:
1. User asks a question.
2. Backend sends schema-aware prompt to LLM planner.
3. LLM returns a structured query plan.
4. Guardrails validate/sanitize the plan.
5. Deterministic engine executes plan on graph/data.
6. Result is converted to grounded response.
7. UI shows answer + supporting records.

Text-based diagram:
`User -> Chat UI -> /query/plan -> LLM Planner -> Guardrails -> Deterministic Executor -> Result -> Response Generator -> UI`

## 3. Architecture Decisions
### Why graph model vs relational-only
- Order-to-cash is relationship-heavy and multi-hop by nature.
- Graph traversal expresses business flow directly (Order -> Delivery -> Invoice -> Payment).

### Why separate LLM planning from execution
- LLM is good at intent parsing, not guaranteed correctness.
- Execution must be deterministic for reproducibility, testability, and trust.

### Why deterministic query generation/execution
- Same input should produce same output.
- Prevents silent LLM drift and hallucinated data operations.

### Why UI shows only filtered/relevant results
- Avoids answer/data mismatch.
- Improves explainability and reviewer confidence.

## 4. Database / Storage Choice
Current implementation uses:
- **in-memory graph service** for relationships and traversal behavior,
- **structured data-backed records** via graph service adapters,
- deployment path that supports backend + frontend on Vercel.

Why this choice:
- fast iteration and low setup complexity,
- easy to reason about and test,
- suitable for small/medium datasets and demos.

Tradeoffs:
- **Pros**: simple, developer-friendly, deterministic behavior.
- **Cons**: limited horizontal scalability and memory headroom for very large graphs.

## 5. Graph Modeling
Nodes represent business entities, e.g.:
- `Customer`, `SalesOrder`, `OutboundDelivery`, `BillingDocument`, `JournalEntry`, `Payment`, `Product`.

Edges represent relationships, e.g.:
- `Customer -> SalesOrder`
- `SalesOrder -> OutboundDelivery`
- `OutboundDelivery -> BillingDocument`
- `BillingDocument -> JournalEntry`

Relationships are defined using schema metadata:
- entity names,
- primary keys,
- attributes,
- join/relationship definitions.

ID handling:
- plans support explicit ID extraction from user queries,
- IDs are enforced as filters for scoped queries (e.g. a specific billing document),
- composite key situations are handled through entity + field-aware filtering logic.

## 6. LLM Integration & Prompting Strategy
LLM is used for:
1. **Query planning** (NL -> structured JSON plan)
2. **Response formatting** (grounded natural language from deterministic result)

LLM is **not** used for query execution.

Prompting strategy:
- schema injection (entities, relationships, attributes),
- strict JSON output contract,
- explicit constraints ("do not hallucinate entities/fields"),
- structured plan types (`lookup`, `traverse`, `filter`, `aggregate`, `path`, `anomaly`).

Correctness controls:
- planner output is validated and sanitized before execution,
- fallback deterministic parser is used if LLM output is invalid.

## 7. Query Execution Engine
Execution is deterministic and type-driven:
- **lookup**: entity/record retrieval
- **traverse**: BFS shortest path + target records
- **filter**: operator-based record filtering
- **aggregate**: count/sum/avg/min/max
- **path**: explicit sequence resolution
- **anomaly**: missing link / broken flow detection

How filters/joins/aggregations are handled:
- filters are applied only on allowed fields/operators,
- traversals use graph edges and adjacency indexes,
- aggregation first computes metric, then aligns displayed records to support answer.

Why results are correct:
- no LLM execution authority,
- schema-constrained plan validation,
- deterministic algorithmic execution paths.

## 8. Guardrails
Guardrails enforce scope and safety at planning + response layers:
- prompt-injection pattern checks,
- query length and filter limits,
- entity/field/operator allowlists,
- relationship reachability validation,
- confidence downgrades for ambiguous/unsafe plans,
- payload redaction before response-generation LLM calls.

Scope rule example:
> This system only answers dataset-related questions.  
Out-of-scope or unsafe prompts are blocked or fall back to constrained deterministic behavior.

## 9. Example Queries
Aggregation:
- "Which products have the highest number of billing documents?"

Traversal:
- "Find journal entry for billing document 91150187"

Anomaly detection:
- "Are there any sales order items without a delivery?"

## 10. Challenges & Solutions
### LLM hallucination
- **Issue**: invented entities/fields or wrong structure.
- **Fix**: schema-constrained validation + deterministic fallback parser.

### Data mismatch between answer and UI
- **Issue**: answer computed on subset but UI showed generic rows.
- **Fix**: aggregation alignment pipeline; only supporting records are displayed.

### Query ambiguity
- **Issue**: underspecified user question.
- **Fix**: confidence handling, validation, and safe defaults/fallback.

## 11. Limitations
- Quality depends on underlying schema/data quality.
- LLM provider limits (latency/rate limits/free-tier constraints) affect planner/response quality.
- In-memory graph approach is not ideal for very large datasets or high concurrency.
- Public deployment access control (Vercel protection settings) must be configured correctly.

## 12. Future Improvements
- migrate heavy graph workloads to Neo4j or Memgraph,
- stronger planner with richer disambiguation and retrieval,
- semantic search over entity metadata,
- query/result caching for repeated workloads,
- role-based access control and policy-based data masking,
- deeper observability (trace planner -> executor -> response).

## 13. How to Run
### Prerequisites
- Python 3.11+
- Node.js 18+

### Backend
```bash
cd backend
python3 -m pip install -r requirements.txt
python3 -m uvicorn app.main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

### Optional environment variables
Backend (`backend/.env`):
- `HUGGINGFACE_API_KEY`
- `HUGGINGFACE_MODEL`
- `HUGGINGFACE_PROVIDER`
- `HUGGINGFACE_API_URL`

Frontend (`VITE_API_BASE_URL`) if not using same-origin `/api`.

## 14. Demo
- Web app: [https://dodgeai-sand.vercel.app](https://dodgeai-sand.vercel.app)
- Architecture diagram: [docs/architecture.png](docs/architecture.png)
- Sequence diagram: [docs/sequence_diagram.png](docs/sequence_diagram.png)
- Flow diagram: [docs/flow_diagram.png](docs/flow_diagram.png)

Note: If demo prompts for authentication, disable Vercel deployment protection for public review.

