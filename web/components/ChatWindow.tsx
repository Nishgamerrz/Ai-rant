"use client";
import { useEffect, useRef, useState } from "react";
import { kindForLine, stripAnsi } from "@/lib/colors";

type Msg = { role: string; content: string; thought?: string; tool_calls?: any[]; time?: string; tool?: string; output?: any };

export function ChatWindow({ runId, tunnelUrl, liveMode }: { runId: number | null; tunnelUrl: string | null; liveMode: boolean }) {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [tools, setTools] = useState<any[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string>("idle");
  const [err, setErr] = useState("");
  const scrollerRef = useRef<HTMLDivElement>(null);

  async function fetchChat() {
    if (!runId) return;
    try {
      const res = await fetch(`/api/github/artifact?run=${runId}&name=nish-agent-${runId}&json=agent_chat.json`, { cache: "no-store" });
      if (!res.ok) return;
      const data = await res.json();
      if (Array.isArray(data)) setMessages(data);
      const tRes = await fetch(`/api/github/artifact?run=${runId}&name=nish-agent-${runId}&json=tunnel_url.txt`, { cache: "no-store" }).then((r) => r.text()).catch(() => "");
      // tools jsonl
      const toolsRes = await fetch(`/api/github/artifact?run=${runId}&name=nish-agent-${runId}&json=agent_tools.jsonl`, { cache: "no-store" }).then((r) => r.text()).catch(() => "");
      if (toolsRes) {
        const lines = toolsRes.trim().split("\n").filter(Boolean);
        setTools(lines.map((l) => { try { return JSON.parse(l); } catch { return { raw: l }; } }));
      }
    } catch {}
  }

  async function fetchStatus() {
    if (!runId) return;
    try {
      const res = await fetch(`/api/github/logs?run=${runId}`, { cache: "no-store" });
      const j = await res.json();
      if (j.run) setStatus(`${j.run.status}${j.run.conclusion ? " · " + j.run.conclusion : ""}`);
    } catch {}
  }

  useEffect(() => {
    if (!runId) {
      setMessages([]);
      setTools([]);
      setStatus("idle");
      return;
    }
    fetchChat();
    fetchStatus();
    const id = setInterval(() => {
      fetchChat();
      fetchStatus();
    }, 4000);
    return () => clearInterval(id);
  }, [runId]);

  useEffect(() => {
    scrollerRef.current?.scrollTo({ top: scrollerRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  async function send() {
    if (!input.trim()) return;
    const text = input.trim();
    setInput("");
    setBusy(true);
    setErr("");
    // optimistic
    setMessages((m) => [...m, { role: "user", content: text, time: new Date().toISOString() }]);
    try {
      if (tunnelUrl && liveMode) {
        const res = await fetch("/api/agent/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message: text, tunnel_url: tunnelUrl }) });
        const j = await res.json();
        if (!j.ok && j.mode === "batch") {
          setErr(j.hint || "No live tunnel — watching batch chat.");
        } else {
          setMessages((m) => [...m, { role: "assistant", content: String(j.reply || j.error || "(no reply)"), time: new Date().toISOString() }]);
        }
      } else {
        // Batch mode: we can't push into a running workflow without tunnel — explain
        setErr("Live tunnel not enabled for this run. Start a New chat with ☑ Cloudflare tunnel for live replies. Until then, the assistant answers appear by polling the workflow artifact (agent_chat.json) every ~4s while the job runs.");
      }
    } catch (e: any) {
      setErr(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  if (!runId) {
    return (
      <div className="flex-1 grid place-items-center p-8 text-center">
        <div className="max-w-lg">
          <div className="h-12 w-12 rounded-2xl bg-zinc-800 grid place-items-center mx-auto text-xl">💬</div>
          <h2 className="mt-4 text-xl font-semibold">No chat selected</h2>
          <p className="mt-2 text-sm text-zinc-400">Pick a chat from the sidebar, or hit <b className="text-zinc-200">＋ New chat</b> to choose what to create — <b className="text-zinc-200">Agent (search / web / code / files)</b> with model selection (Hard is best for agent, as you asked) or <b className="text-zinc-200">RBX Short</b> — then we dispatch the workflow via <code className="bg-zinc-800 px-1 rounded">GITHUB_TOKEN</code> and you watch the coloured logs + file explorer right here.</p>
          <div className="mt-4 rounded-xl bg-zinc-900 border border-zinc-800 p-3 text-xs text-zinc-500 text-left">Secure: the token lives only in Vercel env <code className="bg-zinc-800 px-1 rounded">GITHUB_TOKEN</code> and is read server-side in <code className="bg-zinc-800 px-1 rounded">/api/github/*</code>. The browser never sees it.</div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col min-h-0">
      {/* Header */}
      <div className="shrink-0 px-4 py-3 border-b border-zinc-800 bg-zinc-950/60 backdrop-blur flex items-center gap-3">
        <div className="min-w-0">
          <div className="text-sm font-semibold flex items-center gap-2">
            Run #{runId}
            <span className="text-xs px-2 py-0.5 rounded-full bg-zinc-800 border border-zinc-700">{status}</span>
            {tunnelUrl ? (
              <a href={tunnelUrl} target="_blank" className="text-xs text-violet-300 underline">tunnel live → {tunnelUrl.replace("https://", "").slice(0, 22)}…</a>
            ) : (
              <span className="text-xs text-zinc-500">batch mode — polling artifact</span>
            )}
          </div>
          <div className="text-xs text-zinc-500">{tools.length ? `${tools.length} tool call(s) · ` : ""}{messages.length} messages · {liveMode ? "live via Cloudflare tunnel when enabled" : "polling dist/agent_chat.json"}</div>
        </div>
        <a href={`https://github.com/Nishgamerrz/Ai-rant/actions/runs/${runId}`} target="_blank" className="ml-auto text-xs rounded-lg border border-zinc-700 px-3 py-1.5 hover:bg-zinc-800">Open in GitHub →</a>
      </div>

      {/* Tool chips */}
      {tools.length > 0 && (
        <div className="shrink-0 px-4 py-2 border-b border-zinc-900 bg-zinc-950/40 flex gap-1.5 overflow-x-auto">
          {tools.slice(-12).map((t, i) => (
            <span key={i} className="text-xs whitespace-nowrap rounded-full bg-violet-950/50 border border-violet-800 text-violet-200 px-2 py-1">{t.tool || "tool"} · {String(t.input?.query || t.input?.path || t.input?.cmd || "").slice(0, 28) || "…"}</span>
          ))}
        </div>
      )}

      {/* Messages */}
      <div ref={scrollerRef} className="flex-1 overflow-auto p-4 space-y-4">
        {messages.length === 0 && <div className="text-sm text-zinc-600">Waiting for the workflow to start… logs and AI messages appear here with <b className="text-zinc-400">plan next / previous loads</b> and colours (thinking grey, answer cyan, tool violet).</div>}
        {messages.map((m, i) => {
          const isUser = m.role === "user";
          const isTool = m.role === "tool";
          const isAssist = m.role === "assistant";
          if (isTool) {
            const out = typeof m.output === "string" ? m.output : JSON.stringify(m.output, null, 2);
            return (
              <div key={i} className="rounded-xl border border-violet-900/40 bg-violet-950/20 p-3">
                <div className="text-xs text-violet-300 font-semibold">🔧 tool · {m.tool}</div>
                <pre className="mt-1 text-xs font-mono text-zinc-300 whitespace-pre-wrap break-words max-h-[200px] overflow-auto">{out.slice(0, 2000)}</pre>
              </div>
            );
          }
          return (
            <div key={i} className={`flex gap-3 ${isUser ? "justify-end" : "justify-start"}`}>
              {!isUser && <div className="h-8 w-8 rounded-xl bg-zinc-800 grid place-items-center text-sm shrink-0">{isAssist ? "🤖" : "·"}</div>}
              <div className={`max-w-[78%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${isUser ? "bg-white text-zinc-900" : "bg-zinc-900 border border-zinc-800 text-zinc-100"}`}>
                {m.thought && !isUser && (
                  <details className="mb-2">
                    <summary className="text-xs text-zinc-500 cursor-pointer">thinking</summary>
                    <div className="mt-1 text-xs font-mono text-zinc-400 whitespace-pre-wrap">{stripAnsi(m.thought).slice(0, 1200)}</div>
                  </details>
                )}
                <div className="whitespace-pre-wrap break-words">{m.content}</div>
                {isAssist && m.tool_calls && (m.tool_calls as any[]).length > 0 && <div className="mt-2 flex flex-wrap gap-1">{(m.tool_calls as any[]).map((c: any, j: number) => <span key={j} className="text-xs rounded-full bg-zinc-800 border border-zinc-700 px-2 py-0.5">{c.tool || c.name || "tool"}</span>)}</div>}
                {m.time && <div className="mt-1 text-xs opacity-60">{new Date(m.time).toLocaleTimeString()}</div>}
              </div>
            </div>
          );
        })}
        {err && <div className="rounded-xl border border-amber-800 bg-amber-950/30 text-amber-200 p-3 text-sm">{err}</div>}
      </div>

      {/* Composer */}
      <div className="shrink-0 p-3 border-t border-zinc-800 bg-zinc-950/60">
        <div className="flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
            placeholder={tunnelUrl ? "Message the running agent live (via Cloudflare tunnel)…" : "Live chat needs Cloudflare tunnel — start a new chat with it enabled. Batch chat replies appear by polling."}
            className="flex-1 rounded-xl bg-zinc-900 border border-zinc-800 px-4 py-3 text-sm text-white placeholder:text-zinc-600"
          />
          <button onClick={send} disabled={busy || !input.trim()} className="rounded-xl bg-white text-zinc-900 font-semibold px-5 py-3 text-sm disabled:opacity-50">Send</button>
        </div>
        <div className="mt-2 text-xs text-zinc-600">Press Enter to send · Shift+Enter for newline · Communication uses <code className="bg-zinc-800 px-1 rounded">GITHUB_TOKEN</code> server-side and a free <code className="bg-zinc-800 px-1 rounded">*.trycloudflare.com</code> tunnel when enabled; all tool use is logged to <code className="bg-zinc-800 px-1 rounded">dist/agent_tools.jsonl</code> and shown in the chips above.</div>
      </div>
    </div>
  );
}
