/**
 * Centralized API routing helper for VMD Bullion Frontend.
 * Supports explicit cross-origin Oracle backend via NEXT_PUBLIC_API_BASE_URL (Vercel deployment)
 * or Next.js rewrite proxy (/api/*) in local development.
 */

export function getApiBaseUrl(): string {
  const raw = process.env.NEXT_PUBLIC_API_BASE_URL || "";
  return raw.replace(/\/+$/, "");
}

export function apiUrl(path: string): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const base = getApiBaseUrl();
  return base ? `${base}${normalizedPath}` : normalizedPath;
}

export type BullionDashboardPayload = Record<string, unknown>;

export async function fetchBullionDashboard(
  city: string = "CHENNAI",
  historyLimit: number = 30
): Promise<BullionDashboardPayload> {
  const res = await fetch(
    apiUrl(`/api/bullion/dashboard?city=${encodeURIComponent(city)}&history_limit=${historyLimit}`),
    { cache: "no-store" }
  );
  if (!res.ok) {
    throw new Error(`Dashboard request failed with HTTP ${res.status}`);
  }
  return res.json();
}

export function openBullionEventStream(
  onSnapshot: (data: BullionDashboardPayload) => void,
  onStatus: (status: { connected: boolean; degraded?: boolean; message?: string }) => void
): () => void {
  if (typeof window === "undefined" || typeof EventSource === "undefined") {
    return () => {};
  }

  let closed = false;
  const es = new EventSource(apiUrl("/api/bullion/stream"));

  es.addEventListener("snapshot", (ev: MessageEvent) => {
    if (closed) return;
    try {
      const parsed = JSON.parse(ev.data);
      onSnapshot(parsed);
      onStatus({ connected: true, degraded: false });
    } catch {
      // Ignore malformed frame
    }
  });

  es.addEventListener("heartbeat", () => {
    if (!closed) {
      onStatus({ connected: true, degraded: false });
    }
  });

  es.addEventListener("status", (ev: MessageEvent) => {
    if (closed) return;
    try {
      const parsed = JSON.parse(ev.data);
      onStatus({ connected: true, degraded: parsed.status === "DEGRADED", message: parsed.error });
    } catch {
      onStatus({ connected: true, degraded: true });
    }
  });

  es.onerror = () => {
    if (!closed) {
      onStatus({ connected: false, degraded: true, message: "SSE reconnecting..." });
    }
  };

  return () => {
    closed = true;
    es.close();
  };
}
