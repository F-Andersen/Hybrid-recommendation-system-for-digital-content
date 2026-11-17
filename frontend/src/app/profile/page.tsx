import type { Metadata } from "next";
import Link from "next/link";

import { Metrics } from "@/components/Metrics";
import { Pagination } from "@/components/Pagination";
import { Empty, Section } from "@/components/Section";
import { apiGet, requireUser } from "@/lib/api";
import {
  DOMAIN_SINGULAR,
  formatDate,
  formatDateTime,
  formatInt,
  pickPage,
  query,
} from "@/lib/format";
import type { HistoryItem, Page, RatedItem } from "@/lib/types";

export const metadata: Metadata = { title: "Профіль" };

const PAGE_SIZE = 20;

type Props = { searchParams: Promise<Record<string, string | string[] | undefined>> };

export default async function ProfilePage({ searchParams }: Props) {
  const params = await searchParams;
  const rp = pickPage(params, "rp");
  const hp = pickPage(params, "hp");
  const me = await requireUser(`/profile${query({ rp: rp > 1 ? rp : undefined, hp: hp > 1 ? hp : undefined })}`);

  const [ratings, history] = await Promise.all([
    apiGet<Page<RatedItem>>(`/me/ratings${query({ page: rp, page_size: PAGE_SIZE })}`),
    apiGet<Page<HistoryItem>>(`/me/history${query({ page: hp, page_size: PAGE_SIZE })}`),
  ]);
  const href = (key: "rp" | "hp") => (p: number) =>
    `/profile${query({
      rp: key === "rp" ? (p > 1 ? p : undefined) : rp > 1 ? rp : undefined,
      hp: key === "hp" ? (p > 1 ? p : undefined) : hp > 1 ? hp : undefined,
    })}`;

  return (
    <>
      <h1 className="page-title">{me.display_name}</h1>
      <p className="page-lead mono">{me.email}</p>

      <Section number={1} title="Показники">
        <Metrics
          items={[
            { label: "Оцінено фільмів", value: formatInt(me.rating_counts.movie) },
            { label: "Оцінено книг", value: formatInt(me.rating_counts.book) },
            { label: "Переглядів карток", value: formatInt(history.total) },
            { label: "Учасник з", value: formatDate(me.created_at) },
          ]}
        />
      </Section>

      <Section number={2} title="Мої оцінки" aside={<span>Усього: {formatInt(ratings.total)}</span>}>
        {ratings.items.length ? (
          <>
            <div className="table-scroll">
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">Назва</th>
                    <th scope="col">Тип</th>
                    <th scope="col" className="num">
                      Оцінка
                    </th>
                    <th scope="col" className="num">
                      Дата
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {ratings.items.map((r) => (
                    <tr key={r.item.id}>
                      <td>
                        <Link href={`/items/${r.item.id}`} prefetch={false}>
                          {r.item.title}
                        </Link>
                      </td>
                      <td className="mono">{DOMAIN_SINGULAR[r.item.domain]}</td>
                      <td className="num">{r.value} / 10</td>
                      <td className="num">{formatDate(r.rated_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination
              page={ratings.page}
              pageSize={ratings.page_size}
              total={ratings.total}
              href={href("rp")}
              label="Сторінки оцінок"
            />
          </>
        ) : (
          <Empty>
            Оцінок ще немає. <Link href="/onboarding">Почніть з добірки</Link> або оцініть твори в
            каталозі.
          </Empty>
        )}
      </Section>

      <Section number={3} title="Історія переглядів" aside={<span>Усього: {formatInt(history.total)}</span>}>
        {history.items.length ? (
          <>
            <div className="table-scroll">
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">Назва</th>
                    <th scope="col">Тип</th>
                    <th scope="col" className="num">
                      Переглянуто
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {history.items.map((h) => (
                    <tr key={h.id}>
                      <td>
                        <Link href={`/items/${h.item.id}`} prefetch={false}>
                          {h.item.title}
                        </Link>
                      </td>
                      <td className="mono">{DOMAIN_SINGULAR[h.item.domain]}</td>
                      <td className="num">{formatDateTime(h.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination
              page={history.page}
              pageSize={history.page_size}
              total={history.total}
              href={href("hp")}
              label="Сторінки історії"
            />
          </>
        ) : (
          <Empty>Ви ще не відкривали картки творів.</Empty>
        )}
      </Section>
    </>
  );
}
