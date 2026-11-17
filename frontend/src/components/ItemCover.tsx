"use client";

import { useState } from "react";

import { DOMAIN_SINGULAR } from "@/lib/format";
import type { ItemSummary } from "@/lib/types";

type Props = { item: Pick<ItemSummary, "title" | "cover_url" | "domain" | "year"> };

/** Cover image, or a ruled frame with the title when there is none or it fails to load. */
export function ItemCover({ item }: Props) {
  const [failed, setFailed] = useState(false);

  if (!item.cover_url || failed) {
    return (
      <div className="cover cover-fallback" aria-hidden="true">
        <span className="mono cover-kind">{DOMAIN_SINGULAR[item.domain]}</span>
        <span className="cover-title">{item.title}</span>
        {item.year ? <span className="mono cover-kind">{item.year}</span> : null}
      </div>
    );
  }

  return (
    // Plain <img> on purpose: covers are external, small, and must fall back on 404.
    // eslint-disable-next-line @next/next/no-img-element
    <img
      className="cover"
      src={item.cover_url}
      alt=""
      loading="lazy"
      decoding="async"
      onError={() => setFailed(true)}
    />
  );
}
