import { useEffect, useMemo, useState } from "react";
import { ExternalLink, Sparkles } from "lucide-react";
import { api, type Country as C } from "../lib/api";
import { fmtNum } from "../lib/format";
import { shortName } from "../lib/labels";
import { href } from "../lib/route";
import { BulletBar, Card, Delta, ErrorNote, Loading } from "../components/ui";
import { useChat } from "../components/chat/ChatContext";

export default function Country({ params }: { params: Record<string, string> }) {
  const { ask } = useChat();
  const [countries, setCountries] = useState<C[]>([]);
  const [query, setQuery] = useState("");
  const code = params.c || "KE";
  const [profile, setProfile] = useState<any>(null);
  const [projects, setProjects] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => { api.countries().then(setCountries); }, []);
  useEffect(() => {
    setProfile(null); setProjects(null); setErr(null);
    api.country(code).then(setProfile).catch((e) => setErr(e.message));
    api.projects({ country: code, sort_by: "commitment", limit: 40 }).then(setProjects).catch(() => setProjects({ projects: [] }));
  }, [code]);

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? countries.filter((c) => c.country_name.toLowerCase().includes(q) || c.iso3.toLowerCase() === q).slice(0, 8) : [];
  }, [query, countries]);

  const c = profile?.country;
  const uniqueProjects = useMemo(() => {
    const seen = new Map<string, any>();
    (projects?.projects ?? []).forEach((p: any) => { if (!seen.has(p.proj_id)) seen.set(p.proj_id, { ...p, indicators: [shortName(p.ind_code, p.indicator)] }); else seen.get(p.proj_id).indicators.push(shortName(p.ind_code, p.indicator)); });
    return [...seen.values()].slice(0, 10);
  }, [projects]);

  return (
    <div className="space-y-5">
      <div className="relative max-w-md">
        <label htmlFor="country-search" className="text-xs font-medium uppercase tracking-wider text-muted">Country</label>
        <input id="country-search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search a country…"
          className="mt-1 w-full rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent" autoComplete="off" />
        {matches.length > 0 && (
          <ul className="absolute z-10 mt-1 w-full overflow-hidden rounded-xl border border-line bg-surface shadow-lg">
            {matches.map((m) => (
              <li key={m.country_code}>
                <a href={href("country", { c: m.country_code })} onClick={() => setQuery("")} className="flex justify-between px-3 py-2 text-sm hover:bg-surface-2">
                  <span className="text-ink">{m.country_name}</span><span className="text-xs text-muted">{m.region_code}</span>
                </a>
              </li>
            ))}
          </ul>
        )}
      </div>

      {err && <ErrorNote error={err} />}
      {!profile && !err && <Loading h={300} />}
      {profile && (
        <>
          <section className="card flex flex-col gap-4 p-5 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h1 className="text-2xl font-semibold tracking-tight text-ink">{c.country_name}</h1>
              <div className="mt-2 flex flex-wrap gap-1.5 text-xs">
                {[c.region_name, `${c.income_name} income`, c.lending_eligibility && `${c.lending_eligibility} eligible`, c.is_fcs && "Fragile & conflict-affected", c.is_sids && "Small island state", c.is_ldc && "Least developed"]
                  .filter(Boolean).map((t: string) => <span key={t} className="chip px-2 py-0.5 text-ink-2">{t}</span>)}
              </div>
              <p className="mt-2 text-xs text-muted">{profile.world_bank_projects_reporting} World Bank projects report Scorecard results here (FY{profile.snapshot_fy} snapshot).</p>
            </div>
            <button onClick={() => ask(`What has the World Bank Group achieved in ${c.country_name}, and where are the biggest needs compared with other client countries?`)}
              className="inline-flex items-center gap-1.5 self-start rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white sm:self-auto"><Sparkles className="h-3.5 w-3.5" /> Ask about {c.country_name}</button>
          </section>

          <div className="grid gap-5 xl:grid-cols-5">
            <Card className="xl:col-span-3" title="WBG results in this country" subtitle={`Whole World Bank Group, FY${profile.snapshot_fy} snapshot. Bar: achieved (dark) against expected (light). ▲▼ vs previous snapshot.`}>
              {profile.wbg_results.length === 0 ? <p className="text-sm text-muted">No reported WBG results for this country.</p> : (
                <ul className="divide-y divide-line">
                  {profile.wbg_results.map((r: any) => (
                    <li key={r.ind_code} className="grid grid-cols-1 gap-1.5 py-2.5 sm:grid-cols-[minmax(0,1fr)_7rem_8.5rem] sm:items-center sm:gap-3">
                      <a href={href("explore", { ind: r.ind_code })} className="text-sm text-ink hover:text-accent-ink">{shortName(r.ind_code, r.name)}</a>
                      <BulletBar achieved={r.achieved} expected={r.expected} />
                      <span className="flex items-center justify-end gap-1.5 whitespace-nowrap text-sm tabular text-ink">{fmtNum(r.achieved ?? r.expected, r.unit)} <Delta from={r.achieved_prev_snapshot} to={r.achieved} unit={r.unit} title="Change vs previous snapshot (indicative)" /></span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
            <Card className="xl:col-span-2" title="The context: conditions in the country" subtitle="Latest available year, compared with all WBG client countries. Not WBG results.">
              <ul className="divide-y divide-line">
                {profile.client_context.map((r: any) => {
                  const better = r.all_client_countries_value === null ? null : r.better_when === "lower" ? r.country_value <= r.all_client_countries_value : r.country_value >= r.all_client_countries_value;
                  return (
                    <li key={r.ind_code} className="py-2">
                      <div className="text-xs text-ink-2">{r.name}</div>
                      <div className="mt-0.5 flex items-baseline justify-between gap-2 text-sm">
                        <span className="font-semibold tabular text-ink">{fmtNum(r.country_value, r.unit)} <span className="text-[11px] font-normal text-muted">({r.obs_year})</span></span>
                        {r.all_client_countries_value !== null && (
                          <span className="text-xs tabular" style={{ color: better ? "var(--good)" : "var(--bad)" }}>
                            {better ? "better" : "worse"} than all clients ({fmtNum(r.all_client_countries_value, r.unit)})
                          </span>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ul>
            </Card>
          </div>

          <Card title="World Bank projects reporting results" subtitle="Largest by commitment. IBRD/IDA only. Links open the official project page.">
            {!projects ? <Loading h={120} /> : uniqueProjects.length === 0 ? <p className="text-sm text-muted">No project-level results for this country.</p> : (
              <ul className="grid gap-3 md:grid-cols-2">
                {uniqueProjects.map((p: any) => (
                  <li key={p.proj_id} className="rounded-xl border border-line p-3">
                    <a href={p.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-sm font-medium text-ink hover:text-accent-ink">{p.project_name} <ExternalLink className="h-3 w-3 text-muted" /></a>
                    <div className="mt-1 text-xs text-muted">{p.proj_id} · FY{p.approval_fy}–FY{p.closing_fy} · {p.status === "A" ? "Active" : "Closed"} · {fmtNum(p.commitment_usd, "USD")} committed</div>
                    <div className="mt-1.5 flex flex-wrap gap-1">{[...new Set(p.indicators as string[])].map((t) => <span key={t} className="chip px-2 py-0.5 text-[11px] text-ink-2">{t}</span>)}</div>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
