import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { cache } from "react";

import { ItemCover } from "@/components/ItemCover";
import { ItemGrid } from "@/components/ItemGrid";
import { RatingControl } from "@/components/RatingControl";
import { Empty, Section } from "@/components/Section";
import { apiGet, getMe } from "@/lib/api";
import { ApiError } from "@/lib/errors";
import { DOMAIN_LABEL, DOMAIN_SINGULAR, formatAvg, formatInt, formatScore } from "@/lib/format";
import type { ItemDetail, SimilarItem } from "@/lib/types";

type Props = { params: Promise<{ id: string }> };

// GET /items/{id} records a view for signed-in users, so fetch it once per request
// even though both generateMetadata and the page need it.
const loadItem = cache(async (raw: string): Promise<ItemDetail | null> => {
  const id = Number(raw);
  if (!Number.isSafeInteger(id) || id < 1) return null;
  try {
    return await apiGet<ItemDetail>(`/items/${id}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
});

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const item = await loadItem((await params).id);
  return { title: item ? item.title : "Не знайдено" };
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
}

export default async function ItemPage({ params }: Props) {
  const { id } = await params;
  const [item, me] = await Promise.all([loadItem(id), getMe()]);
  if (!item) notFound();
  const similar = await apiGet<SimilarItem[]>(`/items/${item.id}/similar`);

  const tags = stringList(item.meta.tags);
  const publisher = typeof item.meta.publisher === "string" ? item.meta.publisher : null;
  const scores = new Map(similar.map((s) => [s.item.id, s.score]));
  const genreLabel = item.domain === "movie" ? "Жанри" : "Тематики";

  return (
    <>
      <p className="mono muted" style={{ margin: 0 }}>
        <Link href={`/catalog?domain=${item.domain}`}>Каталог · {DOMAIN_LABEL[item.domain]}</Link>
      </p>
      <h1 className="page-title">
        {item.title}
        {item.year ? <span className="mono muted"> ({item.year})</span> : null}
      </h1>

      <Section number={1} title="Паспорт">
        <div className="detail">
          <ItemCover item={item} />
          <dl className="spec">
            <dt>Тип</dt>
            <dd>{DOMAIN_SINGULAR[item.domain]}</dd>
            <dt>Рік</dt>
            <dd className="mono">{item.year ?? "—"}</dd>
            {item.domain === "book" ? (
              <>
                <dt>Автори</dt>
                <dd>{item.creators.length ? item.creators.join(", ") : "—"}</dd>
                <dt>Видавець</dt>
                <dd>{publisher ?? "—"}</dd>
              </>
            ) : null}
            <dt>{genreLabel}</dt>
            <dd>
              {item.genres.length ? (
                <ul className="tag-list">
                  {item.genres.map((g) => (
                    <li key={g}>
                      <Link href={`/catalog?domain=${item.domain}&genre=${encodeURIComponent(g)}`}>
                        {g}
                      </Link>
                    </li>
                  ))}
                </ul>
              ) : (
                "—"
              )}
            </dd>
            {tags.length ? (
              <>
                <dt>Теги</dt>
                <dd>
                  <ul className="tag-list">
                    {tags.map((t) => (
                      <li key={t}>{t}</li>
                    ))}
                  </ul>
                </dd>
              </>
            ) : null}
            <dt>Середня оцінка</dt>
            <dd className="mono">{formatAvg(item.rating_avg)} / 10</dd>
            <dt>Взаємодій</dt>
            <dd className="mono">{formatInt(item.rating_count)}</dd>
          </dl>
        </div>
      </Section>

      <Section number={2} title="Опис">
        {item.description ? (
          <p className="description">{item.description}</p>
        ) : (
          <Empty>
            {item.domain === "movie"
              ? "MovieLens не містить анотацій. Схожість рахується за назвою, жанрами й тегами."
              : "Анотації в Open Library немає. Схожість рахується за назвою, автором і тематиками."}
          </Empty>
        )}
      </Section>

      <Section number={3} title="Моя оцінка">
        {me ? (
          <RatingControl itemId={item.id} initial={item.my_rating} />
        ) : (
          <p>
            <Link href={`/login?next=/items/${item.id}`}>Увійдіть</Link>, щоб оцінити цей{" "}
            {item.domain === "movie" ? "фільм" : "твір"} і отримувати персональні рекомендації.
          </p>
        )}
      </Section>

      <Section number={4} title="Схожі за змістом" aside={<span>BGE-M3 · косинусна схожість</span>}>
        {similar.length ? (
          <ItemGrid
            items={similar.map((s) => s.item)}
            note={(i) => `схожість ${formatScore(scores.get(i.id) ?? 0)}`}
          />
        ) : (
          <Empty>Для цього запису ще немає ембединга.</Empty>
        )}
      </Section>
    </>
  );
}
