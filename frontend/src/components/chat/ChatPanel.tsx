import { useEffect, useRef, useState } from "react";
import { ArrowUp, MessageSquarePlus, Sparkles, Square, X } from "lucide-react";
import { applyEvent, streamChat, type AssistantMessage, type Message } from "../../lib/chat";
import type { Meta } from "../../lib/api";
import AssistantMessageView from "./AssistantMessageView";

export interface ChatHandle { send: (q: string) => void }

export default function ChatPanel({ meta, onClose, registerSend }: { meta: Meta | null; onClose?: () => void; registerSend: (fn: (q: string) => void) => void }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const sessionRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const roundRef = useRef(0);

  const send = async (question: string) => {
    const q = question.trim();
    if (!q || busy) return;
    setInput("");
    setBusy(true);
    roundRef.current = 0;
    const blank: AssistantMessage = { role: "assistant", text: "", interim: [], steps: [], charts: [], streaming: true };
    setMessages((ms) => [...ms, { role: "user", text: q }, blank]);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    const update = (fn: (m: AssistantMessage) => AssistantMessage) =>
      setMessages((ms) => { const copy = ms.slice(); copy[copy.length - 1] = fn(copy[copy.length - 1] as AssistantMessage); return copy; });
    try {
      await streamChat(q, sessionRef.current, (e) => {
        if (e.type === "session") sessionRef.current = e.session_id;
        update((m) => applyEvent(m, e, roundRef));
      }, ctrl.signal);
    } catch (err) {
      if ((err as Error).name !== "AbortError") update((m) => ({ ...m, error: (err as Error).message }));
    } finally {
      update((m) => ({ ...m, streaming: false }));
      setBusy(false);
    }
  };

  useEffect(() => { registerSend(send); });
  useEffect(() => { scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" }); }, [messages]);

  const reset = () => {
    abortRef.current?.abort();
    if (sessionRef.current) fetch("/api/chat/reset", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: sessionRef.current }) });
    sessionRef.current = null;
    setMessages([]);
  };

  return (
    <div className="flex h-full flex-col bg-surface">
      <header className="flex items-center justify-between border-b border-line px-4 py-3">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-accent" />
          <div>
            <div className="text-sm font-semibold text-ink">Ask the Scorecard</div>
            <div className="text-[11px] text-muted">Answers come only from official Scorecard data</div>
          </div>
        </div>
        <div className="flex items-center gap-1">
          {messages.length > 0 && (
            <button onClick={reset} className="rounded-md p-1.5 text-ink-2 hover:bg-surface-2" title="New chat" aria-label="New chat"><MessageSquarePlus className="h-4 w-4" /></button>
          )}
          {onClose && <button onClick={onClose} className="rounded-md p-1.5 text-ink-2 hover:bg-surface-2 lg:hidden" aria-label="Close chat"><X className="h-4 w-4" /></button>}
        </div>
      </header>

      <div ref={scrollRef} className="flex-1 space-y-5 overflow-y-auto px-4 py-4" aria-live="polite">
        {messages.length === 0 && (
          <div className="space-y-4">
            <p className="text-sm text-ink-2">
              Ask anything about what World Bank Group projects have delivered, where, and how it compares with needs in client countries. Every number is
              looked up in the Scorecard data and checked automatically.
            </p>
            <div className="space-y-2">
              <div className="text-xs font-medium uppercase tracking-wide text-muted">Try</div>
              {(meta?.examples ?? []).map((ex) => (
                <button key={ex} onClick={() => send(ex)} className="block w-full rounded-xl border border-line px-3 py-2 text-left text-sm text-ink hover:border-accent hover:bg-accent-soft/40">
                  {ex}
                </button>
              ))}
            </div>
            {meta && !meta.llm_configured && (
              <p className="rounded-lg px-3 py-2 text-xs" style={{ background: "var(--warn-bg)", color: "var(--warn-ink)" }}>No LLM API key is configured on the server, so chat is disabled.</p>
            )}
          </div>
        )}
        {messages.map((m, i) => m.role === "user"
          ? <div key={i} className="ml-8 rounded-2xl rounded-br-md bg-accent px-3.5 py-2 text-sm text-white">{m.text}</div>
          : <AssistantMessageView key={i} m={m} />)}
      </div>

      <form onSubmit={(e) => { e.preventDefault(); send(input); }} className="border-t border-line p-3">
        <div className="flex items-end gap-2 rounded-2xl border border-line bg-page px-3 py-2 focus-within:border-accent">
          <textarea value={input} onChange={(e) => setInput(e.target.value)} rows={1} maxLength={meta?.limits.max_input_chars ?? 2000}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); } }}
            placeholder="Ask a question in any language…" aria-label="Your question"
            className="max-h-32 min-h-[1.5rem] flex-1 resize-none bg-transparent text-sm text-ink outline-none placeholder:text-muted" />
          {busy
            ? <button type="button" onClick={() => abortRef.current?.abort()} className="rounded-full bg-ink p-1.5 text-surface" aria-label="Stop"><Square className="h-3.5 w-3.5" /></button>
            : <button type="submit" disabled={!input.trim()} className="rounded-full bg-accent p-1.5 text-white disabled:opacity-40" aria-label="Send"><ArrowUp className="h-4 w-4" /></button>}
        </div>
        <p className="mt-1.5 text-center text-[10px] text-muted">AI-generated answers from official Scorecard data · each answer shows the data it used</p>
      </form>
    </div>
  );
}
