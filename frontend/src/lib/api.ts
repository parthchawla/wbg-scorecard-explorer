// Typed client for the FastAPI backend.

export type Tier = "WBG Results" | "Client Context" | "Vision";

export interface Indicator {
  ind_code: string;
  name: string;
  tier: Tier;
  outcome_area: string | null;
  unit: string;
  definition?: string;
  better_when: "higher" | "lower";
  reports_achieved: boolean;
  reports_expected: boolean;
  snapshots_with_data: number[] | null;
}

export interface OverviewItem {
  ind_code: string;
  name: string;
  outcome_area: string;
  unit: string;
  achieved: number | null;
  expected: number | null;
  achieved_first: number | null;
  has_data: boolean;
  by_snapshot: Record<string, { achieved: number | null; expected: number | null }>;
}

export interface ResultRow {
  area_code: string;
  area_name: string;
  achieved?: number | null;
  expected?: number | null;
  achieved_to_expected?: number | null;
  share_of_global_achieved?: number;
  region?: string;
  income?: string;
  fcs?: boolean;
  [k: string]: unknown;
}

export interface ResultsResponse {
  indicator: { ind_code: string; name: string; unit: string };
  snapshot_fy: number;
  institution: string | null;
  breakdown: string;
  global_total: { achieved: number | null; expected: number | null } | null;
  rows: ResultRow[];
  notes: string[];
}

export interface Country {
  country_code: string;
  iso3: string;
  country_name: string;
  region_code: string;
  region_name: string;
  income_name: string;
  is_fcs: boolean;
  lending_eligibility: string;
}

export interface Meta {
  model: string;
  snapshots: number[];
  latest_snapshot: number;
  examples: string[];
  mcp_url: string;
  llm_configured: boolean;
  limits: { questions_per_hour: number; max_input_chars: number };
}

async function get<T>(path: string): Promise<T> {
  const r = await fetch(path);
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try { msg = (await r.json()).detail ?? msg; } catch { /* not JSON */ }
    throw new Error(msg);
  }
  return r.headers.get("content-type")?.includes("json") ? r.json() : ((await r.text()) as unknown as T);
}

const qs = (p: Record<string, string | number | boolean | undefined | null>) =>
  Object.entries(p).filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join("&");

export const api = {
  meta: () => get<Meta>("/api/meta"),
  overview: () => get<OverviewItem[]>("/api/overview"),
  indicators: () => get<Indicator[]>("/api/indicators"),
  profile: (code: string) => get<Record<string, any>>(`/api/indicators/${code}`),
  results: (code: string, p: { breakdown?: string; institution?: string; snapshot_fy?: number; compare_snapshots?: boolean; series?: string; top_n?: number }) =>
    get<ResultsResponse>(`/api/results/${code}?${qs(p)}`),
  countries: () => get<Country[]>("/api/countries"),
  country: (c: string) => get<Record<string, any>>(`/api/countries/${encodeURIComponent(c)}`),
  context: (code: string, areas?: string[], start_year?: number) =>
    get<Record<string, any>>(`/api/context/${code}?${qs({ areas: areas?.join(","), start_year })}`),
  projects: (p: { ind_code?: string; country?: string; region?: string; keyword?: string; sort_by?: string; limit?: number }) =>
    get<Record<string, any>>(`/api/projects?${qs(p)}`),
  content: (name: string) => get<string>(`/api/content/${name}`),
};
