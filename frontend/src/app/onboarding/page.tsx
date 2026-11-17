import type { Metadata } from "next";

import { OnboardingBoard } from "@/components/OnboardingBoard";
import { Empty, Section } from "@/components/Section";
import { Tabs } from "@/components/Tabs";
import { apiGet, requireUser } from "@/lib/api";
import { DOMAIN_LABEL, DOMAINS, pickDomain, query } from "@/lib/format";
import type { ItemSummary } from "@/lib/types";

export const metadata: Metadata = { title: "Перші оцінки" };

type Props = { searchParams: Promise<Record<string, string | string[] | undefined>> };

export default async function OnboardingPage({ searchParams }: Props) {
  const params = await searchParams;
  const domain = pickDomain(params);
  const me = await requireUser(`/onboarding${query({ domain })}`);
  const items = await apiGet<ItemSummary[]>(`/onboarding/items${query({ domain, k: 20 })}`);
  const rated = me.rating_counts.movie + me.rating_counts.book;

  return (
    <>
      <h1 className="page-title">Перші оцінки</h1>
      <p className="page-lead">
        Оцініть щонайменше п&apos;ять творів, які ви бачили або читали, за шкалою від 1 до 10.
        Низькі оцінки теж корисні: вони відштовхують схожий контент. Добірка складена з популярних
        творів різних жанрів.
      </p>
      <Section
        number={1}
        title="Добірка"
        aside={
          <Tabs
            label="Тип контенту"
            tabs={DOMAINS.map((d) => ({
              href: `/onboarding${query({ domain: d })}`,
              label: DOMAIN_LABEL[d],
              active: d === domain,
            }))}
          />
        }
      >
        {items.length ? (
          // key resets local rating state when switching domains
          <OnboardingBoard key={domain} items={items} initialCount={rated} />
        ) : (
          <Empty>У цьому розділі ви вже оцінили всі запропоновані твори.</Empty>
        )}
      </Section>
    </>
  );
}
