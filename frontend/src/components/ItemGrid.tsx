import Link from "next/link";

import { formatAvg, formatInt } from "@/lib/format";
import type { ItemSummary } from "@/lib/types";

import { ItemCover } from "./ItemCover";

type Props = {
  items: ItemSummary[];
  /** Optional extra line per item, e.g. a similarity score. */
  note?: (item: ItemSummary) => string | null;
};

export function ItemGrid({ items, note }: Props) {
  return (
    <ul className="item-grid">
      {items.map((item) => {
        const extra = note?.(item);
        return (
          <li key={item.id}>
            {/* No prefetch: opening an item records a view and resets cached explanations. */}
            <Link href={`/items/${item.id}`} className="item-cell" prefetch={false}>
              <ItemCover item={item} />
              <span className="item-title">{item.title}</span>
              <span className="mono item-meta">
                {[item.year, item.creators[0]].filter(Boolean).join(" · ") || "—"}
              </span>
              <span className="mono item-meta">
                <span title="Середня оцінка за шкалою 1–10">{formatAvg(item.rating_avg)}</span>
                {" / 10 · "}
                <span title="Кількість оцінок і взаємодій">{formatInt(item.rating_count)}</span>
              </span>
              {extra ? <span className="mono item-meta">{extra}</span> : null}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
