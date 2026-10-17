import { useMemo } from "react";
import EChart from "../EChart";
import { barOption, lineOption } from "../chartOptions";
import type { ChartSpec } from "../../lib/chat";
import { round } from "../../lib/format";

/** Renders a chart the assistant asked for via the make_chart tool. */
export default function ChatChart({ spec: raw }: { spec: ChartSpec }) {
  // The chat panel is narrow: vertical bars with several long category names would overlap, so
  // show them as horizontal bars instead (same data, readable labels).
  const spec = useMemo<ChartSpec>(() => {
    const longLabels = raw.categories.length > 3 && Math.max(...raw.categories.map((c) => c.length)) > 10;
    if (longLabels && (raw.chart_type === "bar" || raw.chart_type === "grouped_bar")) return { ...raw, chart_type: "horizontal_bar" };
    return raw;
  }, [raw]);
  const option = useMemo(() => {
    const fmt = (v: number) => `${round(v, Math.abs(v) < 10 ? 2 : 1)} ${spec.unit ?? ""}`.trim();
    const series = spec.series.map((s) => ({ name: s.name, values: s.values }));
    if (spec.chart_type === "line") return lineOption(spec.categories, series, { fmt });
    return barOption(spec.categories, series, {
      horizontal: spec.chart_type === "horizontal_bar", stacked: spec.chart_type === "stacked_bar", fmt,
    });
  }, [spec]);
  const horizontal = spec.chart_type === "horizontal_bar";
  const height = horizontal ? Math.max(180, spec.categories.length * 30 + 60) : 260;
  return (
    <figure className="my-3 rounded-xl border border-line bg-surface p-3">
      <figcaption className="mb-1">
        <div className="text-sm font-semibold text-ink">{spec.title}</div>
        <div className="text-xs text-muted">{[spec.subtitle, spec.unit && `Unit: ${spec.unit}`].filter(Boolean).join(" · ")}</div>
      </figcaption>
      <EChart option={option} height={height} ariaLabel={spec.title} />
      {spec.source_note && <div className="mt-1 text-[11px] text-muted">{spec.source_note}</div>}
    </figure>
  );
}
