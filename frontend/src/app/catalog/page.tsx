import type { Metadata } from "next";
import Link from "next/link";

import { ItemGrid } from "@/components/ItemGrid";
import { Pagination } from "@/components/Pagination";
import { Empty, Section } from "@/components/Section";
import { Tabs } from "@/components/Tabs";
import { apiGet } from "@/lib/api";
import {
  DOMAIN_LABEL,
  DOMAINS,
  formatInt,
  pickDomain,
  pickPage,
  pickSort,
  pickText,
  query,
  SORT_LABEL,
} from "@/lib/format";
import type { GenreCount, ItemSummary, Page, SortKey } from "@/lib/types";

export const metadata: Metadata = { title: "Каталог" };

const PAGE_SIZE = 24;

type Props = { searchParams: Promise<Record<string, string | string[] | undefined>> };

export default async function CatalogPage({ searchParams }: Props) {
  const params = await searchParams;
  const domain = pickDomain(params);
  const q = pickText(params, "q");
  const genre = pickText(params, "genre");
  const sort = pickSort(params);
  const page = pickPage(params);

  const [result, genres] = await Promise.all([
    apiGet<Page<ItemSummary>>(
      `/items${query({ domain, q, genre, sort, page, page_size: PAGE_SIZE })}`,
    ),
    apiGet<GenreCount[]>(`/items/genres${query({ domain })}`),
  ]);

  const state = { domain, q, genre, sort: sort === "popular" ? undefined : sort };
  const pageHref = (p: number) => `/catalog${query({ ...state, page: p > 1 ? p : undefined })}`;
  const filtered = Boolean(q || genre);

  return (
    <>
      <h1 className="page-title">Каталог</h1>
      <Tabs
        label="Тип контенту"
        tabs={DOMAINS.map((d) => ({
          href: `/catalog${query({ domain: d })}`,
          label: DOMAIN_LABEL[d],
          active: d === domain,
        }))}
      />

      <Section number={1} title="Фільтри">
        {/* Plain GET form: works without JavaScript, state lives in the URL. */}
        <form className="filters" action="/catalog" method="get" role="search">
          <input type="hidden" name="domain" value={domain} />
          <div className="field field-search">
            <label className="field-label" htmlFor="q">
              Пошук за назвою
            </label>
            <input
              className="input"
              id="q"
              name="q"
              type="search"
              defaultValue={q}
              maxLength={200}
              placeholder={domain === "movie" ? "Наприклад, Matrix" : "Наприклад, Harry Potter"}
            />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="genre">
              {domain === "movie" ? "Жанр" : "Тематика"}
            </label>
            <select className="select" id="genre" name="genre" defaultValue={genre}>
              <option value="">Усі</option>
              {genres.map((g) => (
                <option key={g.genre} value={g.genre}>
                  {g.genre} ({formatInt(g.count)})
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label className="field-label" htmlFor="sort">
              Сортування
            </label>
            <select className="select" id="sort" name="sort" defaultValue={sort}>
              {(Object.keys(SORT_LABEL) as SortKey[]).map((key) => (
                <option key={key} value={key}>
                  {SORT_LABEL[key]}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <button type="submit" className="btn btn-primary">
              Застосувати
            </button>
          </div>
        </form>
        {filtered ? (
          <p className="mono muted" style={{ margin: "12px 0 0" }}>
            <Link href={`/catalog${query({ domain })}`}>Скинути фільтри</Link>
          </p>
        ) : null}
      </Section>

      <Section
        number={2}
        title={DOMAIN_LABEL[domain]}
        aside={<span>Знайдено: {formatInt(result.total)}</span>}
      >
        {result.items.length ? (
          <>
            <ItemGrid items={result.items} />
            <Pagination
              page={result.page}
              pageSize={result.page_size}
              total={result.total}
              href={pageHref}
            />
          </>
        ) : (
          <Empty>
            {filtered
              ? "За цими умовами нічого не знайдено. Спробуйте іншу назву або скиньте фільтри."
              : "Каталог порожній. Імпортуйте датасети (етап 1)."}
          </Empty>
        )}
      </Section>
    </>
  );
}
