"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { apiSend, errorMessage } from "@/lib/client-api";
import { formatScore, pad2 } from "@/lib/format";
import type { Domain, ModelName, RecommendationItem } from "@/lib/types";

import { ItemCover } from "./ItemCover";

type Props = {
  initial: RecommendationItem[];
  domain: Domain;
  model: ModelName;
  /** Ask the LLM for explanations when the hybrid list arrives without them. */
  explain: boolean;
};

type Phase =
  | { kind: "idle" }
  | { kind: "working"; seconds: number }
  | { kind: "done" }
  | { kind: "failed"; message: string };

const SOURCE_LABEL = { als: "ALS", content: "Контент", popular: "Популярн." } as const;

export function RecommendationList({ initial, domain, model, explain }: Props) {
  const [rows, setRows] = useState(initial);
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const started = useRef(false);

  const needsExplanation =
    explain && model === "hybrid" && initial.length > 0 && initial.every((r) => r.explanation === null);

  useEffect(() => {
    if (!needsExplanation || started.current) return;
    started.current = true;
    const startedAt = Date.now();
    setPhase({ kind: "working", seconds: 0 });
    const timer = window.setInterval(() => {
      setPhase((p) =>
        p.kind === "working" ? { kind: "working", seconds: Math.round((Date.now() - startedAt) / 1000) } : p,
      );
    }, 1000);

    apiSend<RecommendationItem[]>("POST", "/recommendations/explain", { domain })
      .then((result) => {
        if (result && result.length) setRows(result);
        const explained = result?.some((r) => r.explanation) ?? false;
        setPhase(
          explained
            ? { kind: "done" }
            : { kind: "failed", message: "Мовна модель не відповіла вчасно — показано гібридний список." },
        );
      })
      .catch((error: unknown) => setPhase({ kind: "failed", message: errorMessage(error) }))
      .finally(() => window.clearInterval(timer));

    return () => window.clearInterval(timer);
  }, [needsExplanation, domain]);

  return (
    <>
      <p
        className={`mono status-line ${phase.kind === "failed" ? "status-warn" : phase.kind === "done" ? "status-ok" : ""}`}
        role="status"
        aria-live="polite"
        style={{ margin: "0 0 12px" }}
      >
        {phase.kind === "working"
          ? `Модель Qwen3 формує пояснення… ${phase.seconds} с`
          : phase.kind === "done"
            ? "Список переранжовано мовною моделлю, пояснення додано."
            : phase.kind === "failed"
              ? `Пояснення недоступні: ${phase.message}`
              : model === "hybrid" && rows.some((r) => r.explanation)
                ? "Пояснення з кешу: профіль не змінювався після останньої генерації."
                : ""}
      </p>

      <ol className="rec-list">
        {rows.map((row, index) => (
          <li key={row.item.id} className="rec-row">
            <span className="mono rec-pos" aria-hidden="true">
              {pad2(index + 1)}
            </span>
            <ItemCover item={row.item} />
            <div className="rec-body">
              <Link href={`/items/${row.item.id}`} className="rec-title" prefetch={false}>
                {row.item.title}
              </Link>
              <div className="mono item-meta">
                {[row.item.year, row.item.creators[0], row.item.genres.slice(0, 4).join(", ")]
                  .filter(Boolean)
                  .join(" · ")}
              </div>
              {row.explanation ? (
                <p className="rec-explanation">{row.explanation}</p>
              ) : model === "hybrid" && phase.kind !== "working" && phase.kind !== "idle" ? (
                <p className="mono rec-explanation-missing">
                  Без пояснення: позицію доповнено гібридним рейтингом.
                </p>
              ) : null}
            </div>
            <table className="sources">
              <caption className="visually-hidden">Внесок моделей у позицію</caption>
              <tbody>
                {(Object.keys(SOURCE_LABEL) as (keyof typeof SOURCE_LABEL)[]).map((key) => (
                  <tr key={key}>
                    <th scope="row">{SOURCE_LABEL[key]}</th>
                    <td className="bar-cell" aria-hidden="true">
                      <div className="bar">
                        <div
                          className="bar-fill"
                          style={{ width: `${Math.max(0, Math.min(1, row.sources[key])) * 100}%` }}
                        />
                      </div>
                    </td>
                    <td className="num">{formatScore(row.sources[key])}</td>
                  </tr>
                ))}
                <tr className="sources-total">
                  <th scope="row">Разом</th>
                  <td aria-hidden="true" />
                  <td className="num">{formatScore(row.score)}</td>
                </tr>
              </tbody>
            </table>
          </li>
        ))}
      </ol>
    </>
  );
}
