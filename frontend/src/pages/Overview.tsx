import { useEffect, useMemo, useState } from "react";
import { ArrowRight, Sparkles } from "lucide-react";
import { api, type OverviewItem } from "../lib/api";
import { fmtNum, pct } from "../lib/format";
import { shortName } from "../lib/labels";
import { href } from "../lib/route";
import { BulletBar, Delta, ErrorNote, Loading } from "../components/ui";
import { useChat } from "../components/chat/ChatContext";

function Eyebrow({ text }: { text: string }) {
  return <div className="mb-1 truncate text-[10px] font-semibold uppercase tracking-wider text-muted" title={text}>{text}</div>;
}

function IndicatorCard({ it }: { it: OverviewItem }) {
  const { ask } = useChat();
  const name = shortName(it.ind_code, it.name);
  if (!it.has_data)
    return (
      <div className="card flex flex-col p-4 opacity-70">
        <Eyebrow text={it.outcome_area} />
        <div className="text-sm font-medium text-ink">{name}</div>
        <div className="mt-3 text-xs text-muted">No published data yet</div>
      </div>
    );
  const expectedOnly = it.achieved === null || it.achieved === undefined;
  const headline = expectedOnly ? it.expected : it.achieved;
  return (
    <a href={href("explore", { ind: it.ind_code })} className="card group flex flex-col p-4 transition hover:border-accent hover:shadow-sm">
      <Eyebrow text={it.outcome_area} />
      <div className="text-sm font-medium leading-snug text-ink">{name}</div>
      <div className="mt-2 flex items-baseline gap-2">
        <span className="text-2xl font-semibold tracking-tight text-ink">{fmtNum(headline, it.unit)}</span>
        {expectedOnly ? <span className="text-xs text-muted">expected</span>
          : <Delta from={it.achieved_first} to={it.achieved} unit={it.unit} />}
      </div>
      {!expectedOnly && it.expected ? (
        <div className="mt-2 space-y-1">
          <BulletBar achieved={it.achieved} expected={it.expected} />
          <div className="text-[11px] text-muted tabular">{pct((it.achieved ?? 0) / it.expected)} of {fmtNum(it.expected, it.unit)} expected</div>
        </div>
      ) : <div className="mt-2 text-[11px] text-muted">Achieved results not yet reported</div>}
      <div className="mt-auto flex items-center justify-between pt-3 text-xs">
        <span className="inline-flex items-center gap-1 font-medium text-accent-ink">Explore <ArrowRight className="h-3 w-3 transition group-hover:translate-x-0.5" /></span>
        <button onClick={(e) => { e.preventDefault(); ask(`Tell me about WBG results on "${name}": where are they largest, how have they changed since FY2024, and how do they compare with needs?`); }}
          className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-ink-2 hover:bg-surface-2" aria-label={`Ask about ${name}`}>
          <Sparkles className="h-3 w-3" /> Ask
        </button>
      </div>
    </a>
  );
}

export default function Overview({ latest }: { latest: number }) {
  const [items, setItems] = useState<OverviewItem[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const { ask } = useChat();
  useEffect(() => { api.overview().then(setItems).catch((e) => setErr(e.message)); }, []);
  const groups = useMemo(() => {
    const g = new Map<string, OverviewItem[]>();
    (items ?? []).forEach((it) => g.set(it.outcome_area, [...(g.get(it.outcome_area) ?? []), it]));
    return [...g.entries()];
  }, [items]);

  return (
    <div className="space-y-8">
      <section className="card overflow-hidden p-6 sm:p-8" style={{ background: "linear-gradient(135deg, var(--surface) 0%, var(--accent-soft) 160%)" }}>
        <p className="text-xs font-medium uppercase tracking-wider text-accent-ink">World Bank Group Corporate Scorecard · FY{latest} snapshot</p>
        <h1 className="mt-2 max-w-2xl text-3xl font-semibold tracking-tight text-ink sm:text-4xl">What has the World Bank Group delivered, and where?</h1>
        <p className="mt-3 max-w-2xl text-sm text-ink-2 sm:text-base">
          Explore results from projects financed by IBRD, IDA, IFC and MIGA across 15 outcome areas, compare them with needs in client countries,
          or simply ask a question.
        </p>
        <form onSubmit={(e) => { e.preventDefault(); if (q.trim()) { ask(q); setQ(""); } }} className="mt-5 flex max-w-xl items-center gap-2 rounded-2xl border border-line bg-surface p-1.5 pl-4 shadow-sm">
          <Sparkles className="h-4 w-4 shrink-0 text-accent" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. Which regions made the most progress in digital access?"
            className="min-w-0 flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-muted" aria-label="Ask a question" />
          <button className="rounded-xl bg-accent px-3.5 py-2 text-sm font-medium text-white">Ask</button>
        </form>
      </section>

      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-ink">Headline results by outcome area</h2>
          <p className="text-sm text-ink-2">Whole World Bank Group, all countries, FY{latest} snapshot. Click any result to explore it.</p>
        </div>
        <div className="flex items-center gap-4 text-xs text-ink-2">
          <span className="inline-flex items-center gap-1.5"><span className="h-2 w-5 rounded-full" style={{ background: "var(--series-1)" }} /> Achieved (delivered so far)</span>
          <span className="inline-flex items-center gap-1.5"><span className="h-2 w-5 rounded-full" style={{ background: "var(--series-1-soft)" }} /> Expected (over project lifetimes)</span>
          <span className="inline-flex items-center gap-1"><span style={{ color: "var(--good)" }}>▲</span> change since FY2024</span>
        </div>
      </div>

      {err && <ErrorNote error={err} />}
      {!items && !err && <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{Array.from({ length: 6 }, (_, i) => <Loading key={i} h={150} />)}</div>}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {groups.flatMap(([, its]) => its).map((it) => <IndicatorCard key={it.ind_code} it={it} />)}
      </div>
      <p className="text-xs text-muted">
        Changes between snapshots are indicative. <a className="underline" href={href("about")}>About the data</a>
      </p>
    </div>
  );
}
