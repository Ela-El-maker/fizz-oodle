export function KeyValueList({ rows }: { rows: Array<{ label: string; value: string }> }) {
  if (rows.length === 0) {
    return <div className="text-sm text-muted">No data available.</div>;
  }

  return (
    <dl className="grid gap-2">
      {rows.map((row) => (
        <div key={row.label} className="grid grid-cols-[auto_1fr] gap-x-4 rounded-lg border border-line bg-panel-soft px-3 py-2">
          <dt className="text-xs uppercase tracking-wide text-ink-faint">{row.label}</dt>
          <dd className="text-right text-sm text-ink">{row.value}</dd>
        </div>
      ))}
    </dl>
  );
}
