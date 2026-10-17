import { useCallback, useEffect, useState } from "react";
import EChart, { echarts } from "./EChart";
import { chartColors } from "../lib/theme";
import { short } from "../lib/format";

let mapPromise: Promise<void> | null = null;
function loadMap(): Promise<void> {
  mapPromise ??= fetch("/world.geo.json").then((r) => r.json()).then((geo) => { echarts.registerMap("world", geo); });
  return mapPromise;
}

export interface MapDatum { iso3: string; name: string; value: number | null }

/** Choropleth of one indicator by country (sequential single-hue ramp; grey = no reported result). */
export default function WorldMap({ data, label, fmt = short, height = 340 }: { data: MapDatum[]; label: string; fmt?: (v: number) => string; height?: number }) {
  const [ready, setReady] = useState(false);
  useEffect(() => { loadMap().then(() => setReady(true)); }, []);
  const option = useCallback(() => {
    const c = chartColors();
    const vals = data.map((d) => d.value).filter((v): v is number => v !== null && v > 0);
    const max = vals.length ? Math.max(...vals) : 1;
    return {
      tooltip: {
        trigger: "item", backgroundColor: c.surface, borderColor: c.axis, textStyle: { color: c.ink, fontSize: 12 },
        formatter: (p: any) => `<b>${p.data?.label ?? p.name}</b><br/>${p.value > 0 ? fmt(p.value) : "No reported result"}`,
      },
      visualMap: {
        type: "continuous", min: 0, max, left: 8, bottom: 8, itemHeight: 90, itemWidth: 10, calculable: false,
        inRange: { color: c.seq.slice(1) }, text: [short(max), "0"], textStyle: { color: c.muted, fontSize: 11 },
        outOfRange: { color: c.grid },
      },
      series: [{
        type: "map", map: "world", nameProperty: "iso3", roam: true, scaleLimit: { min: 1, max: 8 },
        top: 6, bottom: 6, emphasis: { label: { show: false }, itemStyle: { areaColor: c.series[1] } },
        select: { disabled: true },
        itemStyle: { areaColor: c.grid, borderColor: c.surface, borderWidth: 0.5 },
        data: data.map((d) => ({ name: d.iso3, value: d.value ?? 0, label: d.name })),
      }],
    };
  }, [data, fmt]);
  if (!ready) return <div style={{ height }} className="animate-pulse rounded-lg bg-surface-2" />;
  return <EChart option={option} height={height} ariaLabel={label} />;
}
