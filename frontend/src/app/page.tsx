import Link from "next/link";

import { ItemGrid } from "@/components/ItemGrid";
import { Metrics } from "@/components/Metrics";
import { Empty, Notice, Section } from "@/components/Section";
import { apiGet, getMe } from "@/lib/api";
import { DOMAIN_LABEL, DOMAINS, formatInt, ONBOARDING_TARGET, query } from "@/lib/format";
import type { Domain, ItemSummary, Page, RecommendationItem, UserProfile } from "@/lib/types";

const PREVIEW = 6;

function Pipeline() {
  return (
    <dl className="pipeline">
      <dt>ALS</dt>
      <dd>Колаборативна фільтрація: що оцінили люди зі схожими смаками.</dd>
      <dt>BGE-M3</dt>
      <dd>Контентна модель: ембединги назв, жанрів, тегів і анотацій, пошук у pgvector.</dd>
      <dt>Гібрид</dt>
      <dd>Зважене злиття: що більше ваших оцінок, то більша вага ALS.</dd>
      <dt>Qwen3 8B</dt>
      <dd>Локальна мовна модель переранжовує кандидатів і пояснює кожну рекомендацію.</dd>
    </dl>
  );
}

async function GuestHome() {
  const popular = await Promise.all(
    DOMAINS.map((domain) =>
      apiGet<Page<ItemSummary>>(`/items${query({ domain, sort: "popular", page_size: PREVIEW })}`),
    ),
  );

  return (
    <>
      <h1 className="page-title">Що подивитися або почитати</h1>
      <Section number={1} title="Як це працює">
        <p style={{ marginTop: 0, maxWidth: "72ch" }}>
          Вебплатформа рекомендує фільми й книги на основі ваших оцінок та історії переглядів. Усі
          обчислення, включно з мовною моделлю, виконуються локально.
        </p>
        <Pipeline />
        <div className="actions">
          <Link href="/register" className="btn btn-primary">
            Створити профіль
          </Link>
          <Link href="/catalog" className="btn">
            Переглянути каталог
          </Link>
        </div>
      </Section>
      {DOMAINS.map((domain, i) => (
        <Section
          key={domain}
          number={i + 2}
          title={`Популярні ${DOMAIN_LABEL[domain].toLowerCase()}`}
          aside={<Link href={`/catalog${query({ domain })}`}>Увесь каталог</Link>}
        >
          {popular[i].items.length ? (
            <ItemGrid items={popular[i].items} />
          ) : (
            <Empty>Каталог порожній.</Empty>
          )}
        </Section>
      ))}
    </>
  );
}

async function UserHome({ me }: { me: UserProfile }) {
  const recs = await Promise.all(
    DOMAINS.map((domain) =>
      apiGet<RecommendationItem[]>(`/recommendations${query({ domain, k: PREVIEW })}`),
    ),
  );
  const total = me.rating_counts.movie + me.rating_counts.book;
  const byDomain = Object.fromEntries(DOMAINS.map((d, i) => [d, recs[i]])) as Record<
    Domain,
    RecommendationItem[]
  >;

  return (
    <>
      <h1 className="page-title">Вітаємо, {me.display_name}</h1>
      <Section number={1} title="Ваш профіль">
        <Metrics
          items={[
            { label: "Оцінено фільмів", value: formatInt(me.rating_counts.movie) },
            { label: "Оцінено книг", value: formatInt(me.rating_counts.book) },
            { label: "Усього оцінок", value: formatInt(total) },
          ]}
        />
      </Section>
      {total < ONBOARDING_TARGET ? (
        <Notice tone="warn">
          Оцінок поки замало для точних рекомендацій. <Link href="/onboarding">Оцініть ще{" "}
          {ONBOARDING_TARGET - total}</Link>, і список стане персональним.
        </Notice>
      ) : null}
      {DOMAINS.map((domain, i) => (
        <Section
          key={domain}
          number={i + 2}
          title={`Рекомендовані ${DOMAIN_LABEL[domain].toLowerCase()}`}
          aside={
            <Link href={`/recommendations${query({ domain })}`}>З поясненнями</Link>
          }
        >
          {byDomain[domain].length ? (
            <ItemGrid items={byDomain[domain].map((r) => r.item)} />
          ) : (
            <Empty>Рекомендацій поки немає.</Empty>
          )}
        </Section>
      ))}
    </>
  );
}

export default async function HomePage() {
  const me = await getMe();
  return me ? <UserHome me={me} /> : <GuestHome />;
}
