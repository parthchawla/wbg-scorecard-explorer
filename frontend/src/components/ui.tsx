import type { ReactNode } from "react";
import { pct } from "../lib/format";

export function Card({ title, subtitle, actions, children, className = "" }: { title?: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card p-4 sm:p-5 ${className}`}>
      {(title || actions) && (
        <header className="mb-3 flex items-start justify-between gap-3">
          <div>
            {title && <h2 className="text-[0.95rem] font-semibold text-ink">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-muted">{subtitle}</p>}
          </div>
          {actions}
        </header>
      )}
      {children}
    </section>
  );
}

/** Achieved vs expected as a bullet bar: light track = expected, solid fill = achieved. */
export function BulletBar({ achieved, expected, max, height = 8 }: { achieved: number | null | undefined; expected: number | null | undefined; max?: number; height?: number }) {
  const m = max ?? Math.max(achieved ?? 0, expected ?? 0, 1);
  const a = Math.max(0, Math.min(1, (achieved ?? 0) / m));
  const e = Math.max(0, Math.min(1, (expected ?? 0) / m));
  return (
    <div className="relative w-full rounded-full" style={{ height, background: "var(--surface-2)" }} aria-hidden>
      <div className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${e * 100}%`, background: "var(--series-1-soft)" }} />
      <div className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${a * 100}%`, background: "var(--series-1)" }} />
    </div>
  );
}

export function Delta({ from, to, title, unit = "" }: { from: number | null | undefined; to: number | null | undefined; title?: string; unit?: string }) {
  if (from === null || from === undefined || to === null || to === undefined || from === 0) return null;
  if (unit.toLowerCase().includes("percent")) {
    // Rates change in percentage points, not relative percent.
    const pp = to - from;
    if (Math.abs(pp) < 0.05) return <span className="text-xs text-muted" title={title}>≈ no change</span>;
    return (
      <span title={title ?? "Change since the FY2024 snapshot, in percentage points (indicative)"} className="inline-flex items-center gap-0.5 text-xs font-medium tabular"
        style={{ color: pp >= 0 ? "var(--good)" : "var(--bad)" }}>{pp >= 0 ? "▲" : "▼"} {Math.abs(pp).toFixed(1)} pts</span>
    );
  }
  const change = (to - from) / Math.abs(from);
  if (Math.abs(change) < 0.005) return <span className="text-xs text-muted" title={title}>≈ no change</span>;
  const up = change >= 0;
  return (
    <span title={title ?? "Change in achieved results since the FY2024 snapshot (indicative)"}
      className="inline-flex items-center gap-0.5 text-xs font-medium tabular" style={{ color: up ? "var(--good)" : "var(--bad)" }}>
      {up ? "▲" : "▼"} {pct(Math.abs(change))}
    </span>
  );
}

export function Segmented<T extends string>({ value, options, onChange, label }: { value: T; options: { value: T; label: string }[]; onChange: (v: T) => void; label: string }) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex flex-wrap rounded-lg bg-surface-2 p-0.5 text-xs">
      {options.map((o) => (
        <button key={o.value} role="radio" aria-checked={value === o.value} onClick={() => onChange(o.value)}
          className={`rounded-md px-2.5 py-1 font-medium transition ${value === o.value ? "bg-surface text-ink shadow-sm" : "text-ink-2 hover:text-ink"}`}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="text-xs text-muted">{label}</div>
      <div className="mt-0.5 truncate text-2xl font-semibold tracking-tight text-ink">{value}</div>
      {hint && <div className="mt-0.5 text-xs text-ink-2">{hint}</div>}
    </div>
  );
}

export function Loading({ h = 160 }: { h?: number }) {
  return <div className="animate-pulse rounded-lg bg-surface-2" style={{ height: h }} />;
}

export function ErrorNote({ error }: { error: string }) {
  return <div className="rounded-lg px-3 py-2 text-sm" style={{ background: "var(--warn-bg)", color: "var(--warn-ink)" }}>{error}</div>;
}
