type Metric = { label: string; value: string; unit?: string };

/** Key figures in one row separated by vertical rules (no cards). */
export function Metrics({ items }: { items: Metric[] }) {
  return (
    <dl className="metrics">
      {items.map((m) => (
        <div className="metric" key={m.label}>
          <dt className="mono metric-label">{m.label}</dt>
          <dd className="mono metric-value">
            {m.value}
            {m.unit ? <span className="metric-unit">{m.unit}</span> : null}
          </dd>
        </div>
      ))}
    </dl>
  );
}
