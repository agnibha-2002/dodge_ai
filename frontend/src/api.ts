const rawApiBase = (import.meta.env.VITE_API_BASE_URL ?? "").trim();

export const API_BASE =
  rawApiBase.replace(/\/+$/, "") || (import.meta.env.DEV ? "http://localhost:8000" : "");

export function apiUrl(path: string): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${API_BASE}${normalizedPath}`;
}
