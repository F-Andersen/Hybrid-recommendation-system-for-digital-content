import type { Metadata } from "next";
import Link from "next/link";

import { RecommendationList } from "@/components/RecommendationList";
import { Empty, Notice, Section } from "@/components/Section";
import { Tabs } from "@/components/Tabs";
import { apiGet, requireUser } from "@/lib/api";
import { ApiError } from "@/lib/errors";
import {
  DOMAIN_LABEL,
  DOMAINS,
  MODEL_LABEL,
  MODELS,
  pickDomain,
  pickModel,
  query,
} from "@/lib/format";
import type { ModelName, RecommendationItem } from "@/lib/types";

export const metadata: Metadata = { title: "Рекомендації" };

const MODEL_NOTE: Record<ModelName, string> = {
  hybrid:
    "ALS і контентна модель дають по 200 кандидатів, зважене злиття відбирає 30, Qwen3 обирає 10 і пояснює вибір.",
  als: "Колаборативна фільтрація: схожість поведінки з іншими користувачами.",
  content: "Контентна модель: найближчі за змістом твори до вашого профілю ембедингів BGE-M3.",
  popular: "Базова лінія без персоналізації: найпопулярніші твори, яких ви ще не оцінили.",
};

type Props = { searchParams: Promise<Record<string, string | string[] | undefined>> };

export default async function RecommendationsPage({ searchParams }: Props) {
  const params = await searchParams;
  const domain = pickDomain(params);
  const model = pickModel(params);
  const me = await requireUser(`/recommendations${query({ domain, model })}`);

  let rows: RecommendationItem[] = [];
  let failure: string | null = null;
  try {
    rows = await apiGet<RecommendationItem[]>(`/recommendations${query({ domain, model, k: 10 })}`);
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 503) throw error;
    failure = error.message;
  }
  const rated = me.rating_counts[domain];
  const href = (d: string, m: string) =>
    `/recommendations${query({ domain: d, model: m === "hybrid" ? undefined : m })}`;

  return (
    <>
      <h1 className="page-title">Рекомендації</h1>
      <Tabs
        label="Тип контенту"
        tabs={DOMAINS.map((d) => ({ href: href(d, model), label: DOMAIN_LABEL[d], active: d === domain }))}
      />

      <Section
        number={1}
        title="Алгоритм"
        aside={
          <span>
            Ваших оцінок у розділі: <strong>{rated}</strong>
          </span>
        }
      >
        <Tabs
          label="Модель рекомендацій"
          tabs={MODELS.map((m) => ({ href: href(domain, m), label: MODEL_LABEL[m], active: m === model }))}
        />
        <p className="muted" style={{ marginBottom: 0 }}>
          {MODEL_NOTE[model]}
        </p>
      </Section>

      {rated === 0 ? (
        <Notice tone="warn">
          У розділі «{DOMAIN_LABEL[domain]}» ще немає ваших оцінок, тому список спирається на
          популярність. <Link href={`/onboarding?domain=${domain}`}>Оцінити кілька творів</Link>.
        </Notice>
      ) : null}

      <Section number={2} title={`Топ-10 · ${MODEL_LABEL[model]}`}>
        {failure ? (
          <Notice tone="error">{failure}. Навчіть модель скриптом train_als або оберіть інший алгоритм.</Notice>
        ) : rows.length ? (
          <RecommendationList
            key={`${domain}-${model}`}
            initial={rows}
            domain={domain}
            model={model}
            explain={model === "hybrid"}
          />
        ) : (
          <Empty>
            Модель не має сигналу для цього профілю. Оцініть більше творів або оберіть гібрид.
          </Empty>
        )}
      </Section>
    </>
  );
}
