import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { BarChart, LineChart, MapChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent, VisualMapComponent, AriaComponent } from "echarts/components";
import { SVGRenderer } from "echarts/renderers";
import type { EChartsCoreOption } from "echarts/core";
import { useTheme } from "../lib/theme";

echarts.use([BarChart, LineChart, MapChart, GridComponent, LegendComponent, TooltipComponent, VisualMapComponent, AriaComponent, SVGRenderer]);

export { echarts };

/** ECharts wrapper: rebuilds the option on theme change (options read CSS variables) and resizes with its box.
 *  SVG renderer: crisp at any zoom, and much cheaper than canvas on machines without GPU canvas acceleration. */
export default function EChart({ option, height = 280, ariaLabel }: { option: () => EChartsCoreOption; height?: number; ariaLabel: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [theme] = useTheme();
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current, undefined, { renderer: "svg" });
    chart.setOption({ aria: { enabled: true, label: { description: ariaLabel } }, ...option() });
    let frame = 0;
    const ro = new ResizeObserver(() => { cancelAnimationFrame(frame); frame = requestAnimationFrame(() => chart.resize()); });
    ro.observe(ref.current);
    return () => { cancelAnimationFrame(frame); ro.disconnect(); chart.dispose(); };
  }, [option, theme, ariaLabel]);
  return <div ref={ref} style={{ height }} role="img" aria-label={ariaLabel} />;
}
