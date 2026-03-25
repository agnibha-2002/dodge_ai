import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Table2, Link2, ChevronLeft, ChevronRight } from "lucide-react";
import type { ApiNodeDetail, RecordsResponse } from "./types";

const API_BASE = "http://localhost:8000";
const RECORD_FIELDS_MAX = 10;

type InspectorMode = "overview" | "record";

interface InspectorCardProps {
  detail: ApiNodeDetail | null;
  loading: boolean;
  error: string | null;
  position: { x: number; y: number } | null;
  containerWidth: number;
  containerHeight: number;
  onClose: () => void;
  onViewRecords?: (nodeName: string) => void;
}

export function InspectorCard({
  detail,
  loading,
  error,
  position,
  containerWidth,
  containerHeight,
  onViewRecords,
}: InspectorCardProps) {
  const [mode, setMode] = useState<InspectorMode>("overview");
  const [recordData, setRecordData] = useState<RecordsResponse | null>(null);
  const [recordLoading, setRecordLoading] = useState(false);
  const [recordIdx, setRecordIdx] = useState(0);
  const prevNodeRef = useRef<string | null>(null);

  // Lazy-fetch records only when Record mode is activated
  const fetchRecords = useCallback(async (nodeName: string) => {
    setRecordLoading(true);
    try {
      const resp = await fetch(
        `${API_BASE}/nodes/${encodeURIComponent(nodeName)}/records?limit=5`
      );
      if (resp.ok) {
        const data: RecordsResponse = await resp.json();
        setRecordData(data);
      }
    } catch {
      // silent — record view is best-effort
    } finally {
      setRecordLoading(false);
    }
  }, []);

  // Reset state when node changes
  useEffect(() => {
    if (detail && detail.name !== prevNodeRef.current) {
      prevNodeRef.current = detail.name;
      setMode("overview");
      setRecordData(null);
      setRecordIdx(0);
    }
    if (!detail) {
      prevNodeRef.current = null;
      setRecordData(null);
      setRecordIdx(0);
    }
  }, [detail]);

  // Fetch records when switching to Record mode
  useEffect(() => {
    if (mode === "record" && detail && !recordData && !recordLoading) {
      fetchRecords(detail.name);
    }
  }, [mode, detail, recordData, recordLoading, fetchRecords]);

  if (!position) return null;

  const CARD_W = 320;
  const CARD_H_EST = 460;
  const OFFSET = 24;

  let x = position.x + OFFSET;
  let y = position.y - 48;
  if (x + CARD_W > containerWidth - 16) x = position.x - CARD_W - OFFSET;
  if (y + CARD_H_EST > containerHeight - 16) y = containerHeight - CARD_H_EST - 16;
  if (y < 16) y = 16;
  if (x < 16) x = 16;

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
        {/* Loading */}
        {loading && (
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: "48px 0", gap: 8, color: "#9ca3af" }}>
            <Loader2 style={{ width: 16, height: 16, animation: "spin 0.8s linear infinite", color: "#3b82f6" }} />
            <span style={{ fontSize: 13 }}>Loading...</span>
          </div>
        )}

        {/* Error */}
        {error && !loading && (
          <div style={{ padding: "32px 20px", textAlign: "center" }}>
            <p style={{ fontSize: 13, color: "#ef4444", fontWeight: 600, margin: 0 }}>Failed to load</p>
            <p style={{ fontSize: 12, color: "#9ca3af", marginTop: 6 }}>{error}</p>
          </div>
        )}

        {/* Detail content */}
        {detail && !loading && (
          <div>
            {/* Title + source table */}
            <div style={{ padding: "16px 20px 0" }}>
              <h3 style={{
                fontSize: 16,
                fontWeight: 700,
                color: "#111827",
                margin: 0,
                lineHeight: 1.3,
              }}>
                {detail.name}
              </h3>
              {detail.source_table && (
                <p style={{
                  fontSize: 11,
                  color: "#9ca3af",
                  margin: "3px 0 0",
                  fontFamily: "'SF Mono', 'Fira Code', monospace",
                }}>
                  {detail.source_table}
                </p>
              )}
            </div>

            {/* ── Mode toggle ────────────────────── */}
            <div style={{
              display: "flex",
              margin: "12px 20px 0",
              background: "#f3f4f6",
              borderRadius: 8,
              padding: 3,
              gap: 2,
            }}>
              <ModeTab
                label="Overview"
                active={mode === "overview"}
                onClick={() => setMode("overview")}
              />
              <ModeTab
                label="Record"
                active={mode === "record"}
                onClick={() => setMode("record")}
              />
            </div>

            {/* ── Mode content ───────────────────── */}
            <div style={{ padding: "12px 20px 14px" }}>
              {mode === "overview" ? (
                <OverviewPane
                  detail={detail}
                  onViewRecords={onViewRecords}
                />
              ) : (
                <RecordPane
                  detail={detail}
                  data={recordData}
                  loading={recordLoading}
                  recordIdx={recordIdx}
                  onChangeIdx={setRecordIdx}
                />
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────
// Mode toggle tab
// ─────────────────────────────────────────────

function ModeTab({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        flex: 1,
        padding: "6px 0",
        borderRadius: 6,
        border: "none",
        background: active ? "#ffffff" : "transparent",
        boxShadow: active ? "0 1px 3px rgba(0,0,0,0.08)" : "none",
        color: active ? "#111827" : "#6b7280",
        fontSize: 12,
        fontWeight: 600,
        fontFamily: "inherit",
        cursor: "pointer",
        transition: "all 0.15s",
      }}
    >
      {label}
    </button>
  );
}

// ─────────────────────────────────────────────
// Overview pane (schema-level)
// ─────────────────────────────────────────────

function OverviewPane({
  detail,
  onViewRecords,
}: {
  detail: ApiNodeDetail;
  onViewRecords?: (nodeName: string) => void;
}) {
  // Build key-value entries from schema attributes
  const entries: [string, string][] = [];

  const pks = Array.isArray(detail.primary_key) ? detail.primary_key : [detail.primary_key];
  if (pks.length > 0) {
    entries.push(["Primary Key", pks.join(", ")]);
  }

  if (detail.record_count != null) {
    entries.push(["Records", detail.record_count.toLocaleString()]);
  }

  entries.push(["Connections", String(detail.connected_node_names.length)]);

  // Attributes as column listing
  const totalEdges = detail.outgoing_edges.length + detail.incoming_edges.length;
  if (totalEdges > 0) {
    entries.push(["Edges", String(totalEdges)]);
  }

  for (const attr of detail.attributes) {
    const colonIdx = attr.indexOf(":");
    const eqIdx = attr.indexOf("=");
    if (colonIdx > 0 && (eqIdx < 0 || colonIdx < eqIdx)) {
      entries.push([attr.slice(0, colonIdx).trim(), attr.slice(colonIdx + 1).trim()]);
    } else if (eqIdx > 0) {
      entries.push([attr.slice(0, eqIdx).trim(), attr.slice(eqIdx + 1).trim()]);
    } else {
      entries.push([attr, ""]);
    }
  }

  const MAX_FIELDS = 14;
  const visible = entries.slice(0, MAX_FIELDS);
  const hiddenCount = entries.length - MAX_FIELDS;

  return (
    <>
      <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
        {visible.map(([key, value], i) => (
          <KVRow key={i} label={key} value={value} isLast={i === visible.length - 1} />
        ))}
      </div>

      {hiddenCount > 0 && (
        <p style={{ fontSize: 11, color: "#9ca3af", fontStyle: "italic", margin: "6px 0 0" }}>
          +{hiddenCount} more fields
        </p>
      )}

      {/* Connected entities */}
      {detail.connected_node_names.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 5, marginBottom: 6 }}>
            <Link2 style={{ width: 11, height: 11, color: "#9ca3af" }} />
            <span style={{ fontSize: 10, fontWeight: 600, color: "#9ca3af", textTransform: "uppercase", letterSpacing: "0.05em" }}>
              Related Entities
            </span>
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {detail.connected_node_names.slice(0, 6).map((name) => (
              <span
                key={name}
                style={{
                  fontSize: 11,
                  padding: "3px 8px",
                  borderRadius: 6,
                  background: "#f3f4f6",
                  color: "#374151",
                  fontWeight: 500,
                }}
              >
                {name}
              </span>
            ))}
            {detail.connected_node_names.length > 6 && (
              <span style={{ fontSize: 11, padding: "3px 4px", color: "#9ca3af" }}>
                +{detail.connected_node_names.length - 6}
              </span>
            )}
          </div>
        </div>
      )}

      {/* View Records button */}
      {detail.record_count != null && detail.record_count > 0 && onViewRecords && (
        <button
          onClick={() => onViewRecords(detail.name)}
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 8,
            width: "100%",
            marginTop: 14,
            padding: "10px 0",
            borderRadius: 8,
            border: "1px solid #e5e7eb",
            background: "#f9fafb",
            color: "#374151",
            fontSize: 13,
            fontWeight: 600,
            fontFamily: "inherit",
            cursor: "pointer",
            transition: "all 0.15s",
          }}
          onMouseEnter={(e) => {
            (e.currentTarget as HTMLElement).style.background = "#f3f4f6";
            (e.currentTarget as HTMLElement).style.borderColor = "#d1d5db";
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLElement).style.background = "#f9fafb";
            (e.currentTarget as HTMLElement).style.borderColor = "#e5e7eb";
          }}
        >
          <Table2 style={{ width: 14, height: 14 }} />
          View All Records
          <span style={{ fontSize: 11, fontWeight: 500, color: "#9ca3af", marginLeft: 2 }}>
            ({detail.record_count.toLocaleString()})
          </span>
        </button>
      )}
    </>
  );
}

// ─────────────────────────────────────────────
// Record pane (row-level — single record)
// ─────────────────────────────────────────────

function RecordPane({
  detail,
  data,
  loading,
  recordIdx,
  onChangeIdx,
}: {
  detail: ApiNodeDetail;
  data: RecordsResponse | null;
  loading: boolean;
  recordIdx: number;
  onChangeIdx: (idx: number) => void;
}) {
  if (loading) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: "32px 0", gap: 8, color: "#9ca3af" }}>
        <Loader2 style={{ width: 14, height: 14, animation: "spin 0.8s linear infinite", color: "#3b82f6" }} />
        <span style={{ fontSize: 12 }}>Loading record...</span>
      </div>
    );
  }

  if (!data || data.records.length === 0) {
    return (
      <div style={{ padding: "24px 0", textAlign: "center", color: "#9ca3af", fontSize: 12 }}>
        No records available for this entity.
      </div>
    );
  }

  const safeIdx = Math.min(recordIdx, data.records.length - 1);
  const record = data.records[safeIdx];
  const pks = Array.isArray(data.primary_key) ? data.primary_key : [data.primary_key];
  const pkSet = new Set(pks);

  // Build key-value entries: primary keys first, then other fields
  // Filter out null/empty values, cap at RECORD_FIELDS_MAX
  const entries: [string, unknown, boolean][] = [];

  // Primary key fields first
  for (const pk of pks) {
    if (record[pk] != null && record[pk] !== "") {
      entries.push([pk, record[pk], true]);
    }
  }

  // Other fields
  for (const col of data.columns) {
    if (pkSet.has(col)) continue;
    const val = record[col];
    if (val === null || val === undefined || val === "") continue;
    entries.push([col, val, false]);
    if (entries.length >= RECORD_FIELDS_MAX) break;
  }

  return (
    <>
      {/* Record navigator */}
      <div style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        marginBottom: 10,
        paddingBottom: 8,
        borderBottom: "1px solid #f3f4f6",
      }}>
        <span style={{ fontSize: 11, color: "#9ca3af", fontWeight: 500 }}>
          Record {safeIdx + 1} of {data.records.length}
        </span>
        <div style={{ display: "flex", gap: 3 }}>
          <NavBtn
            disabled={safeIdx === 0}
            onClick={() => onChangeIdx(safeIdx - 1)}
          >
            <ChevronLeft style={{ width: 12, height: 12 }} />
          </NavBtn>
          <NavBtn
            disabled={safeIdx >= data.records.length - 1}
            onClick={() => onChangeIdx(safeIdx + 1)}
          >
            <ChevronRight style={{ width: 12, height: 12 }} />
          </NavBtn>
        </div>
      </div>

      {/* Key-value list */}
      <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
        {entries.map(([key, value, isPk], i) => (
          <div
            key={i}
            style={{
              display: "flex",
              gap: 8,
              padding: "5px 0",
              borderBottom: i < entries.length - 1 ? "1px solid #f3f4f6" : "none",
              fontSize: 13,
              lineHeight: 1.5,
            }}
          >
            <span style={{
              fontWeight: 600,
              color: isPk ? "#1e40af" : "#111827",
              minWidth: 0,
              flexShrink: 0,
              whiteSpace: "nowrap",
              fontSize: 12,
            }}>
              {formatColumnLabel(String(key))}:
            </span>
            <span style={{
              color: "#374151",
              wordBreak: "break-word",
              fontWeight: 400,
              fontFamily: isPk || isNumericish(value) ? "'SF Mono', 'Fira Code', monospace" : "inherit",
              fontSize: isPk ? 12 : 13,
            }}>
              {formatDisplayValue(value)}
            </span>
          </div>
        ))}
      </div>

      {/* Connections count */}
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
        <Link2 style={{ width: 12, height: 12, color: "#9ca3af" }} />
        <span style={{ fontSize: 12, color: "#6b7280" }}>
          <strong style={{ color: "#374151", fontWeight: 600 }}>
            {detail.connected_node_names.length}
          </strong>
          {" "}connected {detail.connected_node_names.length === 1 ? "entity" : "entities"}
        </span>
      </div>
    </>
  );
}

// ─────────────────────────────────────────────
// Shared components
// ─────────────────────────────────────────────

function KVRow({ label, value, isLast }: { label: string; value: string; isLast: boolean }) {
  return (
    <div
      style={{
        display: "flex",
        gap: 8,
        padding: "5px 0",
        borderBottom: isLast ? "none" : "1px solid #f3f4f6",
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
      }}>
        {label}:
      </span>
      <span style={{
        color: "#374151",
        wordBreak: "break-word",
        fontWeight: 400,
      }}>
        {value || <span style={{ color: "#d1d5db" }}>&mdash;</span>}
      </span>
    </div>
  );
}

function NavBtn({
  disabled,
  onClick,
  children,
}: {
  disabled: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        width: 24,
        height: 24,
        borderRadius: 6,
        border: "1px solid #e5e7eb",
        background: "#ffffff",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.35 : 1,
        color: "#374151",
        padding: 0,
        transition: "all 0.1s",
      }}
    >
      {children}
    </button>
  );
}

// ─────────────────────────────────────────────
// Formatting helpers
// ─────────────────────────────────────────────

function formatColumnLabel(col: string): string {
  return col
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatDisplayValue(val: unknown): string {
  if (val === null || val === undefined) return "\u2014";
  if (typeof val === "boolean") return val ? "Yes" : "No";
  if (typeof val === "number") return val.toLocaleString();
  const s = String(val);
  // Truncate ISO dates for readability
  if (/^\d{4}-\d{2}-\d{2}T/.test(s)) return s.slice(0, 10);
  return s;
}

function isNumericish(val: unknown): boolean {
  return typeof val === "number" || (typeof val === "string" && /^\d+$/.test(val));
}
