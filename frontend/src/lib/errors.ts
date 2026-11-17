export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const FALLBACK: Record<number, string> = {
  401: "Потрібно увійти в обліковий запис",
  404: "Не знайдено",
  409: "Конфлікт даних",
  422: "Перевірте введені дані",
  503: "Сервіс тимчасово недоступний",
};

type ValidationIssue = { msg?: unknown };

/** Turns a FastAPI error body ({detail: string | [{msg}]}) into one readable sentence. */
export async function readErrorDetail(res: Response): Promise<string> {
  const fallback = FALLBACK[res.status] ?? `Помилка сервера (${res.status})`;
  try {
    const body: unknown = await res.json();
    const detail = (body as { detail?: unknown } | null)?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      const messages = (detail as ValidationIssue[])
        .map((issue) => (typeof issue.msg === "string" ? issue.msg : ""))
        .map((msg) => msg.replace(/^Value error,\s*/, ""))
        .filter(Boolean);
      if (messages.length) return [...new Set(messages)].join("; ");
    }
  } catch {
    // non-JSON body
  }
  return fallback;
}
