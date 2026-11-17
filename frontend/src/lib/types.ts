// Mirrors backend/app/schemas/*. Keep in sync when the API contract changes.

export type Domain = "movie" | "book";
export type ModelName = "hybrid" | "als" | "content" | "popular";
export type SortKey = "popular" | "rating" | "year";

export type ItemSummary = {
  id: number;
  domain: Domain;
  title: string;
  year: number | null;
  creators: string[];
  genres: string[];
  cover_url: string | null;
  rating_count: number;
  rating_avg: number;
};

export type ItemDetail = ItemSummary & {
  description: string | null;
  meta: Record<string, unknown>;
  my_rating: number | null;
};

export type Page<T> = { items: T[]; total: number; page: number; page_size: number };

export type GenreCount = { genre: string; count: number };
export type SimilarItem = { item: ItemSummary; score: number };

export type UserProfile = {
  id: number;
  email: string;
  display_name: string;
  created_at: string;
  rating_counts: Record<Domain, number>;
};

export type RatingResult = { item_id: number; value: number; rated_at: string };
export type RatedItem = { item: ItemSummary; value: number; rated_at: string | null };
export type HistoryItem = { id: number; item: ItemSummary; kind: string; created_at: string };

export type RecommendationItem = {
  item: ItemSummary;
  score: number;
  sources: { als: number; content: number; popular: number };
  explanation: string | null;
};

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
