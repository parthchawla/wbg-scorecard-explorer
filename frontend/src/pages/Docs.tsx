import { useEffect, useState } from "react";
import { api } from "../lib/api";
import Markdown from "../components/Markdown";
import { ErrorNote, Loading } from "../components/ui";

export default function Docs({ name, mcpUrl }: { name: "guide" | "how-to-use"; mcpUrl?: string }) {
  const [text, setText] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { setText(null); api.content(name).then(setText).catch((e) => setErr(e.message)); }, [name]);
  const title = name === "guide" ? text?.replace(/^# Part A: Data Guide/, "# About the data") : text;
  return (
    <article className="card p-6 sm:p-10">
      {err && <ErrorNote error={err} />}
      {!text && !err && <Loading h={400} />}
      {title && <Markdown text={title} className="doc prose-answer" />}
      {name === "how-to-use" && mcpUrl && (
        <div className="doc prose-answer mt-8 border-t border-line pt-6">
          <h2>Use the data in your own AI assistant (MCP)</h2>
          <p>The assistant's data tools are also served by this app as an MCP server at <code>{mcpUrl}</code>, so you can connect Claude Desktop, Claude Code or any other MCP client to the same data:</p>
          <pre className="overflow-x-auto rounded-lg bg-surface-2 p-3 text-xs">{`claude mcp add --transport http wbg-scorecard ${mcpUrl}`}</pre>
        </div>
      )}
    </article>
  );
}
