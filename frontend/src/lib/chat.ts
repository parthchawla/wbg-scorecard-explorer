// Streaming chat client: POSTs to /api/chat and parses Server-Sent Events from the response body.

export interface ToolStep {
  id: string;
  name: string;
  title: string;
  input: Record<string, unknown>;
  ok?: boolean;
  summary?: string;
  data?: any;
}

export interface ChartSpec {
  chart_type: "bar" | "horizontal_bar" | "grouped_bar" | "stacked_bar" | "line";
  title: string;
  subtitle?: string;
  categories: string[];
  series: { name: string; values: (number | null)[] }[];
  unit: string;
  source_note?: string;
}

export interface Verification { status: "verified" | "unverified" | "no_numbers" | "no_data"; checked: number; verified: number; unverified: string[] }

export interface AssistantMessage {
  role: "assistant";
  text: string;            // final answer text
  interim: string[];       // short notes written before tool calls
  steps: ToolStep[];
  charts: { id: string; spec: ChartSpec }[];
  verification?: Verification;
  revised?: boolean;
  error?: string;
  done?: { model: string; cost_usd: number; seconds: number; tool_calls: number };
  streaming: boolean;
}
export interface UserMessage { role: "user"; text: string }
export type Message = UserMessage | AssistantMessage;

export type ChatEvent = { type: string; [k: string]: any };

export async function streamChat(message: string, sessionId: string | null, onEvent: (e: ChatEvent) => void, signal?: AbortSignal) {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, session_id: sessionId }),
    signal,
  });
  if (!res.ok || !res.body) throw new Error(`Chat request failed (${res.status})`);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const data = chunk.split("\n").filter((l) => l.startsWith("data: ")).map((l) => l.slice(6)).join("\n");
      if (data) onEvent(JSON.parse(data));
    }
  }
}

/** Fold one SSE event into the assistant message being streamed. */
export function applyEvent(m: AssistantMessage, e: ChatEvent, roundRef: { current: number }): AssistantMessage {
  switch (e.type) {
    case "text":
      if (e.round !== roundRef.current) {
        // A new model round started: the previous round's text was a note before tool calls.
        if (m.text.trim()) m = { ...m, interim: [...m.interim, m.text.trim()], text: "" };
        roundRef.current = e.round;
      }
      return { ...m, text: m.text + e.delta };
    case "tool_call":
      return { ...m, steps: [...m.steps, { id: e.id, name: e.name, title: e.title, input: e.input }] };
    case "tool_result":
      return { ...m, steps: m.steps.map((s) => (s.id === e.id ? { ...s, ok: e.ok, summary: e.summary, data: e.data } : s)) };
    case "chart":
      return { ...m, charts: [...m.charts.filter((c) => c.spec.title !== e.spec.title), { id: e.id, spec: e.spec }] };
    case "verification":
      return { ...m, verification: e as unknown as Verification };
    case "revision":
      return { ...m, text: "", revised: true, verification: undefined };
    case "error":
      return { ...m, error: e.message, streaming: false };
    case "done":
      return { ...m, done: e as any, streaming: false };
    default:
      return m;
  }
}
