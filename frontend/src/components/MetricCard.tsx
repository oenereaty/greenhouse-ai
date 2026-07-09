import type { ReactNode } from "react";

export function MetricCard({
  label,
  value,
  delta,
  hint,
  warn,
}: {
  label: string;
  value: string;
  delta?: string;
  hint?: string;
  warn?: boolean;
}) {
  return (
    <div className="card" style={{ padding: "15px 17px", minWidth: 0 }} title={hint}>
      <div style={{ fontSize: 20.5, color: "var(--color-text-muted)", marginBottom: 4 }}>
        {label}
        {warn && <span style={{ color: "var(--color-warn)" }}> ⚠</span>}
      </div>
      <div style={{ fontSize: 30, fontWeight: 900, fontVariantNumeric: "tabular-nums", letterSpacing: "-0.02em", overflowWrap: "break-word" }}>{value}</div>
      {delta && <div style={{ fontSize: 20, color: "var(--color-text-muted)", marginTop: 2 }}>{delta}</div>}
    </div>
  );
}

export function MetricGrid({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
        gap: 12,
        minWidth: 0,
      }}
    >
      {children}
    </div>
  );
}
