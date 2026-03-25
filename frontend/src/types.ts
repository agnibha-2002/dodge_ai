// ─────────────────────────────────────────────
// Shared types used across all modules
// ─────────────────────────────────────────────

export interface ApiNode {
  name: string;
  source_table: string | null;
  record_count: number | null;
}

export interface ApiEdge {
  from: string;
  to: string;
  relationship: string;
  type: string;
}

export interface ApiExpandResponse {
  center_node: ApiNode;
  nodes: ApiNode[];
  edges: ApiEdge[];
}

export interface ApiEdgeDetail {
  from: string;
  to: string;
  relationship: string;
  type: string;
  join_condition: string;
  cardinality: string;
  confidence: string;
  optional: boolean;
  completeness: string;
  filters: string[];
}

export interface ApiNodeDetail {
  name: string;
  source_table: string | null;
  primary_key: string | string[];
  alternate_keys: string[];
  attributes: string[];
  filters: string[];
  record_count: number | null;
  query_guidance: string | null;
  outgoing_edges: ApiEdgeDetail[];
  incoming_edges: ApiEdgeDetail[];
  connected_node_names: string[];
}

export interface GraphNode {
  id: string;
  label: string;
  record_count: number | null;
  x?: number;
  y?: number;
}

export interface GraphLink {
  source: string | GraphNode;
  target: string | GraphNode;
  label: string;
  type: string;
}

export interface GraphState {
  nodeMap: Map<string, GraphNode>;
  edgeMap: Map<string, GraphLink>;
}

// ─────────────────────────────────────────────
// Record-level graph types
// ─────────────────────────────────────────────

export interface RecordGraphNode {
  id: string;
  entity: string;
  primary_key_value: string;
  fields: Record<string, unknown>;
}

export interface RecordGraphEdge {
  source: string;
  target: string;
  relationship: string;
}

export interface RecordGraphResponse {
  nodes: RecordGraphNode[];
  edges: RecordGraphEdge[];
  entity_colors: Record<string, string>;
}

// ForceGraph-compatible record node (with position)
export interface RecordForceNode extends RecordGraphNode {
  x?: number;
  y?: number;
}

// ForceGraph-compatible record link
export interface RecordForceLink {
  source: string | RecordForceNode;
  target: string | RecordForceNode;
  relationship: string;
}

export interface RecordsResponse {
  node_name: string;
  source_table: string | null;
  columns: string[];
  column_types: Record<string, string>;
  primary_key: string | string[];
  records: Record<string, unknown>[];
  total_count: number;
  offset: number;
  limit: number;
}
