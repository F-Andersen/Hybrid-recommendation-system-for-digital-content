// Server-side access to FastAPI (server components only). Client components use lib/client-api.ts.
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { cache } from "react";

import { ApiError, readErrorDetail } from "./errors";
import type { HealthResponse, UserProfile } from "./types";

const API_INTERNAL_URL = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

async function rawGet<T>(path: string, withSession: boolean): Promise<T> {
  const headers: Record<string, string> = {};
  if (withSession) {
    const session = (await cookies()).get("session");
    if (session) headers.cookie = `session=${session.value}`;
  }
  const res = await fetch(`${API_INTERNAL_URL}${path}`, { cache: "no-store", headers });
  if (!res.ok) throw new ApiError(res.status, await readErrorDetail(res));
  return (await res.json()) as T;
}

/** Current user, or null for guests and expired sessions. Deduplicated per request. */
export const getMe = cache(async (): Promise<UserProfile | null> => {
  if (!(await cookies()).get("session")) return null;
  try {
    return await rawGet<UserProfile>("/auth/me", true);
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null;
    throw error;
  }
});

/**
 * GET from the API, forwarding the session cookie only when it is valid,
 * so a stale cookie never turns a public page into a 401.
 */
export async function apiGet<T>(path: string): Promise<T> {
  return rawGet<T>(path, (await getMe()) !== null);
}

export async function requireUser(nextPath: string): Promise<UserProfile> {
  const me = await getMe();
  if (!me) redirect(`/login?next=${encodeURIComponent(nextPath)}`);
  return me;
}

export async function getHealth(): Promise<HealthResponse | null> {
  try {
    return await rawGet<HealthResponse>("/health", false);
  } catch {
    return null;
  }
}
