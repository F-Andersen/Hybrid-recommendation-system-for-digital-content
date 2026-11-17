import type { Domain, ModelName, SortKey } from "./types";

export const DOMAINS: Domain[] = ["movie", "book"];

/** Minimum number of ratings asked for during onboarding. */
export const ONBOARDING_TARGET = 5;

export const DOMAIN_LABEL: Record<Domain, string> = { movie: "Фільми", book: "Книги" };
export const DOMAIN_SINGULAR: Record<Domain, string> = { movie: "фільм", book: "книга" };

export const MODEL_LABEL: Record<ModelName, string> = {
  hybrid: "Гібрид + LLM",
  als: "ALS",
  content: "Контентна",
  popular: "Популярність",
};
export const MODELS: ModelName[] = ["hybrid", "als", "content", "popular"];

export const SORT_LABEL: Record<SortKey, string> = {
  popular: "За популярністю",
  rating: "За оцінкою",
  year: "За роком",
};

type Params = Record<string, string | string[] | undefined>;

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export function pickDomain(params: Params): Domain {
  return first(params.domain) === "book" ? "book" : "movie";
}

export function pickModel(params: Params): ModelName {
  const value = first(params.model);
  return MODELS.includes(value as ModelName) ? (value as ModelName) : "hybrid";
}

export function pickSort(params: Params): SortKey {
  const value = first(params.sort);
  return value === "rating" || value === "year" ? value : "popular";
}

export function pickPage(params: Params, key = "page"): number {
  const value = Number.parseInt(first(params[key]) ?? "1", 10);
  return Number.isFinite(value) && value >= 1 ? Math.min(value, 10_000) : 1;
}

export function pickText(params: Params, key: string): string {
  return (first(params[key]) ?? "").trim().slice(0, 200);
}

/** Average rating on the 1–10 scale; 0 means "no explicit ratings yet". */
export function formatAvg(value: number): string {
  return value > 0 ? value.toFixed(1) : "—";
}

export function formatScore(value: number): string {
  return value.toFixed(2);
}

export function formatInt(value: number): string {
  return new Intl.NumberFormat("uk-UA").format(value);
}

const dateFormat = new Intl.DateTimeFormat("uk-UA", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
});
const dateTimeFormat = new Intl.DateTimeFormat("uk-UA", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Europe/Kyiv",
});

export function formatDate(iso: string | null): string {
  return iso ? dateFormat.format(new Date(iso)) : "—";
}

export function formatDateTime(iso: string): string {
  return dateTimeFormat.format(new Date(iso));
}

export function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

export function query(params: Record<string, string | number | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}
