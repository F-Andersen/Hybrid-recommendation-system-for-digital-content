"use client";

import { useId, useState } from "react";

import { apiSend, errorMessage } from "@/lib/client-api";
import type { RatingResult } from "@/lib/types";

type Props = {
  itemId: number;
  initial: number | null;
  /** Hides the legend visually (still announced) for dense lists. */
  compact?: boolean;
  label?: string;
  onChange?: (previous: number | null, next: number | null) => void;
};

const SCALE = Array.from({ length: 10 }, (_, i) => i + 1);

export function RatingControl({ itemId, initial, compact = false, label, onChange }: Props) {
  const [value, setValue] = useState<number | null>(initial);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const legendId = useId();

  async function save(next: number | null) {
    if (busy || next === value) return;
    const previous = value;
    setValue(next);
    setBusy(true);
    setStatus(null);
    try {
      if (next === null) await apiSend("DELETE", `/ratings/${itemId}`);
      else await apiSend<RatingResult>("PUT", `/ratings/${itemId}`, { value: next });
      setStatus({ tone: "ok", text: next === null ? "Оцінку прибрано" : "Збережено" });
      onChange?.(previous, next);
    } catch (error) {
      setValue(previous);
      setStatus({ tone: "error", text: errorMessage(error) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={compact ? "rating rating-compact" : "rating"}>
      <div
        role="group"
        aria-labelledby={legendId}
        className="rating-scale"
        aria-busy={busy || undefined}
      >
        <span id={legendId} className={compact ? "visually-hidden" : "field-label"}>
          {label ?? "Моя оцінка, 1–10"}
        </span>
        <div className="rating-buttons">
          {SCALE.map((n) => (
            <button
              key={n}
              type="button"
              className="rating-btn mono"
              aria-pressed={value === n}
              aria-label={`Оцінка ${n} з 10`}
              // aria-disabled instead of disabled: a disabled button drops keyboard focus.
              aria-disabled={busy || undefined}
              onClick={() => save(n)}
            >
              {n}
            </button>
          ))}
        </div>
      </div>
      <div className="rating-footer">
        {value !== null ? (
          <button
            type="button"
            className="btn-link mono"
            aria-disabled={busy || undefined}
            onClick={() => save(null)}
          >
            Прибрати оцінку
          </button>
        ) : (
          <span className="mono muted">Не оцінено</span>
        )}
        <span
          className={`mono status-line ${status ? `status-${status.tone === "ok" ? "ok" : "error"}` : ""}`}
          role="status"
          aria-live="polite"
        >
          {busy ? "Зберігаємо…" : (status?.text ?? "")}
        </span>
      </div>
    </div>
  );
}
