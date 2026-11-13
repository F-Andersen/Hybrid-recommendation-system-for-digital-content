import { getHealth } from "@/lib/api";

export const dynamic = "force-dynamic";

type Row = { label: string; value: string; state: "ok" | "warn" | "error" };

export default async function HomePage() {
  const health = await getHealth();

  const rows: Row[] = health
    ? [
        {
          label: "База даних",
          value: health.db.ok ? "підключено" : (health.db.error ?? "помилка"),
          state: health.db.ok ? "ok" : "error",
        },
        {
          label: "pgvector",
          value: health.db.pgvector ? "увімкнено" : "не встановлено — виконайте міграції",
          state: health.db.pgvector ? "ok" : "warn",
        },
        {
          label: "Ollama",
          value: health.ollama.ok ? "доступний" : (health.ollama.error ?? "недоступний"),
          state: health.ollama.ok ? "ok" : "error",
        },
        ...health.ollama.models_required.map<Row>((m) => {
          const missing = health.ollama.models_missing.includes(m);
          return {
            label: `Модель ${m}`,
            value: missing ? `відсутня — ollama pull ${m}` : "завантажена",
            state: missing ? "warn" : "ok",
          };
        }),
        ...Object.entries(health.als_loaded).map<Row>(([domain, loaded]) => ({
          label: `ALS · ${domain}`,
          value: loaded ? "завантажено" : "не навчено",
          state: loaded ? "ok" : "warn",
        })),
      ]
    : [{ label: "API", value: "недоступний", state: "error" }];

  return (
    <section className="panel">
      <h1 className="section-title">
        <span className="mono">01</span> Стан системи
      </h1>
      <table className="table">
        <thead>
          <tr>
            <th scope="col">Компонент</th>
            <th scope="col">Стан</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.label}>
              <td>{r.label}</td>
              <td className={`mono status-${r.state}`}>{r.value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
