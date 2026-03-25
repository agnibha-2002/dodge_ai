import { useCallback, useEffect, useRef, useState } from "react";
import { X, Search, ChevronLeft, ChevronRight, Loader2, Database } from "lucide-react";
import type { RecordsResponse } from "./types";
import { apiUrl } from "./api";
const PAGE_SIZE = 20;

interface RecordsModalProps {
  nodeName: string;
  recordCount: number | null;
  onClose: () => void;
}

export function RecordsModal({ nodeName, recordCount, onClose }: RecordsModalProps) {
  const [data, setData] = useState<RecordsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const backdropRef = useRef<HTMLDivElement>(null);

  // Debounce search input
  useEffect(() => {
    const t = setTimeout(() => {
      setDebouncedSearch(search);
      setOffset(0);
    }, 300);
    return () => clearTimeout(t);
  }, [search]);

  // Fetch records
  const fetchRecords = useCallback(async (currentOffset: number, searchQuery: string) => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String(currentOffset),
      });
      if (searchQuery) params.set("search", searchQuery);

      const resp = await fetch(
        apiUrl(`/nodes/${encodeURIComponent(nodeName)}/records?${params}`)
      );
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const result: RecordsResponse = await resp.json();
      setData(result);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, [nodeName]);

  useEffect(() => {
    fetchRecords(offset, debouncedSearch);
  }, [offset, debouncedSearch, fetchRecords]);

  // Close on backdrop click
  const handleBackdropClick = useCallback((e: React.MouseEvent) => {
    if (e.target === backdropRef.current) onClose();
  }, [onClose]);

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const totalPages = data ? Math.ceil(data.total_count / PAGE_SIZE) : 0;
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;

  // Pick important columns to show (primary key first, then others, capped)
  const visibleColumns = data ? pickVisibleColumns(data) : [];

  return (
    <div
      ref={backdropRef}
      onClick={handleBackdropClick}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 50,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "rgba(0, 0, 0, 0.4)",
        backdropFilter: "blur(4px)",
      }}
    >
      <div style={{
        background: "#ffffff",
        borderRadius: 16,
        border: "1px solid #e5e7eb",
        boxShadow: "0 24px 48px rgba(0, 0, 0, 0.2)",
        width: "min(900px, 92vw)",
        maxHeight: "85vh",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
        animation: "inspector-in 0.2s cubic-bezier(0.16, 1, 0.3, 1)",
      }}>
        {/* Header */}
        <div style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          padding: "16px 20px",
          borderBottom: "1px solid #f3f4f6",
          flexShrink: 0,
        }}>
          <div style={{
            width: 32,
            height: 32,
            borderRadius: 8,
            background: "#f3f4f6",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}>
            <Database style={{ width: 16, height: 16, color: "#6b7280" }} />
          </div>
          <div style={{ flex: 1 }}>
            <h2 style={{ fontSize: 15, fontWeight: 700, color: "#111827", margin: 0 }}>
              {nodeName}
            </h2>
            <p style={{ fontSize: 12, color: "#9ca3af", margin: 0 }}>
              {data?.source_table ?? "Loading..."} &middot; {recordCount?.toLocaleString() ?? "?"} records
            </p>
          </div>
          <button
            onClick={onClose}
            style={{
              width: 32, height: 32, borderRadius: 8, border: "1px solid #e5e7eb",
              background: "#ffffff", display: "flex", alignItems: "center", justifyContent: "center",
              cursor: "pointer", color: "#6b7280", transition: "all 0.15s",
            }}
          >
            <X style={{ width: 16, height: 16 }} />
          </button>
        </div>

        {/* Search */}
        <div style={{ padding: "12px 20px", borderBottom: "1px solid #f3f4f6", flexShrink: 0 }}>
          <div style={{
            display: "flex", alignItems: "center", gap: 8,
            border: "1px solid #e5e7eb", borderRadius: 8,
            padding: "8px 12px", background: "#f9fafb",
          }}>
            <Search style={{ width: 14, height: 14, color: "#9ca3af", flexShrink: 0 }} />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search records..."
              style={{
                flex: 1, border: "none", outline: "none", background: "transparent",
                fontSize: 13, color: "#111827", fontFamily: "inherit",
              }}
            />
            {search && (
              <button
                onClick={() => setSearch("")}
                style={{
                  background: "none", border: "none", cursor: "pointer",
                  color: "#9ca3af", padding: 0, display: "flex",
                }}
              >
                <X style={{ width: 12, height: 12 }} />
              </button>
            )}
          </div>
        </div>

        {/* Table */}
        <div style={{ flex: 1, overflow: "auto", minHeight: 0 }}>
          {loading && !data && (
            <div style={{
              display: "flex", alignItems: "center", justifyContent: "center",
              padding: "60px 0", gap: 8, color: "#9ca3af",
            }}>
              <Loader2 style={{ width: 16, height: 16, animation: "spin 0.8s linear infinite", color: "#3b82f6" }} />
              <span style={{ fontSize: 13 }}>Loading records...</span>
            </div>
          )}

          {error && (
            <div style={{ padding: "40px 20px", textAlign: "center" }}>
              <p style={{ fontSize: 13, color: "#ef4444", fontWeight: 600 }}>Failed to load records</p>
              <p style={{ fontSize: 12, color: "#9ca3af", marginTop: 4 }}>{error}</p>
            </div>
          )}

          {data && !error && (
            <table style={{
              width: "100%",
              borderCollapse: "collapse",
              fontSize: 13,
            }}>
              <thead>
                <tr>
                  {visibleColumns.map((col) => (
                    <th
                      key={col}
                      style={{
                        position: "sticky",
                        top: 0,
                        background: "#f9fafb",
                        padding: "10px 14px",
                        textAlign: "left",
                        fontWeight: 600,
                        color: "#374151",
                        borderBottom: "2px solid #e5e7eb",
                        whiteSpace: "nowrap",
                        fontSize: 12,
                      }}
                    >
                      {formatColumnName(col)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.records.length === 0 && (
                  <tr>
                    <td
                      colSpan={visibleColumns.length}
                      style={{ padding: "32px 14px", textAlign: "center", color: "#9ca3af" }}
                    >
                      {debouncedSearch ? "No records match your search" : "No records available"}
                    </td>
                  </tr>
                )}
                {data.records.map((record, rowIdx) => (
                  <tr
                    key={rowIdx}
                    style={{
                      borderBottom: "1px solid #f3f4f6",
                      transition: "background 0.1s",
                    }}
                    onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = "#f9fafb"; }}
                    onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = "transparent"; }}
                  >
                    {visibleColumns.map((col) => {
                      const val = record[col];
                      const isPk = isPrimaryKey(col, data.primary_key);
                      return (
                        <td
                          key={col}
                          style={{
                            padding: "8px 14px",
                            color: isPk ? "#1e40af" : "#374151",
                            fontWeight: isPk ? 600 : 400,
                            fontFamily: isPk || isNumericish(val) ? "'SF Mono', 'Fira Code', monospace" : "inherit",
                            fontSize: isPk || isNumericish(val) ? 12 : 13,
                            whiteSpace: "nowrap",
                            maxWidth: 200,
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                          }}
                        >
                          {formatValue(val)}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Pagination footer */}
        {data && (
          <div style={{
            display: "flex", alignItems: "center", justifyContent: "space-between",
            padding: "12px 20px", borderTop: "1px solid #f3f4f6", flexShrink: 0,
            fontSize: 12, color: "#6b7280",
          }}>
            <span>
              Showing {data.records.length > 0 ? offset + 1 : 0}–{offset + data.records.length} of {data.total_count}
              {loading && <Loader2 style={{ width: 12, height: 12, animation: "spin 0.8s linear infinite", display: "inline-block", marginLeft: 6, verticalAlign: "middle", color: "#3b82f6" }} />}
            </span>
            <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
              <button
                onClick={() => setOffset((v) => Math.max(0, v - PAGE_SIZE))}
                disabled={offset === 0}
                style={{
                  width: 28, height: 28, borderRadius: 6, border: "1px solid #e5e7eb",
                  background: "#fff", display: "flex", alignItems: "center", justifyContent: "center",
                  cursor: offset === 0 ? "not-allowed" : "pointer",
                  opacity: offset === 0 ? 0.4 : 1, color: "#374151",
                }}
              >
                <ChevronLeft style={{ width: 14, height: 14 }} />
              </button>
              <span style={{ padding: "0 8px", fontWeight: 500, color: "#374151" }}>
                {currentPage} / {totalPages || 1}
              </span>
              <button
                onClick={() => setOffset((v) => v + PAGE_SIZE)}
                disabled={!data || offset + PAGE_SIZE >= data.total_count}
                style={{
                  width: 28, height: 28, borderRadius: 6, border: "1px solid #e5e7eb",
                  background: "#fff", display: "flex", alignItems: "center", justifyContent: "center",
                  cursor: (!data || offset + PAGE_SIZE >= data.total_count) ? "not-allowed" : "pointer",
                  opacity: (!data || offset + PAGE_SIZE >= data.total_count) ? 0.4 : 1, color: "#374151",
                }}
              >
                <ChevronRight style={{ width: 14, height: 14 }} />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────

function pickVisibleColumns(data: RecordsResponse): string[] {
  const pks = Array.isArray(data.primary_key) ? data.primary_key : [data.primary_key];
  const pkSet = new Set(pks);

  // Primary key columns first, then non-pk columns, capped at 8 total
  const pkCols = data.columns.filter((c) => pkSet.has(c));
  const otherCols = data.columns.filter((c) => !pkSet.has(c));
  return [...pkCols, ...otherCols].slice(0, 8);
}

function isPrimaryKey(col: string, pk: string | string[]): boolean {
  const pks = Array.isArray(pk) ? pk : [pk];
  return pks.includes(col);
}

function formatColumnName(col: string): string {
  return col
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatValue(val: unknown): string {
  if (val === null || val === undefined) return "\u2014";
  if (typeof val === "boolean") return val ? "Yes" : "No";
  if (typeof val === "number") return val.toLocaleString();
  return String(val);
}

function isNumericish(val: unknown): boolean {
  return typeof val === "number" || (typeof val === "string" && /^\d+$/.test(val));
}
