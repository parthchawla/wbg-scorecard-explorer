import { useEffect, useState } from "react";

export type Theme = "light" | "dark";

function current(): Theme {
  const set = document.documentElement.dataset.theme as Theme | undefined;
  if (set) return set;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/** Theme state + toggle. Charts re-render on change because they read CSS variables. */
export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(current);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const on = () => setTheme(current());
    mq.addEventListener("change", on);
    window.addEventListener("themechange", on);
    return () => { mq.removeEventListener("change", on); window.removeEventListener("themechange", on); };
  }, []);
  const toggle = () => {
    const next: Theme = current() === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("theme", next); } catch { /* storage blocked */ }
    window.dispatchEvent(new Event("themechange"));
  };
  return [theme, toggle];
}

export function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export function chartColors() {
  return {
    ink: cssVar("--ink"), ink2: cssVar("--ink-2"), muted: cssVar("--muted"), grid: cssVar("--grid"),
    axis: cssVar("--axis"), surface: cssVar("--surface"),
    series: [cssVar("--series-1"), cssVar("--series-2"), cssVar("--series-3")],
    soft: cssVar("--series-1-soft"),
    seq: Array.from({ length: 8 }, (_, i) => cssVar(`--seq-${i}`)),
  };
}
