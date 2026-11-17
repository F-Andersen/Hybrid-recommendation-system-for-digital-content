"use client";

import Link from "next/link";
import { useState } from "react";

import { ONBOARDING_TARGET, pad2 } from "@/lib/format";
import type { ItemSummary } from "@/lib/types";

import { ItemCover } from "./ItemCover";
import { RatingControl } from "./RatingControl";

type Props = { items: ItemSummary[]; initialCount: number };

export function OnboardingBoard({ items, initialCount }: Props) {
  const [count, setCount] = useState(initialCount);
  const done = count >= ONBOARDING_TARGET;
  const shown = Math.min(count, ONBOARDING_TARGET);

  function track(previous: number | null, next: number | null) {
    if (previous === null && next !== null) setCount((c) => c + 1);
    else if (previous !== null && next === null) setCount((c) => Math.max(0, c - 1));
  }

  return (
    <>
      <div className="progress" aria-live="polite">
        <span className="mono">
          Оцінено {pad2(shown)} / {pad2(ONBOARDING_TARGET)}
        </span>
        <div
          className="progress-bar"
          role="progressbar"
          aria-label="Прогрес оцінювання"
          aria-valuemin={0}
          aria-valuemax={ONBOARDING_TARGET}
          aria-valuenow={shown}
        >
          <div className="progress-fill" style={{ width: `${(shown / ONBOARDING_TARGET) * 100}%` }} />
        </div>
        {done ? (
          <Link href="/recommendations" className="btn btn-primary">
            Перейти до рекомендацій
          </Link>
        ) : (
          <span className="btn btn-primary" aria-disabled="true">
            Ще {ONBOARDING_TARGET - count}
          </span>
        )}
      </div>

      <ul className="onboard-list" style={{ marginTop: 16 }}>
        {items.map((item) => (
          <li key={item.id} className="onboard-row">
            <ItemCover item={item} />
            <div>
              <Link href={`/items/${item.id}`} className="item-title" prefetch={false}>
                {item.title}
              </Link>
              <div className="mono item-meta">
                {[item.year, item.creators[0], item.genres.slice(0, 3).join(", ")]
                  .filter(Boolean)
                  .join(" · ")}
              </div>
            </div>
            <RatingControl
              itemId={item.id}
              initial={null}
              compact
              label={`Оцінка для «${item.title}»`}
              onChange={track}
            />
          </li>
        ))}
      </ul>
    </>
  );
}
