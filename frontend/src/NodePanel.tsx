import { useState } from "react";
import { ChevronDown, ChevronRight, Loader2 } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { BadgeVariant } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from "@/components/ui/collapsible";
import type { ApiEdgeDetail, ApiNodeDetail } from "./types";

// ─────────────────────────────────────────────
// Variant helpers
// ─────────────────────────────────────────────

const TYPE_VARIANT: Record<string, BadgeVariant> = {
  STRUCTURAL: "structural",
  FILTERED: "filtered",
  DERIVED: "derived",
};

const CONF_VARIANT: Record<string, BadgeVariant> = {
  HIGH: "high",
  MEDIUM: "medium",
  LOW: "low",
};

// ─────────────────────────────────────────────
// Collapsible section wrapped in a Card
// ─────────────────────────────────────────────

function Section({
  title,
  count,
  children,
  defaultOpen = true,
}: {
  title: string;
  count?: number;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <Card className="bg-card/60 border-border/50 mx-3 my-2">
      <Collapsible open={open} onOpenChange={setOpen}>
        <CollapsibleTrigger className="flex w-full items-center gap-2 px-3.5 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground hover:text-foreground/70 transition-colors cursor-pointer rounded-t-xl">
          {open
            ? <ChevronDown className="size-3 shrink-0" />
            : <ChevronRight className="size-3 shrink-0" />}
          <span className="flex-1 text-left">{title}</span>
          {count !== undefined && (
            <Badge variant="default" className="text-[9px] px-1.5 py-0">
              {count}
            </Badge>
          )}
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="px-3.5 pb-3.5">{children}</div>
        </CollapsibleContent>
      </Collapsible>
    </Card>
  );
}

// ─────────────────────────────────────────────
// Edge card
// ─────────────────────────────────────────────

function EdgeCard({ edge }: { edge: ApiEdgeDetail }) {
  let joinDisplay: string | null = null;
  if (edge.join_condition) {
    const m = edge.join_condition.match(/\.(\w+)\s*=\s*\w+\.(\w+)/);
    joinDisplay = m ? `${m[1]}  →  ${m[2]}` : edge.join_condition;
  }

  return (
    <div className="rounded-lg border border-border/40 bg-background/40 hover:border-border/80 transition-colors">
      {/* Row 1: path + relationship */}
      <div className="px-3 pt-2.5 pb-2">
        <div className="flex items-center gap-1.5 text-xs font-mono">
          <span className="text-primary font-semibold">{edge.from}</span>
          <span className="text-muted-foreground/30">→</span>
          <span className="text-primary font-semibold">{edge.to}</span>
        </div>
        <p className="text-[11px] text-muted-foreground italic mt-0.5">{edge.relationship}</p>
      </div>

      <Separator className="opacity-30" />

      {/* Row 2: metadata badges */}
      <div className="px-3 py-2 flex flex-wrap gap-1">
        <Badge variant={TYPE_VARIANT[edge.type] ?? "outline"}>{edge.type}</Badge>
        <Badge variant={CONF_VARIANT[edge.confidence] ?? "outline"}>{edge.confidence}</Badge>
        <Badge variant="outline">{edge.cardinality.replace(/_/g, ":").toLowerCase()}</Badge>
        {edge.optional && <Badge variant="secondary">optional</Badge>}
        {edge.completeness !== "FULL" && (
          <Badge variant="medium">{edge.completeness}</Badge>
        )}
      </div>

      {/* Row 3: join condition (if present) */}
      {joinDisplay && (
        <>
          <Separator className="opacity-30" />
          <div className="px-3 py-2 flex items-center gap-2">
            <span className="text-[9px] font-bold uppercase tracking-widest text-muted-foreground/40">join</span>
            <code className="text-[11px] text-muted-foreground font-mono bg-transparent p-0">{joinDisplay}</code>
          </div>
        </>
      )}

      {/* Row 4: filters (if present) */}
      {edge.filters.length > 0 && (
        <>
          <Separator className="opacity-30" />
          <div className="px-3 py-2 flex flex-wrap gap-1">
            {edge.filters.map((f, i) => (
              <code key={i} className="text-[10px] px-1.5 py-0.5 rounded bg-[rgba(167,139,250,0.08)] text-[#a78bfa] border border-[rgba(167,139,250,0.18)] font-mono">{f}</code>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────
// Graph state bar
// ─────────────────────────────────────────────

export function DebugPanel({
  nodeCount,
  edgeCount,
  expandedCount,
  activeExpansions,
}: {
  nodeCount: number;
  edgeCount: number;
  expandedCount: number;
  activeExpansions: number;
}) {
  return (
    <div className="shrink-0 px-5 py-2.5" style={{ background: "rgba(247, 248, 250, 0.9)", backdropFilter: "blur(8px)" }}>
      <div className="flex flex-wrap items-center gap-4 text-[11px] font-mono text-[#9ca3af]">
        <span className="flex items-center gap-2">
          <span className="size-1.5 rounded-full bg-[#3b82f6]" />
          <span className="tabular-nums">{nodeCount}</span> nodes
        </span>
        <span className="flex items-center gap-2">
          <span className="size-1.5 rounded-full bg-[#d1d5db]" />
          <span className="tabular-nums">{edgeCount}</span> edges
        </span>
        <span className="flex items-center gap-2">
          <span className="size-1.5 rounded-full bg-[#22c55e]" />
          <span className="tabular-nums">{expandedCount}</span> expanded
        </span>
        {activeExpansions > 0 && (
          <span className="flex items-center gap-2 text-[#3b82f6]">
            <Loader2 className="size-3 animate-spin" />
            <span className="tabular-nums">{activeExpansions}</span> loading
          </span>
        )}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────
// Main panel
// ─────────────────────────────────────────────

interface NodePanelProps {
  detail: ApiNodeDetail | null;
  loading: boolean;
  error: string | null;
}

export function NodePanel({ detail, loading, error }: NodePanelProps) {
  if (!loading && !error && !detail) {
    return (
      <div className="flex flex-col items-center justify-center h-full min-h-48 gap-3 text-muted-foreground/30 px-6">
        <span className="text-5xl">⬡</span>
        <span className="text-sm text-muted-foreground/50">Select a node to inspect</span>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center h-full min-h-48 gap-3 text-muted-foreground px-6">
        <Loader2 className="size-5 animate-spin text-primary" />
        <span className="text-sm">Loading…</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-full min-h-48 gap-2 px-6 text-center">
        <strong className="text-sm text-destructive">Failed to load node</strong>
        <span className="text-xs text-muted-foreground">{error}</span>
      </div>
    );
  }

  if (!detail) return null;

  const primaryKeys = Array.isArray(detail.primary_key)
    ? detail.primary_key
    : [detail.primary_key];
  const totalEdges = detail.outgoing_edges.length + detail.incoming_edges.length;
  const connectedCount = detail.connected_node_names.length;

  return (
    <div className="pb-3">
      {/* ── Header ──────────────────────────── */}
      <div className="px-4 pt-5 pb-4">
        <h2 className="text-xl font-bold text-foreground leading-tight tracking-tight m-0">
          {detail.name}
        </h2>
        {detail.source_table && (
          <code className="inline-block mt-1.5 text-[11px] text-muted-foreground font-mono bg-secondary/80 px-2 py-0.5 rounded border border-border/50">
            {detail.source_table}
          </code>
        )}
        <p className="mt-3 text-xs text-muted-foreground/80 leading-relaxed">
          Connects to{" "}
          <strong className="text-foreground/60 font-semibold">{connectedCount}</strong>{" "}
          {connectedCount === 1 ? "entity" : "entities"} via{" "}
          <strong className="text-foreground/60 font-semibold">{totalEdges}</strong>{" "}
          {totalEdges === 1 ? "relationship" : "relationships"}
        </p>
      </div>

      {/* ── Info ────────────────────────────── */}
      <Section title="Info" defaultOpen>
        <div className="flex flex-col gap-3.5">
          {/* Primary key */}
          <div className="flex flex-col gap-1.5">
            <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground/50">
              Primary key
            </span>
            <div className="flex flex-wrap gap-1">
              {primaryKeys.map((k) => (
                <code key={k} className="text-[11px] font-mono px-2 py-0.5 rounded bg-primary/10 text-primary border border-primary/20">
                  {k}
                </code>
              ))}
            </div>
          </div>

          {/* Alternate keys */}
          {detail.alternate_keys.length > 0 && (
            <div className="flex flex-col gap-1.5">
              <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground/50">
                Alternate keys
              </span>
              <div className="flex flex-wrap gap-1">
                {detail.alternate_keys.map((k) => (
                  <code key={k} className="text-[11px] font-mono px-2 py-0.5 rounded bg-secondary/60 text-muted-foreground border border-border/50">
                    {k}
                  </code>
                ))}
              </div>
            </div>
          )}

          {/* Record count */}
          {detail.record_count != null && (
            <div className="flex flex-col gap-0.5">
              <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground/50">
                Records
              </span>
              <span className="text-sm font-mono text-foreground/80">
                {detail.record_count.toLocaleString()}
              </span>
            </div>
          )}
        </div>

        {/* Query guidance */}
        {detail.query_guidance && (
          <div className="mt-4 rounded-lg bg-primary/5 border border-primary/10 p-3">
            <span className="block text-[10px] font-semibold uppercase tracking-wide text-primary mb-1.5">
              Query guidance
            </span>
            <p className="text-xs text-muted-foreground leading-relaxed m-0">
              {detail.query_guidance}
            </p>
          </div>
        )}
      </Section>

      {/* ── Attributes ──────────────────────── */}
      {detail.attributes.length > 0 && (
        <AttributeSection attributes={detail.attributes} />
      )}

      {/* ── Filters ─────────────────────────── */}
      {detail.filters.length > 0 && (
        <Section title="Filters" count={detail.filters.length} defaultOpen>
          <div className="flex flex-wrap gap-1.5">
            {detail.filters.map((f, i) => (
              <code key={i} className="text-[10px] px-2 py-0.5 rounded bg-[rgba(167,139,250,0.08)] text-[#a78bfa] border border-[rgba(167,139,250,0.18)] font-mono">{f}</code>
            ))}
          </div>
        </Section>
      )}

      {/* ── Outgoing edges ──────────────────── */}
      {detail.outgoing_edges.length > 0 && (
        <Section title="Outgoing" count={detail.outgoing_edges.length} defaultOpen>
          <div className="flex flex-col gap-2">
            {detail.outgoing_edges.map((e, i) => <EdgeCard key={i} edge={e} />)}
          </div>
        </Section>
      )}

      {/* ── Incoming edges ──────────────────── */}
      {detail.incoming_edges.length > 0 && (
        <Section title="Incoming" count={detail.incoming_edges.length} defaultOpen>
          <div className="flex flex-col gap-2">
            {detail.incoming_edges.map((e, i) => <EdgeCard key={i} edge={e} />)}
          </div>
        </Section>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────
// Attributes: bullet list with progressive disclosure
// ─────────────────────────────────────────────

const ATTR_PREVIEW = 5;

function AttributeSection({ attributes }: { attributes: string[] }) {
  const [expanded, setExpanded] = useState(false);
  const hasMore = attributes.length > ATTR_PREVIEW;
  const visible = expanded ? attributes : attributes.slice(0, ATTR_PREVIEW);

  return (
    <Section title="Attributes" count={attributes.length} defaultOpen={false}>
      <ul className="flex flex-col gap-1 list-none p-0 m-0">
        {visible.map((a) => (
          <li key={a} className="flex items-center gap-2 text-[12px] text-muted-foreground/80 py-0.5 hover:text-foreground/70 transition-colors">
            <span className="size-1 rounded-full bg-muted-foreground/30 shrink-0" />
            <code className="font-mono text-[11px] bg-transparent p-0 border-none text-inherit">{a}</code>
          </li>
        ))}
      </ul>
      {hasMore && (
        <button
          onClick={() => setExpanded((v) => !v)}
          className="mt-2 text-[11px] px-2.5 py-1 rounded-md bg-primary/8 text-primary border border-primary/15 cursor-pointer font-medium hover:bg-primary/15 transition-colors"
        >
          {expanded ? "show less" : `+${attributes.length - ATTR_PREVIEW} more`}
        </button>
      )}
    </Section>
  );
}
