// Option builders shared by dashboard and chat charts. Mark specs follow the dataviz guidance:
// thin bars with 4px rounded data ends, 2px lines, hairline grid, recessive axes, tooltip on hover,
// legend whenever there are 2+ series, one y-axis only.
import type { EChartsCoreOption } from "echarts/core";
import { chartColors } from "../lib/theme";
import { short } from "../lib/format";

export interface Series { name: string; values: (number | null)[]; color?: string }

const axisCommon = (c: ReturnType<typeof chartColors>) => ({
  axisLine: { lineStyle: { color: c.axis } },
  axisTick: { show: false },
  axisLabel: { color: c.muted, fontSize: 11 },
  splitLine: { lineStyle: { color: c.grid, width: 1 } },
});

function tooltip(c: ReturnType<typeof chartColors>, fmt: (v: number) => string) {
  return {
    trigger: "axis",
    axisPointer: { type: "shadow", shadowStyle: { color: c.grid, opacity: 0.35 } },
    backgroundColor: c.surface, borderColor: c.axis, textStyle: { color: c.ink, fontSize: 12 },
    valueFormatter: (v: number | null) => (v === null || v === undefined ? "–" : fmt(v)),
  };
}

export function barOption(categories: string[], series: Series[], opts: { horizontal?: boolean; stacked?: boolean; fmt?: (v: number) => string; overlay?: boolean } = {}): () => EChartsCoreOption {
  return () => {
    const c = chartColors();
    const fmt = opts.fmt ?? short;
    const valueAxis = { type: "value", ...axisCommon(c), axisLabel: { ...axisCommon(c).axisLabel, formatter: (v: number) => short(v) } };
    const catAxis = { type: "category", data: categories, ...axisCommon(c), splitLine: { show: false },
      axisLabel: { ...axisCommon(c).axisLabel, color: c.ink2, width: opts.horizontal ? 150 : 90, overflow: "truncate", interval: 0 } };
    const radius = opts.horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0];
    return {
      animationDuration: 400,
      grid: { left: opts.horizontal ? 8 : 8, right: 16, top: series.length > 1 ? 36 : 12, bottom: 8, containLabel: true },
      legend: series.length > 1 ? { top: 0, left: 0, icon: "roundRect", itemWidth: 12, itemHeight: 8, textStyle: { color: c.ink2, fontSize: 12 } } : undefined,
      tooltip: tooltip(c, fmt),
      xAxis: opts.horizontal ? valueAxis : catAxis,
      yAxis: opts.horizontal ? { ...catAxis, inverse: true } : valueAxis,
      series: series.map((s, i) => ({
        name: s.name, type: "bar", data: s.values, stack: opts.stacked ? "total" : undefined,
        barMaxWidth: 22, barGap: opts.overlay ? "-100%" : "20%", barCategoryGap: "35%",
        z: opts.overlay ? i + 1 : undefined,
        itemStyle: { color: s.color ?? c.series[i % c.series.length], borderRadius: opts.stacked && i < series.length - 1 ? 0 : radius,
                     borderColor: c.surface, borderWidth: opts.stacked ? 1 : 0 },
        emphasis: { focus: "series" },
      })),
    };
  };
}

export function lineOption(categories: string[], series: Series[], opts: { fmt?: (v: number) => string; yMin?: number } = {}): () => EChartsCoreOption {
  return () => {
    const c = chartColors();
    const fmt = opts.fmt ?? short;
    return {
      animationDuration: 400,
      grid: { left: 8, right: 20, top: series.length > 1 ? 36 : 12, bottom: 8, containLabel: true },
      legend: series.length > 1 ? { top: 0, left: 0, icon: "roundRect", itemWidth: 12, itemHeight: 3, textStyle: { color: c.ink2, fontSize: 12 } } : undefined,
      tooltip: { ...tooltip(c, fmt), axisPointer: { type: "line", lineStyle: { color: c.axis } } },
      xAxis: { type: "category", data: categories, boundaryGap: false, ...axisCommon(c), splitLine: { show: false } },
      yAxis: { type: "value", min: opts.yMin, ...axisCommon(c), axisLabel: { ...axisCommon(c).axisLabel, formatter: (v: number) => short(v) } },
      series: series.map((s, i) => ({
        name: s.name, type: "line", data: s.values, smooth: false, connectNulls: true,
        lineStyle: { width: 2, color: s.color ?? c.series[i % c.series.length] },
        itemStyle: { color: s.color ?? c.series[i % c.series.length], borderColor: c.surface, borderWidth: 2 },
        symbol: "circle", symbolSize: 8, emphasis: { focus: "series" },
      })),
    };
  };
}
