import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { BarChart3, Globe2, Moon, Sparkles, Sun } from "lucide-react";
import { api, type Meta } from "./lib/api";
import { href, useRoute } from "./lib/route";
import { useTheme } from "./lib/theme";
import { ChatContext } from "./components/chat/ChatContext";
import ChatPanel from "./components/chat/ChatPanel";
import Overview from "./pages/Overview";
import { Loading } from "./components/ui";

// Chart-heavy pages (ECharts, map) load on demand so the first screen stays light.
const Explore = lazy(() => import("./pages/Explore"));
const Country = lazy(() => import("./pages/Country"));
const Docs = lazy(() => import("./pages/Docs"));

const NAV = [
  { page: "overview", label: "Overview" },
  { page: "explore", label: "Explore results" },
  { page: "country", label: "Countries" },
  { page: "how-to-use", label: "How to use" },
  { page: "about", label: "About the data" },
];

export default function App() {
  const route = useRoute();
  const [theme, toggleTheme] = useTheme();
  const [meta, setMeta] = useState<Meta | null>(null);
  const [chatOpen, setChatOpen] = useState(false);
  const sendRef = useRef<(q: string) => void>(() => {});
  useEffect(() => { api.meta().then(setMeta).catch(() => setMeta(null)); }, []);

  const ask = (q: string) => { setChatOpen(true); setTimeout(() => sendRef.current(q), 0); };
  // Shareable question links: #/overview?ask=Which%20regions... asks on load.
  const askedRef = useRef<string | null>(null);
  useEffect(() => {
    const q = route.params.ask;
    if (q && meta && askedRef.current !== q) { askedRef.current = q; ask(q); }
  }, [route.params.ask, meta]);
  const snapshots = meta?.snapshots ?? [2024, 2025, 2026];
  const latest = meta?.latest_snapshot ?? 2026;

  let page;
  switch (route.page) {
    case "explore": page = <Explore params={route.params} snapshots={snapshots} />; break;
    case "country": page = <Country params={route.params} />; break;
    case "how-to-use": page = <Docs name="how-to-use" mcpUrl={meta?.mcp_url} />; break;
    case "about": page = <Docs name="guide" />; break;
    default: page = <Overview latest={latest} />;
  }

  return (
    <ChatContext.Provider value={{ ask, open: chatOpen, setOpen: setChatOpen }}>
      <div className="flex h-full flex-col">
        <header className="sticky top-0 z-20 border-b border-line bg-surface/90 backdrop-blur">
          <div className="flex items-center gap-4 px-4 py-2.5 lg:px-6">
            <a href={href("overview")} className="flex items-center gap-2 font-semibold text-ink">
              <span className="grid h-7 w-7 place-items-center rounded-lg bg-accent text-white"><BarChart3 className="h-4 w-4" /></span>
              <span className="hidden sm:inline">Scorecard Explorer</span>
            </a>
            <nav className="flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto text-sm" aria-label="Main">
              {NAV.map((n) => (
                <a key={n.page} href={href(n.page)} aria-current={route.page === n.page ? "page" : undefined}
                  className={`whitespace-nowrap rounded-lg px-2.5 py-1.5 ${route.page === n.page ? "bg-surface-2 font-medium text-ink" : "text-ink-2 hover:text-ink"}`}>{n.label}</a>
              ))}
            </nav>
            <button onClick={toggleTheme} className="rounded-lg p-2 text-ink-2 hover:bg-surface-2" aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}>
              {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </button>
            <button onClick={() => setChatOpen(true)} className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-white lg:hidden">
              <Sparkles className="h-4 w-4" /> Ask
            </button>
          </div>
        </header>

        <div className="flex min-h-0 flex-1">
          <main className="min-w-0 flex-1 overflow-y-auto">
            <div className="mx-auto max-w-6xl px-4 py-6 lg:px-8 lg:py-8">
              <Suspense fallback={<Loading h={400} />}>{page}</Suspense>
              <footer className="mt-12 flex flex-wrap items-center justify-between gap-2 border-t border-line pt-4 text-xs text-muted">
                <span className="inline-flex items-center gap-1.5"><Globe2 className="h-3.5 w-3.5" /> Data: World Bank Group Corporate Scorecard (scorecard.worldbank.org), snapshots FY{snapshots[0]}–FY{latest}.</span>
                <span>Created by Parth Chawla · prototype, not an official World Bank product{meta ? ` · AI model: ${meta.model}` : ""}</span>
              </footer>
            </div>
          </main>
          {/* Chat: docked on large screens, full-screen sheet on small ones. */}
          <aside className={`${chatOpen ? "fixed inset-0 z-30 flex" : "hidden"} lg:static lg:z-auto lg:flex lg:w-[420px] lg:shrink-0 lg:border-l lg:border-line`} aria-label="Chat">
            <div className="flex w-full flex-col">
              <ChatPanel meta={meta} onClose={() => setChatOpen(false)} registerSend={(fn) => { sendRef.current = fn; }} />
            </div>
          </aside>
        </div>
      </div>
    </ChatContext.Provider>
  );
}
