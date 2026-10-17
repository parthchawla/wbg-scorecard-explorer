// Number formatting for plain-language display.

export function fmtNum(v: number | null | undefined, unit = ""): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  const u = unit.toLowerCase();
  if (u.includes("usd")) return "$" + compact(v);
  if (u.includes("percent")) return `${round(v, 1)}%`;
  if (u.includes("gigawatt")) return `${round(v, 1)} GW`;
  if (u.includes("mtco2")) return `${round(v, 1)} Mt`;
  if (u.includes("hectare")) return `${compact(v)} ha`;
  if (u.includes("index")) return round(v, 2);
  return compact(v);
}

export function compact(v: number): string {
  const a = Math.abs(v);
  if (a >= 1e12) return `${round(v / 1e12, 1)} trillion`;
  if (a >= 1e9) return `${round(v / 1e9, 1)} billion`;
  if (a >= 1e6) return `${round(v / 1e6, 1)} million`;
  if (a >= 1e4) return `${round(v / 1e3, 0)}K`;
  return round(v, a < 10 ? 2 : 0);
}

export function short(v: number): string {
  const a = Math.abs(v);
  if (a >= 1e9) return `${round(v / 1e9, 1)}B`;
  if (a >= 1e6) return `${round(v / 1e6, 1)}M`;
  if (a >= 1e3) return `${round(v / 1e3, 0)}K`;
  return round(v, a < 10 ? 1 : 0);
}

export function pct(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  return `${round(v * 100, digits)}%`;
}

export function round(v: number, digits: number): string {
  return v.toLocaleString("en-US", { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}

export function unitLabel(unit: string): string {
  const u = unit.toLowerCase();
  if (u.includes("beneficiar")) return "people";
  if (u.includes("countries")) return "economies";
  if (u.includes("usd")) return "US dollars";
  if (u.includes("mtco2")) return "MtCO2eq per year";
  if (u.includes("hectare")) return "hectares";
  if (u.includes("gigawatt")) return "gigawatts";
  return unit.toLowerCase();
}

export const INSTITUTIONS: Record<string, string> = {
  WBG: "World Bank Group", WB: "World Bank (IBRD + IDA)", IBRD: "IBRD", IDA: "IDA", "IDA-21": "IDA-21", IFC: "IFC", MIGA: "MIGA",
};
