import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D from "react-force-graph-2d";
import type { ForceGraphMethods } from "react-force-graph-2d";
import { LayoutGrid, Layers, Minimize2, GitBranch, Database } from "lucide-react";
import { InspectorCard } from "./InspectorCard";
import { ChatPanel } from "./ChatPanel";
import { RecordsModal } from "./RecordsModal";
import { DebugPanel } from "./NodePanel";
import type {
  ApiEdge,
  ApiExpandResponse,
  ApiNode,
  ApiNodeDetail,
  GraphLink,
  GraphNode,
  GraphState,
  RecordGraphResponse,
  RecordForceNode,
  RecordForceLink,
} from "./types";
import "./App.css";
import { Group as PanelGroup, Panel, Separator as PanelResizeHandle } from "react-resizable-panels";

const API_BASE  = "http://localhost:8000";
const MAX_NODES = 200;
const MAX_EDGES = 500;

type GraphMode = "entity" | "record";

// ─────────────────────────────────────────────
// Fetch layer
// ─────────────────────────────────────────────

async function safeFetch<T>(url: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url);
  } catch (err) {
    throw new Error(`Network error: ${String(err)}`);
  }
  if (!response.ok) {
    if (response.status === 404) {
      throw new Error(`Endpoint not found (404). Restart the backend server to register new routes.`);
    }
    throw new Error(`HTTP ${response.status} from ${url}`);
  }
  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new Error(`Invalid JSON from ${url}`);
  }
  return data as T;
}

async function fetchInitial(): Promise<{ nodes: ApiNode[]; edges: ApiEdge[] }> {
  const [nodes, edges] = await Promise.all([
    safeFetch<unknown>(`${API_BASE}/nodes`),
    safeFetch<unknown>(`${API_BASE}/edges`),
  ]);
  if (!Array.isArray(nodes)) throw new Error("Expected array from /nodes");
  if (!Array.isArray(edges)) throw new Error("Expected array from /edges");
  return { nodes: nodes as ApiNode[], edges: edges as ApiEdge[] };
}

async function fetchExpand(nodeId: string): Promise<ApiExpandResponse> {
  const data = await safeFetch<ApiExpandResponse>(
    `${API_BASE}/expand?node=${encodeURIComponent(nodeId)}`
  );
  if (
    typeof data !== "object" ||
    data === null ||
    !Array.isArray(data.nodes) ||
    !Array.isArray(data.edges)
  ) {
    throw new Error(`Unexpected expand response shape for "${nodeId}"`);
  }
  return data;
}

async function fetchNodeDetail(nodeId: string): Promise<ApiNodeDetail> {
  const data = await safeFetch<ApiNodeDetail>(
    `${API_BASE}/nodes/${encodeURIComponent(nodeId)}`
  );
  if (typeof data !== "object" || data === null || typeof data.name !== "string") {
    throw new Error(`Unexpected node detail response for "${nodeId}"`);
  }
  return data;
}

async function fetchRecordGraph(): Promise<RecordGraphResponse> {
  const data = await safeFetch<RecordGraphResponse>(
    `${API_BASE}/record-graph?records_per_entity=5`
  );
  return data;
}

// ─────────────────────────────────────────────
// Sanitization / merge helpers
// ─────────────────────────────────────────────

function toGraphNode(n: ApiNode): GraphNode | null {
  if (typeof n?.name !== "string" || n.name.trim() === "") return null;
  return { id: n.name, label: n.name, record_count: n.record_count ?? null };
}

function edgeKey(from: string, to: string, relationship: string): string {
  return `${from}||${to}||${relationship}`;
}

function emptyGraphState(): GraphState {
  return { nodeMap: new Map(), edgeMap: new Map() };
}

function mergeIntoState(
  prev: GraphState,
  rawNodes: ApiNode[],
  rawEdges: ApiEdge[]
): { next: GraphState; addedNodes: number; addedEdges: number; skippedEdges: number } {
  const nodeMap = new Map(prev.nodeMap);
  const edgeMap = new Map(prev.edgeMap);
  let addedNodes = 0, addedEdges = 0, skippedEdges = 0;

  for (const raw of rawNodes) {
    if (nodeMap.size >= MAX_NODES) break;
    const node = toGraphNode(raw);
    if (node && !nodeMap.has(node.id)) { nodeMap.set(node.id, node); addedNodes++; }
  }

  for (const raw of rawEdges) {
    if (
      typeof raw?.from !== "string" || typeof raw?.to !== "string" ||
      raw.from.trim() === "" || raw.to.trim() === ""
    ) { skippedEdges++; continue; }
    if (!nodeMap.has(raw.from) || !nodeMap.has(raw.to)) { skippedEdges++; continue; }
    const key = edgeKey(raw.from, raw.to, raw.relationship ?? "");
    if (edgeMap.has(key)) continue;
    if (edgeMap.size >= MAX_EDGES) break;
    edgeMap.set(key, {
      source: raw.from, target: raw.to,
      label: typeof raw.relationship === "string" ? raw.relationship : "",
      type:  typeof raw.type === "string" ? raw.type : "STRUCTURAL",
    });
    addedEdges++;
  }

  return { next: { nodeMap, edgeMap }, addedNodes, addedEdges, skippedEdges };
}

// ─────────────────────────────────────────────
// App component
// ─────────────────────────────────────────────

type UIState = "loading" | "error" | "empty" | "success";

export default function App() {
  const [uiState, setUiState]     = useState<UIState>("loading");
  const [errorMsg, setErrorMsg]   = useState("");
  const [graphState, setGraphState] = useState<GraphState>(emptyGraphState());

  // ── Graph mode ──────────────────────────────
  const [graphMode, setGraphMode] = useState<GraphMode>("entity");

  // ── Record graph data ───────────────────────
  const [recordGraphData, setRecordGraphData] = useState<RecordGraphResponse | null>(null);
  const [recordGraphLoading, setRecordGraphLoading] = useState(false);
  const [recordGraphError, setRecordGraphError] = useState<string | null>(null);
  const recordGraphFetched = useRef(false);

  // Expansion state (entity mode only)
  const [selectedId, setSelectedId]       = useState<string | null>(null);
  const [expandingIds, setExpandingIds]   = useState<Set<string>>(new Set());
  const [expandError, setExpandError]     = useState<string | null>(null);
  const [limitHit, setLimitHit]           = useState(false);
  const expandedRef = useRef<Set<string>>(new Set());
  const [expandedCount, setExpandedCount] = useState(0);

  // Inspector state
  const [inspectorDetail, setInspectorDetail] = useState<ApiNodeDetail | null>(null);
  const [inspectorLoading, setInspectorLoading] = useState(false);
  const [inspectorError, setInspectorError]     = useState<string | null>(null);
  const [inspectorPos, setInspectorPos] = useState<{ x: number; y: number } | null>(null);
  const metaCacheRef = useRef<Map<string, ApiNodeDetail>>(new Map());

  // Record graph inspector state
  const [selectedRecordNode, setSelectedRecordNode] = useState<RecordForceNode | null>(null);
  const [recordInspectorPos, setRecordInspectorPos] = useState<{ x: number; y: number } | null>(null);

  // Controls
  const [showOverlay, setShowOverlay] = useState(true);

  // Records modal
  const [recordsNodeName, setRecordsNodeName] = useState<string | null>(null);

  // Visual
  const [hovered, setHovered] = useState<GraphNode | null>(null);
  const [hoveredRecord, setHoveredRecord] = useState<RecordForceNode | null>(null);
  const [graphDims, setGraphDims] = useState({ w: 0, h: 0 });
  const [graphAreaEl, setGraphAreaEl] = useState<HTMLDivElement | null>(null);
  const graphAreaRef = useCallback((node: HTMLDivElement | null) => {
    setGraphAreaEl(node);
  }, []);

  const fetchedRef = useRef(false);
  const fgRef = useRef<ForceGraphMethods<GraphNode, GraphLink>>(undefined);
  const fgRecordRef = useRef<ForceGraphMethods<RecordForceNode, RecordForceLink>>(undefined);

  // ── Initial fetch (entity graph) ────────────
  useEffect(() => {
    if (fetchedRef.current) return;
    fetchedRef.current = true;
    fetchInitial()
      .then(({ nodes, edges }) => {
        const { next } = mergeIntoState(emptyGraphState(), nodes, edges);
        setGraphState(next);
        setUiState(next.nodeMap.size === 0 ? "empty" : "success");
      })
      .catch((err: Error) => { setErrorMsg(err.message); setUiState("error"); });
  }, []);

  // ── Lazy fetch record graph ─────────────────
  useEffect(() => {
    if (graphMode !== "record" || recordGraphFetched.current || recordGraphLoading) return;
    recordGraphFetched.current = true;
    setRecordGraphLoading(true);
    setRecordGraphError(null);
    fetchRecordGraph()
      .then((data) => {
        if (!data.nodes || data.nodes.length === 0) {
          setRecordGraphError("Record graph returned no nodes");
          recordGraphFetched.current = false;
          return;
        }
        setRecordGraphData(data);
      })
      .catch((err: Error) => {
        setRecordGraphError(err.message);
        recordGraphFetched.current = false; // allow retry
      })
      .finally(() => setRecordGraphLoading(false));
  }, [graphMode, recordGraphLoading]);

  // ── Measure graph container ─────────────────
  useEffect(() => {
    if (!graphAreaEl) return;
    const { width, height } = graphAreaEl.getBoundingClientRect();
    if (width > 0 && height > 0) {
      setGraphDims({ w: Math.floor(width), h: Math.floor(height) });
    }
    const ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      if (width > 0 && height > 0) {
        setGraphDims({ w: Math.floor(width), h: Math.floor(height) });
      }
    });
    ro.observe(graphAreaEl);
    return () => ro.disconnect();
  }, [graphAreaEl]);

  // ── Mode switching ──────────────────────────
  const handleModeSwitch = useCallback((mode: GraphMode) => {
    if (mode === graphMode) return;
    // Clear selections when switching
    setSelectedId(null);
    setSelectedRecordNode(null);
    setInspectorDetail(null);
    setInspectorPos(null);
    setRecordInspectorPos(null);
    setHovered(null);
    setHoveredRecord(null);
    setRecordGraphError(null);
    // Reset zoom-to-fit so it re-triggers on each mode entry
    if (mode === "record") didFitRecordRef.current = false;
    setGraphMode(mode);
  }, [graphMode]);

  // ── Node click: expand + inspect (ENTITY) ───
  const handleNodeClick = useCallback(
    (rawNode: object) => {
      const node = rawNode as GraphNode;
      const id = node.id;

      const deselecting = selectedId === id;
      setSelectedId(deselecting ? null : id);
      setExpandError(null);

      if (deselecting) return;

      // Position the inspector card near the node
      if (fgRef.current && node.x != null && node.y != null) {
        const screen = fgRef.current.graph2ScreenCoords(node.x, node.y);
        setInspectorPos({ x: screen.x, y: screen.y });
      }

      // Metadata fetch (cached)
      if (metaCacheRef.current.has(id)) {
        setInspectorDetail(metaCacheRef.current.get(id)!);
        setInspectorError(null);
      } else {
        setInspectorLoading(true);
        setInspectorError(null);
        setInspectorDetail(null);
        fetchNodeDetail(id)
          .then((detail) => {
            metaCacheRef.current.set(id, detail);
            setSelectedId((current) => {
              if (current === id) setInspectorDetail(detail);
              return current;
            });
          })
          .catch((err: Error) => {
            setSelectedId((current) => {
              if (current === id) setInspectorError(err.message);
              return current;
            });
          })
          .finally(() => setInspectorLoading(false));
      }

      // Graph expansion
      if (expandedRef.current.has(id) || limitHit) return;
      setExpandingIds((prev) => new Set(prev).add(id));

      fetchExpand(id)
        .then((resp) => {
          const allNodes = [resp.center_node, ...resp.nodes];
          setGraphState((prev) => {
            if (prev.nodeMap.size >= MAX_NODES || prev.edgeMap.size >= MAX_EDGES) {
              setLimitHit(true);
              return prev;
            }
            const { next } = mergeIntoState(prev, allNodes, resp.edges);
            if (next.nodeMap.size >= MAX_NODES || next.edgeMap.size >= MAX_EDGES) {
              setLimitHit(true);
            }
            expandedRef.current.add(id);
            setExpandedCount(expandedRef.current.size);
            return next;
          });
        })
        .catch((err: Error) => setExpandError(`Expand failed for "${id}": ${err.message}`))
        .finally(() => setExpandingIds((prev) => {
          const next = new Set(prev); next.delete(id); return next;
        }));
    },
    [limitHit, selectedId]
  );

  // ── Record node click (RECORD mode) ─────────
  const handleRecordNodeClick = useCallback(
    (rawNode: object) => {
      const node = rawNode as RecordForceNode;
      const deselecting = selectedRecordNode?.id === node.id;

      if (deselecting) {
        setSelectedRecordNode(null);
        setRecordInspectorPos(null);
        return;
      }

      setSelectedRecordNode(node);

      if (fgRecordRef.current && node.x != null && node.y != null) {
        const screen = fgRecordRef.current.graph2ScreenCoords(node.x, node.y);
        setRecordInspectorPos({ x: screen.x, y: screen.y });
      }
    },
    [selectedRecordNode]
  );

  // Close inspector when deselected
  useEffect(() => {
    if (selectedId === null) {
      setInspectorDetail(null);
      setInspectorError(null);
      setInspectorLoading(false);
      setInspectorPos(null);
    }
  }, [selectedId]);

  // ── Derived graph data (entity) ────────────
  const entityGraphData = useMemo(() => ({
    nodes: Array.from(graphState.nodeMap.values()),
    links: Array.from(graphState.edgeMap.values()),
  }), [graphState]);

  const neighbourIds = useMemo<Set<string>>(() => {
    if (!selectedId) return new Set();
    const s = new Set<string>();
    for (const link of graphState.edgeMap.values()) {
      const src = typeof link.source === "string" ? link.source : link.source.id;
      const tgt = typeof link.target === "string" ? link.target : link.target.id;
      if (src === selectedId) s.add(tgt);
      if (tgt === selectedId) s.add(src);
    }
    return s;
  }, [selectedId, graphState.edgeMap]);

  // ── Derived graph data (record) ────────────
  const recordForceData = useMemo(() => {
    if (!recordGraphData) return { nodes: [] as RecordForceNode[], links: [] as RecordForceLink[] };
    return {
      nodes: recordGraphData.nodes.map((n) => ({ ...n } as RecordForceNode)),
      links: recordGraphData.edges.map((e) => ({
        source: e.source,
        target: e.target,
        relationship: e.relationship,
      } as RecordForceLink)),
    };
  }, [recordGraphData]);

  const recordNeighbourIds = useMemo<Set<string>>(() => {
    if (!selectedRecordNode || !recordGraphData) return new Set();
    const s = new Set<string>();
    for (const edge of recordGraphData.edges) {
      if (edge.source === selectedRecordNode.id) s.add(edge.target);
      if (edge.target === selectedRecordNode.id) s.add(edge.source);
    }
    return s;
  }, [selectedRecordNode, recordGraphData]);

  // ── Initial zoom-to-fit ────────────────────
  const didFitRef = useRef(false);
  useEffect(() => {
    if (!didFitRef.current && entityGraphData.nodes.length > 0 && fgRef.current) {
      didFitRef.current = true;
      setTimeout(() => fgRef.current?.zoomToFit(400, 60), 300);
    }
  }, [entityGraphData.nodes.length]);

  // Zoom-to-fit record graph when it first becomes visible
  const didFitRecordRef = useRef(false);
  useEffect(() => {
    if (graphMode !== "record" || didFitRecordRef.current || recordForceData.nodes.length === 0) return;
    // Use a short delay to let ForceGraph2D mount and populate the ref
    const timer = setTimeout(() => {
      if (fgRecordRef.current) {
        fgRecordRef.current.zoomToFit(400, 60);
        didFitRecordRef.current = true;
      }
    }, 600);
    return () => clearTimeout(timer);
  }, [graphMode, recordForceData.nodes.length]);

  // ── Zoom-to-fit handler ────────────────────
  const handleMinimize = useCallback(() => {
    if (graphMode === "entity") {
      fgRef.current?.zoomToFit(400, 60);
    } else {
      fgRecordRef.current?.zoomToFit(400, 60);
    }
  }, [graphMode]);

  // ── Full-screen status screens ─────────────
  if (uiState === "loading") {
    return <div className="status"><span className="spinner" />Loading graph data...</div>;
  }
  if (uiState === "error") {
    return (
      <div className="status error">
        <strong>Failed to load graph</strong>
        <span>{errorMsg}</span>
      </div>
    );
  }
  if (uiState === "empty") {
    return (
      <div className="status">
        <strong>No data available</strong>
        <span>The graph is empty. Check the backend data source.</span>
      </div>
    );
  }

  return (
    <div className="app">
      {/* ── Header (breadcrumb style) ──────── */}
      <header>
        <div className="header-icon">
          <LayoutGrid />
        </div>
        <span className="header-sep">|</span>
        <span className="header-breadcrumb">
          Mapping / <strong>Order to Cash</strong>
        </span>
      </header>

      {/* ── Body: graph + chat ─────────────── */}
      <PanelGroup orientation="horizontal" className="body-row">
          <Panel defaultSize="65" minSize="20">

        {/* ── Graph canvas ───────────────────── */}
        <div className="graph-area" ref={graphAreaRef}>

          {/* ── Mode toggle (centered) ──────── */}
          <div className="graph-mode-toggle">
            <button
              className={`mode-toggle-btn ${graphMode === "entity" ? "active" : ""}`}
              onClick={() => handleModeSwitch("entity")}
            >
              <GitBranch />
              Entity Graph
            </button>
            <button
              className={`mode-toggle-btn ${graphMode === "record" ? "active" : ""}`}
              onClick={() => handleModeSwitch("record")}
            >
              <Database />
              Record Graph
            </button>
          </div>

          {/* Control buttons */}
          <div className="graph-controls">
            <button className="control-btn" onClick={handleMinimize}>
              <Minimize2 />
              Minimize
            </button>
            {graphMode === "entity" && (
              <button
                className={`control-btn ${showOverlay ? "active" : ""}`}
                onClick={() => setShowOverlay((v) => !v)}
              >
                <Layers />
                {showOverlay ? "Hide Granular Overlay" : "Show Granular Overlay"}
              </button>
            )}
          </div>

          {/* Banners (entity mode) */}
          {graphMode === "entity" && limitHit && (
            <div className="warn-banner">
              Graph limit reached ({MAX_NODES} nodes / {MAX_EDGES} edges)
            </div>
          )}
          {graphMode === "entity" && expandError && (
            <div className="warn-banner warn-error">{expandError}</div>
          )}
          {graphMode === "entity" && expandingIds.size > 0 && (
            <div className="expand-indicator">
              <span className="spinner spinner-sm" />
              Expanding {Array.from(expandingIds).join(", ")}
            </div>
          )}

          {/* Record graph loading */}
          {graphMode === "record" && recordGraphLoading && (
            <div className="expand-indicator">
              <span className="spinner spinner-sm" />
              Loading record graph...
            </div>
          )}

          {/* Record graph error */}
          {graphMode === "record" && recordGraphError && !recordGraphLoading && (
            <div className="warn-banner warn-error">
              Record graph failed: {recordGraphError}
              <button
                onClick={() => { recordGraphFetched.current = false; setRecordGraphError(null); setRecordGraphLoading(false); }}
                style={{
                  marginLeft: 12,
                  padding: "2px 10px",
                  borderRadius: 6,
                  border: "1px solid #fca5a5",
                  background: "#ffffff",
                  color: "#991b1b",
                  fontSize: 11,
                  fontWeight: 600,
                  cursor: "pointer",
                  fontFamily: "inherit",
                }}
              >
                Retry
              </button>
            </div>
          )}

          {/* ── ENTITY GRAPH ──────────────────── */}
          {graphMode === "entity" && graphDims.w > 0 && <ForceGraph2D
            key="entity-graph"
            ref={fgRef}
            graphData={entityGraphData}
            nodeId="id"
            nodeLabel=""
            onNodeClick={handleNodeClick}
            onNodeHover={(node) => setHovered((node as GraphNode) ?? null)}
            onBackgroundClick={() => setSelectedId(null)}
            nodeCanvasObject={(rawNode, ctx, globalScale) => {
              const node = rawNode as GraphNode;
              const isSelected  = node.id === selectedId;
              const isNeighbour = neighbourIds.has(node.id);
              const isDimmed    = selectedId !== null && !isSelected && !isNeighbour;
              const isExpanding = expandingIds.has(node.id);

              const r = isSelected ? 10 : isNeighbour ? 7 : 6;
              ctx.globalAlpha = isDimmed ? 0.25 : 1;

              // Node circle
              ctx.beginPath();
              ctx.arc(node.x!, node.y!, r, 0, 2 * Math.PI);

              if (isSelected) {
                ctx.fillStyle = "#3b82f6";
                ctx.fill();
                ctx.strokeStyle = "#2563eb";
                ctx.lineWidth = 2;
                ctx.stroke();
              } else {
                ctx.fillStyle = isDimmed ? "#e8d5d5" : "#e8a0a0";
                ctx.fill();
                ctx.strokeStyle = isDimmed ? "#ddd" : "#d48a8a";
                ctx.lineWidth = 1;
                ctx.stroke();
              }

              // Loading ring on expanding
              if (isExpanding) {
                const t = (Date.now() % 1200) / 1200;
                ctx.beginPath();
                ctx.arc(node.x!, node.y!, r + 4, t * Math.PI * 2, t * Math.PI * 2 + Math.PI * 1.2);
                ctx.strokeStyle = "#3b82f6";
                ctx.lineWidth = 1.5;
                ctx.stroke();
              }

              // Label
              if (globalScale >= 1.5 || isSelected) {
                const fontSize = isSelected
                  ? Math.min(Math.max(11 / globalScale, 4), 12)
                  : Math.min(Math.max(9 / globalScale, 3), 10);
                ctx.font = `500 ${fontSize}px Inter, system-ui, sans-serif`;
                ctx.textAlign = "center";
                ctx.textBaseline = "top";
                ctx.fillStyle = isSelected ? "#1e40af" : "#6b7280";
                ctx.fillText(node.label, node.x!, node.y! + r + 3);
              }

              ctx.globalAlpha = 1;
            }}
            nodePointerAreaPaint={(rawNode, color, ctx) => {
              const node = rawNode as GraphNode;
              ctx.fillStyle = color;
              ctx.beginPath();
              ctx.arc(node.x!, node.y!, 12, 0, 2 * Math.PI);
              ctx.fill();
            }}
            linkColor={() => "#93c5fd"}
            linkWidth={(rawLink) => {
              const link = rawLink as GraphLink;
              const src = typeof link.source === "string" ? link.source : link.source.id;
              const tgt = typeof link.target === "string" ? link.target : link.target.id;
              return (selectedId && (src === selectedId || tgt === selectedId)) ? 2.5 : 1;
            }}
            linkDirectionalArrowLength={5}
            linkDirectionalArrowRelPos={1}
            linkCurvature={0.1}
            linkCanvasObjectMode={() => "after"}
            linkCanvasObject={(rawLink, ctx, globalScale) => {
              if (globalScale < 1.5 || !showOverlay) return;
              const l = rawLink as GraphLink & { source: GraphNode; target: GraphNode };
              if (l.source?.x == null || l.target?.x == null) return;
              const mx = (l.source.x + l.target.x) / 2;
              const my = ((l.source.y ?? 0) + (l.target.y ?? 0)) / 2;
              const fontSize = Math.min(Math.max(8 / globalScale, 2), 9);
              ctx.font = `400 ${fontSize}px Inter, system-ui, sans-serif`;
              ctx.fillStyle = "#9ca3af";
              ctx.textAlign = "center";
              ctx.textBaseline = "middle";
              ctx.fillText(l.label, mx, my);
            }}
            backgroundColor="#f7f8fa"
            width={graphDims.w}
            height={graphDims.h}
          />}

          {/* ── RECORD GRAPH ─────────────────── */}
          {graphMode === "record" && graphDims.w > 0 && recordGraphData && <ForceGraph2D
            key="record-graph"
            ref={fgRecordRef}
            graphData={recordForceData}
            nodeId="id"
            nodeLabel=""
            onNodeClick={handleRecordNodeClick}
            onNodeHover={(node) => setHoveredRecord((node as RecordForceNode) ?? null)}
            onBackgroundClick={() => { setSelectedRecordNode(null); setRecordInspectorPos(null); }}
            nodeCanvasObject={(rawNode, ctx, globalScale) => {
              const node = rawNode as RecordForceNode;
              const isSelected  = node.id === selectedRecordNode?.id;
              const isNeighbour = recordNeighbourIds.has(node.id);
              const isDimmed    = selectedRecordNode !== null && !isSelected && !isNeighbour;

              const baseColor = recordGraphData.entity_colors[node.entity] ?? "#93c5fd";
              const r = isSelected ? 9 : isNeighbour ? 7 : 5;

              ctx.globalAlpha = isDimmed ? 0.2 : 1;

              // Node circle — colored by entity type
              ctx.beginPath();
              ctx.arc(node.x!, node.y!, r, 0, 2 * Math.PI);

              if (isSelected) {
                ctx.fillStyle = "#3b82f6";
                ctx.fill();
                ctx.strokeStyle = "#1d4ed8";
                ctx.lineWidth = 2;
                ctx.stroke();
              } else {
                ctx.fillStyle = isDimmed ? adjustAlpha(baseColor, 0.4) : baseColor;
                ctx.fill();
                ctx.strokeStyle = darken(baseColor, 0.15);
                ctx.lineWidth = 1;
                ctx.stroke();
              }

              // Label: show entity:pk when zoomed in or selected
              if (globalScale >= 2.0 || isSelected) {
                const fontSize = isSelected
                  ? Math.min(Math.max(10 / globalScale, 3.5), 11)
                  : Math.min(Math.max(8 / globalScale, 2.5), 9);
                ctx.font = `500 ${fontSize}px Inter, system-ui, sans-serif`;
                ctx.textAlign = "center";
                ctx.textBaseline = "top";
                ctx.fillStyle = isSelected ? "#1e40af" : "#6b7280";
                const label = node.primary_key_value.length > 12
                  ? node.primary_key_value.slice(0, 10) + "…"
                  : node.primary_key_value;
                ctx.fillText(label, node.x!, node.y! + r + 2);
              }

              ctx.globalAlpha = 1;
            }}
            nodePointerAreaPaint={(rawNode, color, ctx) => {
              const node = rawNode as RecordForceNode;
              ctx.fillStyle = color;
              ctx.beginPath();
              ctx.arc(node.x!, node.y!, 10, 0, 2 * Math.PI);
              ctx.fill();
            }}
            linkColor={() => "#d1d5db"}
            linkWidth={(rawLink) => {
              const link = rawLink as RecordForceLink;
              const src = typeof link.source === "string" ? link.source : link.source.id;
              const tgt = typeof link.target === "string" ? link.target : link.target.id;
              return (selectedRecordNode && (src === selectedRecordNode.id || tgt === selectedRecordNode.id)) ? 2 : 0.8;
            }}
            linkDirectionalArrowLength={4}
            linkDirectionalArrowRelPos={1}
            linkCurvature={0.15}
            linkCanvasObjectMode={() => "after"}
            linkCanvasObject={(rawLink, ctx, globalScale) => {
              if (globalScale < 2.5) return;
              const l = rawLink as RecordForceLink & { source: RecordForceNode; target: RecordForceNode };
              if (l.source?.x == null || l.target?.x == null) return;
              const mx = (l.source.x + l.target.x) / 2;
              const my = ((l.source.y ?? 0) + (l.target.y ?? 0)) / 2;
              const fontSize = Math.min(Math.max(7 / globalScale, 2), 8);
              ctx.font = `400 ${fontSize}px Inter, system-ui, sans-serif`;
              ctx.fillStyle = "#9ca3af";
              ctx.textAlign = "center";
              ctx.textBaseline = "middle";
              ctx.fillText(l.relationship, mx, my);
            }}
            backgroundColor="#f7f8fa"
            width={graphDims.w}
            height={graphDims.h}
          />}

          {/* ── Inspector cards ───────────────── */}

          {/* Entity mode inspector */}
          {graphMode === "entity" && (
            <InspectorCard
              detail={inspectorDetail}
              loading={inspectorLoading}
              error={inspectorError}
              position={inspectorPos}
              containerWidth={graphDims.w}
              containerHeight={graphDims.h}
              onClose={() => setSelectedId(null)}
              onViewRecords={(name) => setRecordsNodeName(name)}
            />
          )}

          {/* Record mode inspector */}
          {graphMode === "record" && selectedRecordNode && recordInspectorPos && (
            <RecordInspectorCard
              node={selectedRecordNode}
              entityColors={recordGraphData?.entity_colors ?? {}}
              position={recordInspectorPos}
              containerWidth={graphDims.w}
              containerHeight={graphDims.h}
              connectedCount={recordNeighbourIds.size}
              onClose={() => { setSelectedRecordNode(null); setRecordInspectorPos(null); }}
            />
          )}

          {/* Entity hover tooltip */}
          {graphMode === "entity" && hovered && !selectedId && (
            <div className="tooltip">
              <strong>{hovered.label}</strong>
              {hovered.record_count != null && (
                <span>{hovered.record_count.toLocaleString()} records</span>
              )}
              <span className="tag tag-click">click to inspect</span>
            </div>
          )}

          {/* Record hover tooltip */}
          {graphMode === "record" && hoveredRecord && !selectedRecordNode && (
            <div className="tooltip">
              <strong>{hoveredRecord.entity}</strong>
              <span style={{ fontFamily: "'SF Mono', 'Fira Code', monospace", fontSize: 11 }}>
                {hoveredRecord.primary_key_value}
              </span>
              <span className="tag tag-click">click to inspect</span>
            </div>
          )}

          {/* Entity color legend (record mode) */}
          {graphMode === "record" && recordGraphData && (
            <div className="record-legend">
              <span className="record-legend-title">Entities</span>
              {Object.entries(recordGraphData.entity_colors).map(([entity, color]) => (
                <span key={entity} className="record-legend-item">
                  <span className="record-legend-dot" style={{ background: color }} />
                  {entity}
                </span>
              ))}
            </div>
          )}

          {/* Graph state bar */}
          <div className="graph-stats">
            {graphMode === "entity" ? (
              <DebugPanel
                nodeCount={entityGraphData.nodes.length}
                edgeCount={entityGraphData.links.length}
                expandedCount={expandedCount}
                activeExpansions={expandingIds.size}
              />
            ) : (
              <DebugPanel
                nodeCount={recordForceData.nodes.length}
                edgeCount={recordForceData.links.length}
                expandedCount={0}
                activeExpansions={0}
              />
            )}
          </div>
        </div>

          </Panel>
          <PanelResizeHandle
            className="resize-handle"
            style={{ width: 5, cursor: "col-resize", background: "#e2e8f0", flexShrink: 0 }}
          />
          <Panel defaultSize="35" minSize="20" maxSize="55">
            <ChatPanel />
          </Panel>
      </PanelGroup>

      {/* Records modal */}
      {recordsNodeName && (
        <RecordsModal
          nodeName={recordsNodeName}
          recordCount={inspectorDetail?.record_count ?? null}
          onClose={() => setRecordsNodeName(null)}
        />
      )}
    </div>
  );
}

// ─────────────────────────────────────────────
// Record Inspector Card (inline — record mode)
// ─────────────────────────────────────────────

function RecordInspectorCard({
  node,
  entityColors,
  position,
  containerWidth,
  containerHeight,
  connectedCount,
  onClose,
}: {
  node: RecordForceNode;
  entityColors: Record<string, string>;
  position: { x: number; y: number };
  containerWidth: number;
  containerHeight: number;
  connectedCount: number;
  onClose: () => void;
}) {
  void onClose;

  const CARD_W = 300;
  const CARD_H_EST = 380;
  const OFFSET = 24;

  let x = position.x + OFFSET;
  let y = position.y - 48;
  if (x + CARD_W > containerWidth - 16) x = position.x - CARD_W - OFFSET;
  if (y + CARD_H_EST > containerHeight - 16) y = containerHeight - CARD_H_EST - 16;
  if (y < 16) y = 16;
  if (x < 16) x = 16;

  const entityColor = entityColors[node.entity] ?? "#93c5fd";

  // Build key-value entries, filter out nulls
  const entries = Object.entries(node.fields).filter(
    ([, val]) => val !== null && val !== undefined && val !== ""
  );
  const MAX_FIELDS = 10;
  const visible = entries.slice(0, MAX_FIELDS);
  const hiddenCount = entries.length - MAX_FIELDS;

  return (
    <div
      className="absolute z-20 animate-inspector-in"
      style={{ left: x, top: y, width: CARD_W }}
      onClick={(e) => e.stopPropagation()}
    >
      <div
        style={{
          background: "#ffffff",
          borderRadius: 12,
          border: "1px solid #e5e7eb",
          boxShadow: "0 8px 30px rgba(0, 0, 0, 0.12)",
          overflow: "hidden",
          maxHeight: containerHeight - 32,
          overflowY: "auto",
        }}
      >
        {/* Header with entity badge */}
        <div style={{ padding: "14px 18px 0" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
            <span style={{
              width: 10, height: 10, borderRadius: "50%",
              background: entityColor, flexShrink: 0,
            }} />
            <span style={{
              fontSize: 11, fontWeight: 600, color: "#6b7280",
              textTransform: "uppercase", letterSpacing: "0.04em",
            }}>
              {node.entity}
            </span>
          </div>
          <h3 style={{
            fontSize: 15, fontWeight: 700, color: "#111827", margin: 0,
            fontFamily: "'SF Mono', 'Fira Code', monospace",
          }}>
            {node.primary_key_value}
          </h3>
        </div>

        {/* Key-value fields */}
        <div style={{ padding: "12px 18px 14px" }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
            {visible.map(([key, value], i) => (
              <div
                key={key}
                style={{
                  display: "flex",
                  gap: 8,
                  padding: "5px 0",
                  borderBottom: i < visible.length - 1 ? "1px solid #f3f4f6" : "none",
                  fontSize: 13,
                  lineHeight: 1.5,
                }}
              >
                <span style={{
                  fontWeight: 600,
                  color: "#111827",
                  minWidth: 0,
                  flexShrink: 0,
                  whiteSpace: "nowrap",
                  fontSize: 12,
                }}>
                  {formatColumnLabel(key)}:
                </span>
                <span style={{
                  color: "#374151",
                  wordBreak: "break-word",
                  fontWeight: 400,
                  fontFamily: isNumericish(value) ? "'SF Mono', 'Fira Code', monospace" : "inherit",
                  fontSize: 13,
                }}>
                  {formatDisplayValue(value)}
                </span>
              </div>
            ))}
          </div>

          {hiddenCount > 0 && (
            <p style={{ fontSize: 11, color: "#9ca3af", fontStyle: "italic", margin: "6px 0 0" }}>
              +{hiddenCount} more fields
            </p>
          )}

          {/* Connections badge */}
          <div style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            marginTop: 12,
            padding: "8px 10px",
            borderRadius: 8,
            background: "#f9fafb",
            border: "1px solid #f3f4f6",
          }}>
            <GitBranch style={{ width: 12, height: 12, color: "#9ca3af" }} />
            <span style={{ fontSize: 12, color: "#6b7280" }}>
              <strong style={{ color: "#374151", fontWeight: 600 }}>
                {connectedCount}
              </strong>
              {" "}connected {connectedCount === 1 ? "record" : "records"}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────
// Helpers (record inspector)
// ─────────────────────────────────────────────

function formatColumnLabel(col: string): string {
  return col.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatDisplayValue(val: unknown): string {
  if (val === null || val === undefined) return "\u2014";
  if (typeof val === "boolean") return val ? "Yes" : "No";
  if (typeof val === "number") return val.toLocaleString();
  const s = String(val);
  if (/^\d{4}-\d{2}-\d{2}T/.test(s)) return s.slice(0, 10);
  return s;
}

function isNumericish(val: unknown): boolean {
  return typeof val === "number" || (typeof val === "string" && /^\d+$/.test(val));
}

// ─────────────────────────────────────────────
// Color helpers (record graph)
// ─────────────────────────────────────────────

function adjustAlpha(hex: string, alpha: number): string {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function darken(hex: string, amount: number): string {
  const r = Math.max(0, parseInt(hex.slice(1, 3), 16) - Math.round(255 * amount));
  const g = Math.max(0, parseInt(hex.slice(3, 5), 16) - Math.round(255 * amount));
  const b = Math.max(0, parseInt(hex.slice(5, 7), 16) - Math.round(255 * amount));
  return `#${r.toString(16).padStart(2, "0")}${g.toString(16).padStart(2, "0")}${b.toString(16).padStart(2, "0")}`;
}
