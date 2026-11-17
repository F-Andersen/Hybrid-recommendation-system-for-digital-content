// Browser-side calls go through the Next.js proxy (/api/* → FastAPI), so cookies stay first-party.
import { ApiError, readErrorDetail } from "./errors";

export async function apiSend<T>(
  method: "POST" | "PUT" | "DELETE",
  path: string,
  body?: unknown,
): Promise<T | null> {
  const res = await fetch(`/api${path}`, {
    method,
    credentials: "same-origin",
    headers: body === undefined ? undefined : { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw new ApiError(res.status, await readErrorDetail(res));
  if (res.status === 204) return null;
  return (await res.json()) as T;
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "Немає зв'язку з сервером. Спробуйте ще раз.";
}

/** Accept only same-site relative paths as a post-login destination. */
export function safeNext(next: string | null | undefined, fallback = "/"): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) {
    return fallback;
  }
  return next;
}
