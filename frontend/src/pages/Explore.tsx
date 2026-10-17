import { useCallback, useEffect, useMemo, useState } from "react";
import { ExternalLink, Sparkles } from "lucide-react";
import { api, type Indicator, type ResultsResponse } from "../lib/api";
import { fmtNum, INSTITUTIONS, pct, unitLabel } from "../lib/format";
import { NEED, REGION_SHORT, shortName } from "../lib/labels";
import { href } from "../lib/route";
import { BulletBar, Card, Delta, ErrorNote, Loading, Segmented, Stat } from "../components/ui";
import EChart from "../components/EChart";
import { barOption } from "../components/chartOptions";
import WorldMap from "../components/WorldMap";
import { useChat } from "../components/chat/ChatContext";
import { chartColors } from "../lib/theme";

type Inst = "WBG" | "WB" | "IFC" | "MIGA" | "IBRD" | "IDA";

export default function Explore({ params, snapshots }: { params: Record<string, string>; snapshots: number[] }) {
  const { ask } = useChat();
  const [indicators, setIndicators] = useState<Indicator[]>([]);
  const code = params.ind || "CSC_RES_ELC_ACCS";
  const [inst, setInst] = useState<Inst>("WBG");
  const latest = snapshots.at(-1) ?? 2026;
  const [fy, setFy] = useState<number>(latest);
  const [data, setData] = useState<{ region?: ResultsResponse; country?: ResultsResponse; income?: ResultsResponse; fcs?: ResultsResponse; trend?: ResultsResponse; inst?: ResultsResponse }>({});
  const [need, setNeed] = useState<any>(null);
  const [projects, setProjects] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => { api.indicators().then((xs) => setIndicators(xs.filter((x) => x.tier === "WBG Results"))); }, []);
  const ind = indicators.find((i) => i.ind_code === code);
  const unit = ind?.unit ?? "";
  const fmt = useCallback((v: number) => fmtNum(v, unit), [unit]);

  useEffect(() => {
    setErr(null); setData({});
    const p = { institution: inst, snapshot_fy: fy };
    Promise.all([
      api.results(code, { ...p, breakdown: "region" }), api.results(code, { ...p, breakdown: "country", top_n: 250 }),
      api.results(code, { ...p, breakdown: "income" }), api.results(code, { ...p, breakdown: "fcs" }),
      api.results(code, { institution: inst, breakdown: "global", compare_snapshots: true }), api.results(code, { breakdown: "institution", snapshot_fy: fy }),
    ]).then(([region, country, income, fcs, trend, instRes]) => setData({ region, country, income, fcs, trend, inst: instRes }))
      .catch((e) => setErr(e.message));
  }, [code, inst, fy]);

  useEffect(() => {
    setNeed(null); setProjects(null);
    const needCode = NEED[code];
    if (needCode) api.context(needCode, ["AFE", "AFW", "EAP", "ECA", "LCR", "MENAAP", "SAR", "global"]).then(setNeed).catch(() => setNeed(null));
    api.projects({ ind_code: code, sort_by: "expected", limit: 8 }).then(setProjects).catch(() => setProjects(null));
  }, [code]);

  const globalRow = data.trend?.rows[0];
  const latestG = data.region?.global_total;
  const firstFy = snapshots[0];

  const regionChart = useMemo(() => {
    const rows = (data.region?.rows ?? []).filter((r) => r.area_code !== "MNA" || fy === 2024);
    return { rows, option: barOption(rows.map((r) => REGION_SHORT[r.area_code] ?? r.area_name),
      [{ name: "Expected", values: rows.map((r) => r.expected ?? null), color: chartColors().soft }, { name: "Achieved", values: rows.map((r) => r.achieved ?? null), color: chartColors().series[0] }],
      { horizontal: true, fmt, overlay: true }) };
  }, [data.region, fmt, fy]);

  const trendChart = useMemo(() => {
    const r = globalRow;
    if (!r) return null;
    return barOption(snapshots.map((s) => `FY${s}`), [
      { name: "Achieved", values: snapshots.map((s) => (r[`achieved_fy${s}`] as number) ?? null) },
      { name: "Expected", values: snapshots.map((s) => (r[`expected_fy${s}`] as number) ?? null), color: chartColors().soft },
    ], { fmt });
  }, [globalRow, snapshots, fmt]);

  const groupChart = useMemo(() => {
    const inc = (data.income?.rows ?? []).filter((r) => ["LIC", "LMC", "UMC", "HIC"].includes(r.area_code));
    const order = ["LIC", "LMC", "UMC", "HIC"];
    inc.sort((a, b) => order.indexOf(a.area_code) - order.indexOf(b.area_code));
    const fcs = (data.fcs?.rows ?? []).filter((r) => r.area_code === "FCS");
    const rows = [...inc.map((r) => ({ ...r, area_name: `${r.area_name} income` })), ...fcs.map((r) => ({ ...r, area_name: "Fragile & conflict-affected" }))];
    return { rows, option: barOption(rows.map((r) => r.area_name), [{ name: "Expected", values: rows.map((r) => r.expected ?? null), color: chartColors().soft }, { name: "Achieved", values: rows.map((r) => r.achieved ?? null), color: chartColors().series[0] }], { horizontal: true, fmt, overlay: true }) };
  }, [data.income, data.fcs, fmt]);

  const needChart = useMemo(() => {
    if (!need?.series) return null;
    // Worst first: the biggest needs sit at the top.
    const worse = need.indicator.better_when === "lower" ? -1 : 1;
    const s = (need.series as any[]).filter((x) => x.latest).sort((a, b) => worse * (a.latest.value - b.latest.value));
    return { s, option: barOption(s.map((x) => REGION_SHORT[x.area_code] ?? x.area_name), [{ name: need.indicator.name, values: s.map((x) => x.latest.value) }],
      { horizontal: true, fmt: (v) => fmtNum(v, need.indicator.unit) }) };
  }, [need]);

  const mapData = useMemo(() => (data.country?.rows ?? []).map((r) => ({ iso3: "", code: r.area_code, name: r.area_name, value: r.achieved ?? null })), [data.country]);
  const [iso, setIso] = useState<Record<string, string>>({});
  useEffect(() => { api.countries().then((cs) => setIso(Object.fromEntries(cs.map((c) => [c.country_code, c.iso3])))); }, []);
  const mapRows = useMemo(() => mapData.map((d) => ({ ...d, iso3: iso[d.code] ?? "" })).filter((d) => d.iso3), [mapData, iso]);

  const name = shortName(code, ind?.name ?? code);
  const instOptions = (["WBG", "WB", "IFC", "MIGA", "IBRD", "IDA"] as Inst[]).map((v) => ({ value: v, label: v }));
  const grouped = useMemo(() => {
    const g = new Map<string, Indicator[]>();
    indicators.forEach((i) => g.set(i.outcome_area ?? "Other", [...(g.get(i.outcome_area ?? "Other") ?? []), i]));
    return [...g.entries()];
  }, [indicators]);

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <label className="text-xs font-medium uppercase tracking-wider text-muted" htmlFor="ind">Indicator</label>
          <select id="ind" value={code} onChange={(e) => (window.location.hash = href("explore", { ind: e.target.value }))}
            className="mt-1 block w-full max-w-xl rounded-xl border border-line bg-surface px-3 py-2 text-base font-semibold text-ink">
            {grouped.map(([area, xs]) => (
              <optgroup key={area} label={area}>{xs.map((x) => <option key={x.ind_code} value={x.ind_code}>{shortName(x.ind_code, x.name)}</option>)}</optgroup>
            ))}
          </select>
          {ind && <p className="mt-1.5 max-w-3xl text-xs text-ink-2">{ind.name}. Unit: {unitLabel(unit)}. <span className="text-muted">{ind.outcome_area}</span></p>}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Segmented label="Institution" value={inst} options={instOptions} onChange={setInst} />
          <Segmented label="Snapshot" value={String(fy)} options={snapshots.map((s) => ({ value: String(s), label: `FY${s}` }))} onChange={(v) => setFy(Number(v))} />
          <button onClick={() => ask(`Tell me about ${INSTITUTIONS[inst]} results on "${name}" (FY${fy} snapshot): where are they largest, how have they changed since FY2024, and how do they compare with needs?`)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white"><Sparkles className="h-3.5 w-3.5" /> Ask about this</button>
        </div>
      </div>

      {err && <ErrorNote error={err} />}

      <Card>
        <div className="grid grid-cols-2 gap-5 md:grid-cols-4">
          <Stat label={`Achieved · ${INSTITUTIONS[inst]}`} value={latestG ? fmtNum(latestG.achieved, unit) : "…"} hint="delivered so far" />
          <Stat label="Expected" value={latestG ? fmtNum(latestG.expected, unit) : "…"} hint="over project lifetimes" />
          <Stat label="Share delivered so far" value={latestG?.expected ? pct((latestG.achieved ?? 0) / latestG.expected) : "–"} hint="not a performance grade" />
          <Stat label={`Change since FY${firstFy}`} value={globalRow ? (globalRow[`achieved_fy${firstFy}`] ? <Delta from={globalRow[`achieved_fy${firstFy}`] as number} to={globalRow[`achieved_fy${latest}`] as number} unit={unit} /> : "–") : "…"}
            hint={globalRow ? `${fmtNum(globalRow[`achieved_fy${firstFy}`] as number, unit)} → ${fmtNum(globalRow[`achieved_fy${latest}`] as number, unit)}` : undefined} />
        </div>
      </Card>

      <Card title="Where results are reported" subtitle={`Achieved results by country, ${INSTITUTIONS[inst]}, FY${fy}. Grey = no reported result. Multi-country projects are not shown on the map. Scroll to zoom.`}>
        {data.country ? <WorldMap data={mapRows} label={`Map of ${name} by country`} fmt={fmt} /> : <Loading h={340} />}
      </Card>

      <div className="grid gap-5 xl:grid-cols-2">
        <Card title="By region" subtitle="Achieved (dark) against expected (light)">
          {data.region ? <EChart option={regionChart.option} height={Math.max(220, regionChart.rows.length * 34 + 50)} ariaLabel={`${name} by region`} /> : <Loading h={260} />}
        </Card>
        <Card title="Over time" subtitle={`All countries, ${INSTITUTIONS[inst]}, by snapshot (changes are indicative)`}>
          {trendChart ? <EChart option={trendChart} height={260} ariaLabel={`${name} over time`} /> : <Loading h={260} />}
        </Card>
        <Card title="Income groups and fragile states" subtitle="Achieved (dark) against expected (light)">
          {data.income ? <EChart option={groupChart.option} height={Math.max(200, groupChart.rows.length * 34 + 50)} ariaLabel={`${name} by income group`} /> : <Loading h={220} />}
        </Card>
        <Card title="Which institutions deliver it" subtitle={`All countries, FY${fy}. Rows overlap: WBG includes WB, IFC and MIGA; WB includes IBRD and IDA.`}>
          {data.inst ? (
            <ul className="space-y-2.5">
              {data.inst.rows.filter((r) => r.area_code !== "IDA-21").map((r) => (
                <li key={r.area_code} className="grid grid-cols-[11.5rem_1fr_6rem] items-center gap-3 text-sm">
                  <span className="truncate text-ink-2">{INSTITUTIONS[r.area_code] ?? r.area_code}</span>
                  <BulletBar achieved={r.achieved} expected={r.expected} max={Math.max(...data.inst!.rows.map((x) => x.expected ?? x.achieved ?? 0))} />
                  <span className="text-right text-xs tabular text-ink">{fmtNum(r.achieved ?? r.expected, unit)}</span>
                </li>
              ))}
            </ul>
          ) : <Loading h={180} />}
        </Card>
      </div>

      {needChart && (
        <Card title={`The need: ${need.indicator.name}`} subtitle={`Client Context, latest year per region (${need.indicator.better_when} is better). Conditions in countries, shaped by everyone, not only WBG projects.`}>
          <EChart option={needChart.option} height={Math.max(220, needChart.s.length * 32 + 30)} ariaLabel="Client context by region" />
        </Card>
      )}

      <Card title="Largest World Bank projects contributing" subtitle="IBRD/IDA projects by expected contribution, latest snapshot. IFC and MIGA do not report project-level results.">
        {!projects ? <Loading h={160} /> : projects.projects.length === 0 ? <p className="text-sm text-muted">No project-level data for this indicator.</p> : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="text-left text-xs text-muted">
                <th className="pb-2 pr-3 font-medium">Project</th><th className="pb-2 pr-3 font-medium">Country</th>
                <th className="pb-2 pr-3 text-right font-medium">Achieved</th><th className="pb-2 pr-3 text-right font-medium">Expected</th><th className="pb-2 text-right font-medium">Closes</th>
              </tr></thead>
              <tbody>
                {projects.projects.map((p: any) => (
                  <tr key={p.proj_id} className="border-t border-line">
                    <td className="py-2 pr-3"><a href={p.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-medium text-ink hover:text-accent-ink">{p.project_name} <ExternalLink className="h-3 w-3 text-muted" /></a></td>
                    <td className="py-2 pr-3 text-ink-2">{p.country ?? p.region}</td>
                    <td className="py-2 pr-3 text-right tabular">{fmtNum(p.achieved, unit)}</td>
                    <td className="py-2 pr-3 text-right tabular">{fmtNum(p.expected, unit)}</td>
                    <td className="py-2 text-right tabular text-ink-2">FY{p.closing_fy}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {data.region && <p className="text-xs text-muted">{data.region.notes.join(" ")}</p>}
    </div>
  );
}
