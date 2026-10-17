import { lazy, Suspense, useState } from "react";
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, Database, Loader2, XCircle } from "lucide-react";
import type { AssistantMessage, ToolStep } from "../../lib/chat";
import Markdown from "../Markdown";
const ChatChart = lazy(() => import("./ChatChart"));

const PARAM_LABELS: Record<string, string> = {
  ind_code: "indicator", breakdown: "by", institution: "institution", snapshot_fy: "snapshot", compare_snapshots: "over time",
  series: "subset", country: "country", region: "region", keyword: "keyword", query: "search", areas: "places", sql: "SQL",
};

function paramText(input: Record<string, unknown>): string {
  return Object.entries(input).filter(([k]) => k !== "sql" && k !== "top_n" && k !== "limit" && k !== "sort_by")
    .map(([k, v]) => `${PARAM_LABELS[k] ?? k}: ${Array.isArray(v) ? v.join(", ") : String(v)}`).join(" · ");
}

function DataPreview({ data }: { data: any }) {
  const rows: any[] | undefined = data?.rows ?? data?.matches ?? data?.projects ?? data?.wbg_results ?? data?.global_totals;
  if (Array.isArray(rows) && rows.length && typeof rows[0] === "object") {
    const cols = Object.keys(rows[0]).filter((k) => !/description|url|definition/.test(k)).slice(0, 7);
    return (
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-[11px] tabular">
          <thead><tr>{cols.map((c) => <th key={c} className="border-b border-line px-1.5 py-1 text-left font-medium text-ink-2">{c}</th>)}</tr></thead>
          <tbody>
            {rows.slice(0, 12).map((r, i) => (
              <tr key={i}>{cols.map((c) => <td key={c} className="border-b border-line/60 px-1.5 py-1 text-ink-2">{fmtCell(r[c])}</td>)}</tr>
            ))}
          </tbody>
        </table>
        {rows.length > 12 && <div className="mt-1 text-[11px] text-muted">+ {rows.length - 12} more rows</div>}
      </div>
    );
  }
  return <pre className="mt-2 max-h-48 overflow-auto rounded bg-surface-2 p-2 text-[11px] text-ink-2">{JSON.stringify(data, null, 1)?.slice(0, 3000)}</pre>;
}

function fmtCell(v: unknown): string {
  if (v === null || v === undefined) return "–";
  if (typeof v === "number") return Math.abs(v) >= 1000 ? Math.round(v).toLocaleString("en-US") : String(v);
  if (typeof v === "object") return JSON.stringify(v).slice(0, 60);
  return String(v).slice(0, 60);
}

function Step({ step }: { step: ToolStep }) {
  const [open, setOpen] = useState(false);
  const icon = step.ok === undefined ? <Loader2 className="h-3.5 w-3.5 animate-spin text-accent" />
    : step.ok ? <CheckCircle2 className="h-3.5 w-3.5 text-good" /> : <XCircle className="h-3.5 w-3.5 text-bad" />;
  return (
    <li className="rounded-lg border border-line bg-surface">
      <button onClick={() => setOpen(!open)} className="flex w-full items-start gap-2 px-2.5 py-1.5 text-left" aria-expanded={open}>
        <span className="mt-0.5">{icon}</span>
        <span className="min-w-0 flex-1">
          <span className="text-xs font-medium text-ink">{step.title}</span>
          <span className="block truncate text-[11px] text-muted">{paramText(step.input)}{step.summary ? ` → ${step.summary}` : ""}</span>
        </span>
        {open ? <ChevronDown className="mt-0.5 h-3.5 w-3.5 text-muted" /> : <ChevronRight className="mt-0.5 h-3.5 w-3.5 text-muted" />}
      </button>
      {open && (
        <div className="border-t border-line px-2.5 pb-2.5 pt-1.5">
          <div className="text-[11px] text-muted">Tool <code className="text-ink-2">{step.name}</code></div>
          {typeof step.input.sql === "string" && <pre className="mt-1 overflow-x-auto rounded bg-surface-2 p-2 text-[11px] text-ink-2">{step.input.sql}</pre>}
          {step.data ? <DataPreview data={step.data} /> : step.summary && <div className="mt-1 text-[11px] text-ink-2">{step.summary}</div>}
        </div>
      )}
    </li>
  );
}

function Badge({ m }: { m: AssistantMessage }) {
  const v = m.verification;
  if (!v || m.streaming) return null;
  if (v.status === "verified")
    return <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium" style={{ background: "var(--ok-bg)", color: "var(--ok-ink)" }}
      title="Every figure in this answer matches a number returned by the data tools."><CheckCircle2 className="h-3 w-3" /> All {v.checked} figures verified against the data</span>;
  if (v.status === "unverified")
    return <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium" style={{ background: "var(--warn-bg)", color: "var(--warn-ink)" }}
      title={`Not matched: ${v.unverified.join(", ")}`}><AlertTriangle className="h-3 w-3" /> {v.unverified.length} of {v.checked} figures could not be matched to the data</span>;
  return null;
}

export default function AssistantMessageView({ m }: { m: AssistantMessage }) {
  const [showSteps, setShowSteps] = useState(false);
  const working = m.streaming && !m.text;
  const dataSteps = m.steps.filter((s) => s.name !== "make_chart");
  return (
    <div className="space-y-2">
      {(dataSteps.length > 0 || working) && (
        <div>
          <button onClick={() => setShowSteps(!showSteps)} className="inline-flex items-center gap-1.5 text-xs text-ink-2 hover:text-ink" aria-expanded={showSteps}>
            <Database className="h-3.5 w-3.5" />
            {m.streaming && !m.text ? (dataSteps.at(-1)?.title ?? "Thinking") + "…" : `How this was answered · ${dataSteps.length} data ${dataSteps.length === 1 ? "lookup" : "lookups"}`}
            {showSteps ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
          </button>
          {showSteps && (
            <div className="mt-2 space-y-1.5">
              {m.interim.map((t, i) => <p key={i} className="text-xs italic text-muted">{t}</p>)}
              <ol className="space-y-1.5">{dataSteps.map((s) => <Step key={s.id} step={s} />)}</ol>
            </div>
          )}
        </div>
      )}
      {m.revised && m.streaming && <p className="text-xs text-muted">Double-checking figures against the data…</p>}
      {working && <div className="typing text-lg leading-none text-muted" aria-label="Working"><span>•</span><span>•</span><span>•</span></div>}
      {m.charts.map((c) => <Suspense key={c.id} fallback={<div className="h-64 animate-pulse rounded-xl bg-surface-2" />}><ChatChart spec={c.spec} /></Suspense>)}
      {m.text && <Markdown text={m.text} />}
      {m.error && <div className="rounded-lg px-3 py-2 text-sm" style={{ background: "var(--warn-bg)", color: "var(--warn-ink)" }}>{m.error}</div>}
      {!m.streaming && (m.verification || m.done) && (
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <Badge m={m} />
          {m.done && <span className="text-[11px] text-muted">{m.done.seconds}s · {m.done.tool_calls} tool calls</span>}
        </div>
      )}
    </div>
  );
}
