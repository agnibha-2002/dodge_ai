import { useEffect, useRef, useState } from "react";
import { Loader2, ChevronDown, ChevronRight, ChevronLeft, PanelRightClose } from "lucide-react";
import { apiUrl } from "./api";

// ─── Plan types ───────────────────────────────────────────────────────────────

type PlanType = "lookup" | "traverse" | "filter" | "aggregate" | "path" | "anomaly";

interface AggregationSpec {
  metric: "count" | "sum" | "avg" | "max" | "min";
  group_by?: string;
  target?: string;
  sort?: "asc" | "desc";
  limit?: number;
}

interface PathSpec {
  sequence: string[];
  direction: "forward" | "backward";
}

interface AnomalySpec {
  type: "missing_link" | "broken_flow" | "inconsistency";
  description: string;
}

interface PlanFilter {
  entity?: string;
  field: string;
  operator: string;
  value: string;
}

interface GraphQueryPlan {
  type: PlanType;
  start_entity: string | null;
  target_entity: string | null;
  aggregation?: AggregationSpec | null;
  path?: PathSpec | null;
  filters: PlanFilter[];
  anomaly?: AnomalySpec | null;
  confidence: "HIGH" | "MEDIUM" | "LOW";
}

// ─── Execution result shapes ──────────────────────────────────────────────────

interface TraversalHop {
  from_entity: string;
  to_entity: string;
  relationship: string;
}

interface LookupResult {
  type: "lookup";
  entity: string;
  id: string | null;
  record: Record<string, unknown> | null;
  records: Record<string, unknown>[];
  record_count: number | null;
  attributes: string[];
  connected_entities: string[];
}

interface TraverseResult {
  type: "traverse";
  start_entity: string;
  target_entity: string;
  path: string[];
  hops: TraversalHop[];
  path_length: number;
  target_records: Record<string, unknown>[];
  target_record_count: number | null;
}

interface FilterResult {
  type: "filter";
  entity: string;
  filters_applied: { field: string; operator: string; value: string }[];
  records: Record<string, unknown>[];
  record_count: number;
}

interface AggregateResult {
  type: "aggregate";
  metric: string;
  field?: string;
  entity?: string;
  group_by?: string;
  target?: string;
  value?: number;
  sample_size?: number;
  records?: Record<string, unknown>[];
  rows?: { group?: string; entity?: string; count?: number; [k: string]: unknown }[];
  row_count?: number;
  metadata?: {
    type?: "aggregate";
    filter_applied?: boolean;
  };
}

interface PathResult {
  type: "path";
  sequence: string[];
  hops: TraversalHop[];
  path_length: number;
  entity_records: Record<string, Record<string, unknown>[]>;
  id_filter?: { entity: string; field: string; value: string } | null;
}

interface AnomalyResult {
  type: "anomaly";
  anomaly_type: string;
  description: string;
  start_entity: string;
  target_entity: string | null;
  checked: number;
  flagged_count: number;
  flagged: { record: Record<string, unknown>; issue: string }[];
}

type ExecResult =
  | LookupResult
  | TraverseResult
  | FilterResult
  | AggregateResult
  | PathResult
  | AnomalyResult;

interface Execution {
  result: ExecResult | null;
  status: "success" | "empty" | "error";
  error?: string | null;
}

interface Message {
  id: number;
  role: "user" | "assistant";
  content: string;
  plan?: GraphQueryPlan;
  execution?: Execution;
}

// ─── Constants ────────────────────────────────────────────────────────────────

const STORAGE_KEY = "dodge_ai_messages_v1";

// Dark palette — atmospheric navy, not flat black
const D = {
  bg:      "#0d1421",
  surface: "#131f35",
  surf2:   "#1a2840",
  border:  "#1f3050",
  text:    "#dde6f0",
  muted:   "#6b85a6",
  dim:     "#3d5070",
  accent:  "#3b82f6",
};

// ─── Persistence ──────────────────────────────────────────────────────────────

function loadMessages(): Message[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Message[]) : [];
  } catch {
    return [];
  }
}

const GREETING: Message = {
  id: 1,
  role: "assistant",
  content: "Hi! I can help you explore your **Order to Cash** data. Ask me anything — like which orders are linked to a delivery, how many invoices exist, or whether any payments are missing.",
};

// ─── Avatar ───────────────────────────────────────────────────────────────────

function AgentAvatar() {
  return (
    <div style={{
      width: 28, height: 28, borderRadius: 7,
      background: "#1a3060", border: `1px solid ${D.border}`,
      display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
    }}>
      <svg width="13" height="13" viewBox="0 0 14 14" fill="none">
        <rect x="2" y="3" width="10" height="8" rx="2" stroke="#7ec8ff" strokeWidth="1.5" />
        <path d="M5 7h4" stroke="#7ec8ff" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    </div>
  );
}

// ─── Humanize helpers ─────────────────────────────────────────────────────────

/** "order_items" → "Order Items", "BillingDocument" → "Billing Document" */
function humanize(s: string): string {
  if (!s) return "";
  // Split PascalCase: insert space before uppercase after lowercase/digit
  let spaced = s.replace(/([a-z0-9])([A-Z])/g, "$1 $2");
  // Split consecutive caps: "HTMLParser" → "HTML Parser"
  spaced = spaced.replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2");
  // Replace underscores
  spaced = spaced.replace(/_/g, " ");
  // Title case each word
  return spaced.replace(/\b\w/g, c => c.toUpperCase());
}

/** Format a number nicely */
function fmt(n: number): string {
  return Number.isInteger(n) ? n.toLocaleString() : n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

// ─── Expandable records table ─────────────────────────────────────────────────

function RecordsTable({ records, maxCols = 5, label }: {
  records: Record<string, unknown>[];
  maxCols?: number;
  label?: string;
}) {
  const [expanded, setExpanded] = useState(false);
  if (!records.length) return null;

  const cols = Object.keys(records[0]).slice(0, maxCols);
  const PREVIEW_ROWS = 3;
  const hasMore = records.length > PREVIEW_ROWS;
  const visibleRows = expanded ? records : records.slice(0, PREVIEW_ROWS);

  return (
    <div style={{ marginTop: 6, minWidth: 0 }}>
      {label && (
        <div style={{ fontSize: 12, color: D.muted, marginBottom: 4 }}>{label}</div>
      )}
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12, color: D.text }}>
          <thead>
            <tr>
              {cols.map((c, i) => (
                <th key={c} style={{
                  textAlign: "left", padding: "5px 8px",
                  borderBottom: `1px solid ${D.border}`,
                  color: i === 0 ? "#93c5fd" : D.muted,
                  fontWeight: 600, whiteSpace: "nowrap", background: D.surface,
                  fontSize: 11, letterSpacing: "0.02em",
                }}>{humanize(c)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visibleRows.map((row, i) => (
              <tr key={i} style={{ borderBottom: `1px solid ${D.surf2}` }}>
                {cols.map((c, j) => (
                  <td key={c} style={{
                    padding: "5px 8px",
                    fontFamily: j === 0 ? "monospace" : "inherit",
                    fontWeight: j === 0 ? 600 : 400,
                    color: j === 0 ? "#93c5fd" : D.text,
                    whiteSpace: "nowrap",
                    fontSize: 12,
                  }}>
                    {String(row[c] ?? "—")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {hasMore && (
        <button
          onClick={() => setExpanded(!expanded)}
          style={{
            marginTop: 4, padding: "4px 10px", borderRadius: 6,
            background: D.surf2, border: `1px solid ${D.border}`,
            color: D.muted, fontSize: 11, fontWeight: 500,
            cursor: "pointer", display: "flex", alignItems: "center", gap: 4,
            fontFamily: "inherit",
          }}
        >
          {expanded ? (
            <><ChevronDown style={{ width: 12, height: 12 }} /> Show less</>
          ) : (
            <><ChevronRight style={{ width: 12, height: 12 }} /> Show all {records.length} rows</>
          )}
        </button>
      )}
    </div>
  );
}

// ─── Flow path visualization ──────────────────────────────────────────────────

function FlowPath({ steps }: { steps: string[] }) {
  if (!steps.length) return null;
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 0, flexWrap: "wrap",
      padding: "8px 0",
    }}>
      {steps.map((step, i) => (
        <span key={step} style={{ display: "flex", alignItems: "center", gap: 0 }}>
          <span style={{
            padding: "4px 10px", borderRadius: 6,
            background: D.surf2, color: "#93c5fd",
            fontWeight: 600, fontSize: 12, border: `1px solid ${D.border}`,
          }}>
            {humanize(step)}
          </span>
          {i < steps.length - 1 && (
            <span style={{ color: D.dim, fontSize: 14, padding: "0 4px" }}> → </span>
          )}
        </span>
      ))}
    </div>
  );
}

// ─── Supporting data card ─────────────────────────────────────────────────────
// Replaces the old debug-style ExecResultCard + QueryCard.
// Shows only what helps the user understand the answer.

function SupportingData({ exec }: { exec: Execution }) {
  if (exec.status === "error" || !exec.result) return null;
  const r = exec.result;

  const card: React.CSSProperties = {
    marginTop: 10, border: `1px solid ${D.border}`, borderRadius: 10,
    overflow: "hidden", minWidth: 0, background: D.bg,
  };

  // ── Traverse ──
  if (r.type === "traverse") {
    const tr = r as TraverseResult;
    const recordCount = tr.target_record_count ?? tr.target_records.length;
    const showPath = tr.path.length > 2; // only show flow for 3+ node paths
    return (
      <div style={card}>
        <div style={{ padding: "10px 14px" }}>
          {showPath && (
            <>
              <div style={{ fontSize: 12, color: D.muted, marginBottom: 2 }}>
                How they're connected
              </div>
              <FlowPath steps={tr.path} />
            </>
          )}
          {recordCount > 0 && (
            <RecordsTable
              records={tr.target_records as Record<string, unknown>[]}
              label={`${fmt(recordCount)} ${humanize(tr.target_entity).toLowerCase()} record${recordCount !== 1 ? "s" : ""} found`}
            />
          )}
        </div>
      </div>
    );
  }

  // ── Lookup ──
  if (r.type === "lookup") {
    const lr = r as LookupResult;
    const rows = lr.record ? [lr.record] : lr.records;
    if (!rows.length) return null;
    const total = lr.record_count ?? rows.length;
    return (
      <div style={card}>
        <div style={{ padding: "10px 14px" }}>
          <RecordsTable
            records={rows as Record<string, unknown>[]}
            label={total > rows.length ? `Showing ${rows.length} of ${fmt(total)} records` : undefined}
          />
          {lr.connected_entities.length > 0 && (
            <div style={{ fontSize: 11, color: D.dim, marginTop: 6 }}>
              Related to: {lr.connected_entities.slice(0, 4).map(humanize).join(", ")}
            </div>
          )}
        </div>
      </div>
    );
  }

  // ── Filter ──
  if (r.type === "filter") {
    const fr = r as FilterResult;
    if (!fr.records.length) return null;
    const criteria = fr.filters_applied
      .map(f => `${humanize(f.field)} ${f.operator} ${f.value}`)
      .join(", ");
    return (
      <div style={card}>
        <div style={{ padding: "10px 14px" }}>
          <RecordsTable
            records={fr.records as Record<string, unknown>[]}
            label={`${fmt(fr.record_count)} record${fr.record_count !== 1 ? "s" : ""} matched${criteria ? ` (${criteria})` : ""}`}
          />
        </div>
      </div>
    );
  }

  // ── Aggregate ──
  if (r.type === "aggregate") {
    const ar = r as AggregateResult;
    const metricLabel = ar.metric === "count" ? "Total" :
                        ar.metric === "avg"   ? "Average" :
                        humanize(ar.metric);
    const fieldLabel = ar.field ? humanize(ar.field) : ar.entity ? humanize(ar.entity) : "";

    return (
      <div style={card}>
        <div style={{ padding: "12px 14px" }}>
          {ar.value !== undefined && ar.value !== null && (
            <>
              <div style={{ fontSize: 11, color: D.muted, marginBottom: 2 }}>
                {metricLabel}{fieldLabel ? ` — ${fieldLabel}` : ""}
              </div>
              <div style={{
                fontSize: 28, fontWeight: 700, color: "#34d399",
                letterSpacing: "-0.02em", lineHeight: 1.2,
              }}>
                {fmt(ar.value)}
              </div>
              {ar.sample_size != null && (
                <div style={{ fontSize: 11, color: D.dim, marginTop: 4 }}>
                  Based on {fmt(ar.sample_size)} records
                </div>
              )}
            </>
          )}
          {ar.rows && ar.rows.length > 0 && (
            <RecordsTable
              records={ar.rows as Record<string, unknown>[]}
              label={ar.value == null ? `${metricLabel}${fieldLabel ? ` — ${fieldLabel}` : ""}` : undefined}
            />
          )}
          {ar.records && ar.records.length > 0 && (
            <RecordsTable
              records={ar.records as Record<string, unknown>[]}
              label={
                ar.metadata?.filter_applied
                  ? `Records matching ${metricLabel.toLowerCase()}${fieldLabel ? ` of ${fieldLabel}` : ""}`
                  : "Records used for this aggregation"
              }
            />
          )}
        </div>
      </div>
    );
  }

  // ── Path ──
  if (r.type === "path") {
    const pr = r as PathResult;
    const entities = Object.entries(pr.entity_records).filter(([, recs]) => recs.length > 0);
    return (
      <div style={card}>
        <div style={{ padding: "10px 14px" }}>
          <div style={{ fontSize: 12, color: D.muted, marginBottom: 2 }}>
            Data flow
          </div>
          <FlowPath steps={pr.sequence} />
          {entities.map(([entity, recs]) => (
            <RecordsTable
              key={entity}
              records={recs}
              maxCols={4}
              label={humanize(entity)}
            />
          ))}
        </div>
      </div>
    );
  }

  // ── Anomaly ──
  if (r.type === "anomaly") {
    const anr = r as AnomalyResult;
    if (anr.flagged_count === 0) return null;

    return (
      <div style={{ ...card, border: "1px solid #3a1515" }}>
        <div style={{ padding: "10px 14px" }}>
          <div style={{ fontSize: 12, color: "#fc8080", fontWeight: 600, marginBottom: 8 }}>
            {anr.flagged_count} issue{anr.flagged_count !== 1 ? "s" : ""} found
            <span style={{ fontWeight: 400, color: D.muted, marginLeft: 6 }}>
              out of {fmt(anr.checked)} checked
            </span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {anr.flagged.slice(0, 5).map((item, i) => (
              <div key={i} style={{
                fontSize: 12, padding: "8px 10px", borderRadius: 6,
                background: "#150505", border: "1px solid #3a1010",
              }}>
                <div style={{ color: "#fc8080", marginBottom: 3 }}>{item.issue}</div>
                <div style={{
                  fontFamily: "monospace", color: D.dim, fontSize: 11,
                  overflowWrap: "anywhere", wordBreak: "break-word",
                }}>
                  {Object.entries(item.record).slice(0, 4).map(([k, v]) => `${humanize(k)}: ${v}`).join("  ·  ")}
                </div>
              </div>
            ))}
          </div>
          {anr.flagged_count > 5 && (
            <div style={{ fontSize: 11, color: D.muted, marginTop: 6 }}>
              + {anr.flagged_count - 5} more issue{anr.flagged_count - 5 !== 1 ? "s" : ""}
            </div>
          )}
        </div>
      </div>
    );
  }

  return null;
}

// ─── Fallback summary ─────────────────────────────────────────────────────────

function _summarize(exec?: Execution): string {
  if (!exec) return "Done.";
  if (exec.status === "error") return `Something went wrong: ${exec.error ?? "unknown error"}`;
  const r = exec.result;
  if (!r) return exec.status === "empty" ? "I couldn't find any matching records." : "Done.";

  if (r.type === "lookup") {
    const lr = r as LookupResult;
    if (exec.status === "empty") return `I couldn't find any **${humanize(lr.entity)}** records matching that.`;
    if (lr.id && lr.record) return `Here's the **${humanize(lr.entity)}** record for **${lr.id}**.`;
    const count = lr.record_count ?? lr.records.length;
    return `There ${count === 1 ? "is" : "are"} **${fmt(count)}** **${humanize(lr.entity)}** record${count !== 1 ? "s" : ""}.`;
  }
  if (r.type === "traverse") {
    const tr = r as TraverseResult;
    if (exec.status === "empty") return `I couldn't find a connection between **${humanize(tr.start_entity)}** and **${humanize(tr.target_entity)}**.`;
    const count = tr.target_record_count ?? tr.target_records.length;
    return `**${humanize(tr.start_entity)}** connects to **${humanize(tr.target_entity)}** through ${tr.path_length} step${tr.path_length !== 1 ? "s" : ""}. Found **${fmt(count)}** record${count !== 1 ? "s" : ""}.`;
  }
  if (r.type === "filter") {
    const fr = r as FilterResult;
    if (exec.status === "empty") return `No **${humanize(fr.entity)}** records matched those criteria.`;
    return `Found **${fmt(fr.record_count)}** matching **${humanize(fr.entity)}** record${fr.record_count !== 1 ? "s" : ""}.`;
  }
  if (r.type === "aggregate") {
    const ar = r as AggregateResult;
    if (ar.value != null) return `The ${ar.metric} is **${fmt(ar.value)}**.`;
    return "Here are the results.";
  }
  if (r.type === "anomaly") {
    const anr = r as AnomalyResult;
    if (anr.flagged_count === 0) return `Everything looks good — checked ${fmt(anr.checked)} records and found no issues.`;
    return `Found **${anr.flagged_count}** issue${anr.flagged_count !== 1 ? "s" : ""}** across ${fmt(anr.checked)} records.`;
  }
  return "Here are your results.";
}

// ─── ChatPanel ────────────────────────────────────────────────────────────────

interface ChatPanelProps {
  isMinimized?: boolean;
  onToggle?: () => void;
  /** Called whenever a query result arrives; passes the entity names to highlight in the graph. */
  onHighlight?: (entities: string[]) => void;
}

// ─── Entity extraction from execution result ──────────────────────────────────

function extractHighlightedEntities(exec: Execution): string[] {
  if (!exec?.result) return [];
  const r = exec.result;
  if (r.type === "lookup")    return [(r as LookupResult).entity].filter(Boolean);
  if (r.type === "traverse") {
    const tr = r as TraverseResult;
    return tr.path?.length ? tr.path : [tr.start_entity, tr.target_entity].filter(Boolean);
  }
  if (r.type === "filter")    return [(r as FilterResult).entity].filter(Boolean);
  if (r.type === "aggregate") return [(r as AggregateResult).entity ?? ""].filter(Boolean);
  if (r.type === "path")      return (r as PathResult).sequence ?? [];
  if (r.type === "anomaly") {
    const anr = r as AnomalyResult;
    return [anr.start_entity, anr.target_entity].filter(Boolean) as string[];
  }
  return [];
}

export function ChatPanel({ isMinimized = false, onToggle, onHighlight }: ChatPanelProps) {
  const [messages, setMessages] = useState<Message[]>(() => {
    const stored = loadMessages();
    return stored.length > 0 ? stored : [GREETING];
  });
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const nextId = useRef(messages.length + 1);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Persist to localStorage on every message change
  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(messages));
  }, [messages]);

  // Auto-scroll to newest message
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  async function handleSend() {
    const text = input.trim();
    if (!text || sending) return;

    setMessages(prev => [...prev, { id: nextId.current++, role: "user", content: text }]);
    setInput("");
    setSending(true);

    try {
      const resp = await fetch(apiUrl("/query/plan"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: text }),
      });

      let content: string;
      let plan: GraphQueryPlan | undefined;
      let execution: Execution | undefined;

      if (!resp.ok) {
        content = `Sorry, I couldn't process that — the server returned an error (${resp.status}).`;
      } else {
        const data = await resp.json();
        if (data.plan) plan = data.plan as GraphQueryPlan;
        if (data.execution) execution = data.execution as Execution;
        content = data.answer ?? _summarize(execution);
      }

      const assistantMsg: Message = { id: nextId.current++, role: "assistant", content, plan, execution };
      setMessages(prev => [...prev, assistantMsg]);

      // Highlight the entities involved in this query result in the graph
      if (execution && onHighlight) {
        const entities = extractHighlightedEntities(execution);
        if (entities.length > 0) onHighlight(entities);
      }
    } catch (err) {
      setMessages(prev => [...prev, {
        id: nextId.current++,
        role: "assistant",
        content: `I can't reach the server right now. Make sure the backend is running and try again.`,
      }]);
    } finally {
      setSending(false);
    }
  }

  function renderContent(text: string) {
    return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
      part.startsWith("**") && part.endsWith("**")
        ? <strong key={i} style={{ color: D.text, fontWeight: 600 }}>{part.slice(2, -2)}</strong>
        : part
    );
  }

  // ── Minimized: icon-only vertical strip ─────
  if (isMinimized) {
    return (
      <div style={{
        display: "flex", flexDirection: "column", height: "100%",
        background: D.surface, borderLeft: `1px solid ${D.border}`,
        alignItems: "center", paddingTop: 12, overflow: "hidden",
        minWidth: 0,
      }}>
        <button
          onClick={onToggle}
          title="Expand chat"
          style={{
            width: 28, height: 28, borderRadius: 7,
            background: D.surf2, border: `1px solid ${D.border}`,
            color: D.muted, cursor: "pointer",
            display: "flex", alignItems: "center", justifyContent: "center",
            flexShrink: 0,
          }}
        >
          <ChevronLeft style={{ width: 14, height: 14 }} />
        </button>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", background: D.bg, overflow: "hidden", minWidth: 0 }}>

      {/* ── Header ────────────────────────────── */}
      <div style={{
        padding: "13px 16px", background: D.surface,
        borderBottom: `1px solid ${D.border}`, flexShrink: 0,
        display: "flex", alignItems: "center", gap: 10,
      }}>
        <AgentAvatar />
        <div>
          <div style={{ fontSize: 14, fontWeight: 600, color: D.text, lineHeight: 1.2 }}>Dodge AI</div>
          <div style={{ fontSize: 11, color: D.muted, marginTop: 1 }}>Graph Intelligence</div>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{
            width: 6, height: 6, borderRadius: "50%", background: "#22c55e",
            boxShadow: "0 0 6px #22c55e80",
          }} />
          <span style={{ fontSize: 11, color: D.muted }}>Live</span>
          <button
            onClick={onToggle}
            title="Minimize chat"
            style={{
              width: 24, height: 24, borderRadius: 6,
              background: "transparent", border: `1px solid ${D.border}`,
              color: D.muted, cursor: "pointer",
              display: "flex", alignItems: "center", justifyContent: "center",
              flexShrink: 0, transition: "background 0.15s ease",
            }}
            onMouseEnter={(e) => (e.currentTarget.style.background = D.surf2)}
            onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
          >
            <PanelRightClose style={{ width: 13, height: 13 }} />
          </button>
        </div>
      </div>

      {/* ── Messages ──────────────────────────── */}
      <div style={{ flex: 1, minHeight: 0, overflowY: "auto", overflowX: "hidden", minWidth: 0 }}>
        <div style={{
          padding: "20px 14px", display: "flex", flexDirection: "column", gap: 22,
          minWidth: 0,
        }}>
          {messages.map((msg) => (
            <div key={msg.id} style={{ minWidth: 0 }}>
              {msg.role === "assistant" ? (
                /* Assistant */
                <div style={{ display: "flex", gap: 10, minWidth: 0 }}>
                  <AgentAvatar />
                  <div style={{
                    flex: 1, minWidth: 0, paddingTop: 2,
                    overflowWrap: "anywhere", wordBreak: "break-word",
                  }}>
                    {/* Answer text — always first, always prominent */}
                    <div style={{
                      fontSize: 14, color: "#c5d5ea", lineHeight: 1.65,
                      whiteSpace: "pre-wrap",
                    }}>
                      {renderContent(msg.content)}
                    </div>

                    {/* Supporting data — clean, collapsible, no debug labels */}
                    {msg.execution && <SupportingData exec={msg.execution} />}
                  </div>
                </div>
              ) : (
                /* User */
                <div style={{ display: "flex", justifyContent: "flex-end", minWidth: 0 }}>
                  <div style={{
                    maxWidth: "78%",
                    background: "#1a3a6a",
                    color: "#c5d9f5",
                    borderRadius: "16px 16px 4px 16px",
                    padding: "10px 14px",
                    fontSize: 14, lineHeight: 1.6,
                    border: "1px solid #1e4a8a",
                    overflowWrap: "anywhere",
                    wordBreak: "break-word",
                    whiteSpace: "pre-wrap",
                  }}>
                    {msg.content}
                  </div>
                </div>
              )}
            </div>
          ))}

          {/* Loading */}
          {sending && (
            <div style={{ display: "flex", gap: 10 }}>
              <AgentAvatar />
              <div style={{
                display: "flex", alignItems: "center", gap: 8,
                color: D.muted, fontSize: 13, paddingTop: 2,
              }}>
                <Loader2 style={{
                  width: 13, height: 13,
                  animation: "spin 0.8s linear infinite",
                  color: "#3a7bff",
                }} />
                Thinking...
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      {/* ── Input ─────────────────────────────── */}
      <div style={{
        flexShrink: 0, padding: "10px 12px",
        background: D.surface, borderTop: `1px solid ${D.border}`,
      }}>
        {/* Status line */}
        <div style={{
          display: "flex", alignItems: "center", gap: 6,
          marginBottom: 8, paddingLeft: 2,
        }}>
          <div style={{
            width: 6, height: 6, borderRadius: "50%",
            background: sending ? "#f59e0b" : "#22c55e",
            flexShrink: 0,
            boxShadow: sending ? "0 0 6px #f59e0b60" : "0 0 6px #22c55e50",
          }} />
          <span style={{ fontSize: 11, color: D.muted }}>
            {sending ? "Analyzing..." : "Ask anything about your data"}
          </span>
        </div>

        {/* Textarea + send */}
        <div style={{
          border: `1px solid ${D.border}`, borderRadius: 10,
          overflow: "hidden", background: D.bg,
        }}>
          <div style={{ display: "flex", alignItems: "flex-end", padding: "8px 8px 8px 12px" }}>
            <textarea
              className="chat-textarea"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); }
              }}
              placeholder="Ask about orders, deliveries, invoices..."
              disabled={sending}
              rows={2}
              style={{
                flex: 1, background: "transparent",
                fontSize: 14, color: D.text,
                border: "none", outline: "none", resize: "none",
                fontFamily: "inherit", lineHeight: 1.5, padding: "3px 0",
              }}
            />
            <button
              onClick={handleSend}
              disabled={sending || !input.trim()}
              style={{
                padding: "8px 16px", borderRadius: 8,
                background: sending || !input.trim() ? D.surf2 : "#1e4a9e",
                color: sending || !input.trim() ? D.dim : "#c5d9f5",
                border: "none", fontSize: 13, fontWeight: 600,
                fontFamily: "inherit",
                cursor: sending || !input.trim() ? "not-allowed" : "pointer",
                flexShrink: 0, transition: "all 0.15s ease",
                letterSpacing: "0.01em",
              }}
            >
              Send
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
