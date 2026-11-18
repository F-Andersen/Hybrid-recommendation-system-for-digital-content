import type { Metadata } from "next";

import { Metrics } from "@/components/Metrics";
import { Empty, Notice, Section } from "@/components/Section";
import { Tabs } from "@/components/Tabs";
import { apiGet } from "@/lib/api";
import { DOMAIN_LABEL, DOMAINS, pickDomain, query } from "@/lib/format";
import type { Domain } from "@/lib/types";

export const metadata: Metadata = { title: "Оцінювання моделей" };

type ResultRow = {
  model: string;
  segment: string;
  k: number;
  metric: string;
  value: number;
  users: number;
};

type GridRow = Record<string, number> & { "ndcg@10": number };

type Summary = {
  domain: Domain;
  generated_at: string;
  seconds: number;
  split: { method: string; train: number; validation: number; test: number; users: number };
  relevance_threshold: number;
  catalog_items: number;
  test_users: number;
  cold_users: number;
  cold_threshold: number;
  cold_sim_users: number;
  cold_history: number;
  max_users: number | null;
  params: {
    grid: string;
    selection: string;
    als: { factors: number; regularization: number; iterations: number; random_state: number };
    hybrid: { alpha_max: number; n_full: number };
    validation: { als: GridRow[]; hybrid: GridRow[] };
  };
  results: ResultRow[];
  llm: {
    users: number;
    model: string;
    prompt: string;
    calls: number;
    cache_hits: number;
    fallbacks: number;
    mean_valid_choices: number;
    mean_latency_s: number | null;
  } | null;
  labels: Record<string, string>;
  files: { csv: string; charts: string[] };
};

const METRICS = [
  { key: "precision", label: "P" },
  { key: "recall", label: "R" },
  { key: "ndcg", label: "NDCG" },
] as const;

const SPLIT_LABEL: Record<string, string> = {
  temporal: "часове (останні 10 % взаємодій)",
  random: "випадкове, seed 42",
};

const CHART_ALT: Record<string, string> = {
  ndcg10: "NDCG@10 кожної моделі: повна історія та імітований холодний старт",
  by_k: "Precision, Recall і NDCG залежно від K для кожної моделі",
};

const fileUrl = (name: string) => `/api/evaluation/files/${encodeURIComponent(name)}`;
const fmt = (value: number | undefined) => (value === undefined ? "—" : value.toFixed(4));
const int = (value: number) => value.toLocaleString("uk-UA");

function lookup(rows: ResultRow[], segment: string) {
  const map = new Map<string, number>();
  for (const r of rows) {
    if (r.segment === segment) map.set(`${r.model}|${r.metric}|${r.k}`, r.value);
  }
  return map;
}

function ResultsTable({
  summary,
  segment,
  ks,
  coverage = false,
}: {
  summary: Summary;
  segment: string;
  ks: number[];
  coverage?: boolean;
}) {
  const values = lookup(summary.results, segment);
  const models = Object.keys(summary.labels).filter((m) =>
    summary.results.some((r) => r.model === m && r.segment === segment),
  );
  if (models.length === 0) return <Empty>Немає даних для цього зрізу.</Empty>;
  const columns = ks.flatMap((k) => METRICS.map((m) => ({ key: `${m.key}|${k}`, label: `${m.label}@${k}` })));
  if (coverage) columns.push({ key: "coverage|10", label: "Покриття@10" });
  const coverageValues = lookup(summary.results, "all");
  const get = (model: string, key: string) =>
    (key.startsWith("coverage") ? coverageValues : values).get(`${model}|${key}`);
  const best = new Map(
    columns.map((c) => [c.key, Math.max(...models.map((m) => get(m, c.key) ?? -1))]),
  );

  return (
    <div className="table-scroll">
      <table className="table">
        <caption className="visually-hidden">
          Метрики моделей; найкраще значення в колонці виділено жирним
        </caption>
        <thead>
          <tr>
            <th scope="col">Модель</th>
            {columns.map((c) => (
              <th scope="col" className="num" key={c.key}>
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {models.map((model) => (
            <tr key={model}>
              <th scope="row" className="row-head">
                {summary.labels[model]}
              </th>
              {columns.map((c) => {
                const value = get(model, c.key);
                const top = value !== undefined && value === best.get(c.key);
                return (
                  <td className="num" key={c.key}>
                    {top ? <strong>{fmt(value)}</strong> : fmt(value)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function GridTable({ rows, keys, limit }: { rows: GridRow[]; keys: string[]; limit: number }) {
  const sorted = [...rows].sort((a, b) => b["ndcg@10"] - a["ndcg@10"]).slice(0, limit);
  return (
    <div className="table-scroll">
      <table className="table">
        <thead>
          <tr>
            {keys.map((k) => (
              <th scope="col" className="num" key={k}>
                {k}
              </th>
            ))}
            <th scope="col" className="num">
              NDCG@10 (валідація)
            </th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((row, index) => (
            <tr key={keys.map((k) => row[k]).join("|")}>
              {keys.map((k) => (
                <td className="num" key={k}>
                  {row[k]}
                </td>
              ))}
              <td className="num">{index === 0 ? <strong>{fmt(row["ndcg@10"])}</strong> : fmt(row["ndcg@10"])}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

type Props = { searchParams: Promise<Record<string, string | string[] | undefined>> };

export default async function EvaluationPage({ searchParams }: Props) {
  const domain = pickDomain(await searchParams);
  const { domains } = await apiGet<{ domains: Record<Domain, Summary | null> }>("/evaluation/results");
  const summary = domains[domain];

  return (
    <>
      <h1 className="page-title">Оцінювання моделей</h1>
      <Tabs
        label="Набір даних"
        tabs={DOMAINS.map((d) => ({
          href: `/evaluation${query({ domain: d === "movie" ? undefined : d })}`,
          label: d === "movie" ? "Фільми · MovieLens" : "Книги · Book-Crossing",
          active: d === domain,
        }))}
      />

      {!summary ? (
        <Section number={1} title="Результати">
          <Notice tone="warn">
            Оцінювання для розділу «{DOMAIN_LABEL[domain]}» ще не виконано. Запустіть{" "}
            <code>docker compose exec api python -m scripts.evaluate --domain {domain}</code>.
          </Notice>
        </Section>
      ) : (
        <>
          <Section
            number={1}
            title="Протокол"
            aside={<span className="mono">{new Date(summary.generated_at).toLocaleString("uk-UA")}</span>}
          >
            <Metrics
              items={[
                { label: "Користувачів у тесті", value: int(summary.test_users) },
                { label: "Об'єктів каталогу", value: int(summary.catalog_items) },
                { label: "Навчальних взаємодій", value: int(summary.split.train + summary.split.validation) },
                { label: "Тестових взаємодій", value: int(summary.split.test) },
              ]}
            />
            <table className="table protocol">
              <tbody>
                <tr>
                  <th scope="row">Розбиття</th>
                  <td>{SPLIT_LABEL[summary.split.method] ?? summary.split.method}; валідація — така сама частка перед тестом</td>
                </tr>
                <tr>
                  <th scope="row">Релевантність</th>
                  <td>явна оцінка ≥ {summary.relevance_threshold} з 10 у відкладеній частині</td>
                </tr>
                <tr>
                  <th scope="row">Підбір параметрів</th>
                  <td>NDCG@10 на валідації, моделі навчені лише на навчальній частині</td>
                </tr>
                <tr>
                  <th scope="row">Фінальна перевірка</th>
                  <td>моделі перенавчені на навчальній і валідаційній частинах, один прогін на тесті</td>
                </tr>
                {summary.max_users ? (
                  <tr>
                    <th scope="row">Підвибірка</th>
                    <td className="status-warn">обмежено {summary.max_users} користувачами</td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </Section>

          <Section number={2} title="Результати на тестовій вибірці">
            <ResultsTable summary={summary} segment="all" ks={[5, 10, 20]} coverage />
            <p className="muted">
              P — Precision@K, R — Recall@K, NDCG — нормалізований дисконтований кумулятивний виграш.
              Покриття — частка каталогу, що потрапляє хоча б в один топ-10.
            </p>
          </Section>

          <Section number={3} title="Холодний старт">
            <h3 className="subhead">
              Імітація: {summary.cold_history} взаємодій в історії · {int(summary.cold_sim_users)} користувачів
            </h3>
            <ResultsTable summary={summary} segment="cold_sim" ks={[5, 10, 20]} />
            <h3 className="subhead">
              Природний зріз: менше {summary.cold_threshold} взаємодій · {int(summary.cold_users)} користувачів
            </h3>
            {summary.cold_users > 0 ? (
              <ResultsTable summary={summary} segment="cold" ks={[5, 10, 20]} />
            ) : (
              <Empty>У наборі немає користувачів із такою короткою історією.</Empty>
            )}
          </Section>

          <Section number={4} title="Переранжування Qwen3">
            {summary.llm ? (
              <>
                <Metrics
                  items={[
                    { label: "Користувачів", value: int(summary.llm.users) },
                    { label: "Відмов моделі", value: int(summary.llm.fallbacks) },
                    { label: "Валідних виборів", value: summary.llm.mean_valid_choices.toFixed(1), unit: "з 10" },
                    {
                      label: "Час відповіді",
                      value: summary.llm.mean_latency_s === null ? "кеш" : summary.llm.mean_latency_s.toFixed(1),
                      unit: summary.llm.mean_latency_s === null ? undefined : "с",
                    },
                  ]}
                />
                <ResultsTable summary={summary} segment="llm_sample" ks={[5, 10]} />
                <p className="muted">
                  Порівняння на одній підвибірці: зважений гібрид дає 30 кандидатів, {summary.llm.model}{" "}
                  обирає 10 (промпт {summary.llm.prompt}). За відмови моделі лишається порядок гібрида.
                </p>
              </>
            ) : (
              <Empty>Переранжування не запускалося (--skip-llm).</Empty>
            )}
          </Section>

          <Section number={5} title="Підібрані гіперпараметри">
            <Metrics
              items={[
                { label: "ALS · factors", value: String(summary.params.als.factors) },
                { label: "ALS · λ", value: String(summary.params.als.regularization) },
                { label: "ALS · ітерацій", value: String(summary.params.als.iterations) },
                { label: "Гібрид · α max", value: String(summary.params.hybrid.alpha_max) },
                { label: "Гібрид · n full", value: String(summary.params.hybrid.n_full) },
              ]}
            />
            <h3 className="subhead">ALS · п&apos;ять найкращих конфігурацій</h3>
            <GridTable rows={summary.params.validation.als} keys={["factors", "regularization", "iterations"]} limit={5} />
            <h3 className="subhead">Гібрид · усі конфігурації</h3>
            <GridTable rows={summary.params.validation.hybrid} keys={["alpha_max", "n_full"]} limit={20} />
          </Section>

          <Section
            number={6}
            title="Графіки"
            aside={
              <a className="btn btn-small" href={fileUrl(summary.files.csv)} download>
                CSV
              </a>
            }
          >
            {summary.files.charts.map((name) => {
              const kind = name.endsWith("_by_k.png") ? "by_k" : "ndcg10";
              return (
                <figure className="chart" key={name}>
                  {/* Static PNG produced by the evaluation script; no optimisation needed. */}
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={fileUrl(name)} alt={CHART_ALT[kind]} loading="lazy" />
                  <figcaption className="mono">{CHART_ALT[kind]}</figcaption>
                </figure>
              );
            })}
          </Section>
        </>
      )}
    </>
  );
}
