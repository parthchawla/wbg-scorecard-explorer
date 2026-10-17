import { useEffect, useState } from "react";

// Tiny hash router: #/explore?ind=CSC_RES_ELC_ACCS -> { page: "explore", params: { ind: ... } }
export interface Route { page: string; params: Record<string, string> }

function parse(): Route {
  const h = window.location.hash.replace(/^#\/?/, "");
  const [page, query = ""] = h.split("?");
  return { page: page || "overview", params: Object.fromEntries(new URLSearchParams(query)) };
}

export function useRoute(): Route {
  const [route, setRoute] = useState(parse);
  useEffect(() => {
    const on = () => { setRoute(parse()); window.scrollTo({ top: 0 }); };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

export function href(page: string, params: Record<string, string | undefined> = {}): string {
  const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v) as [string, string][]).toString();
  return `#/${page}${q ? "?" + q : ""}`;
}
