// Server-side access to FastAPI. Client components call "/api/*" instead (proxied by Next.js).
const API_INTERNAL_URL = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

export type HealthResponse = {
  status: "ok" | "degraded";
  db: { ok: boolean; pgvector: boolean; error: string | null };
  ollama: {
    ok: boolean;
    models_required: string[];
    models_missing: string[];
    error: string | null;
  };
  als_loaded: Record<string, boolean>;
};

export async function getHealth(): Promise<HealthResponse | null> {
  try {
    const res = await fetch(`${API_INTERNAL_URL}/health`, { cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as HealthResponse;
  } catch {
    return null;
  }
}
