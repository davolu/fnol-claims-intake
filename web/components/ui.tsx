import { STATUS_LABEL, confClass } from "@/lib/format";

export function StatusBadge({ status }: { status: string }) {
  return <span className={`badge s-${status}`}>{STATUS_LABEL[status] ?? status}</span>;
}

export function Confidence({ value, threshold = 0.85 }: { value?: number; threshold?: number }) {
  if (value === undefined || value === null) return <span className="muted small">—</span>;
  return (
    <span className={`meter ${confClass(value, threshold)}`} title={`confidence ${value}`}>
      <span className="bar"><i style={{ width: `${Math.round(value * 100)}%` }} /></span>
      {Math.round(value * 100)}%
    </span>
  );
}

export function Kpi({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="card kpi">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {hint ? <div className="hint">{hint}</div> : null}
    </div>
  );
}
