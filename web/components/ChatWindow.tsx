"use client";
import { useEffect, useRef, useState } from "react";
import { SubagentTimeline } from "./SubagentTimeline";

type Msg = { role: string; content: string; thought?: string; tool_calls?: any[]; time?: string; tool?: string; output?: any };

function parseLiveLogTail(tail: string): { msgs: Msg[]; subagentCalls: any[] } {
  const msgs: Msg[] = [];
  // Look for JSON after "answer ▸" or tool blocks
  // Example: [nish-agent r1/8] answer ▸ { "answer": "...", "tool_calls": [...] }
  const lines = tail.split("\n");
  let buf = "";
  let inAnswer = false;
  for (const ln of lines) {
    if (ln.includes("answer") && ln.includes("▸")) {
      inAnswer = true;
      buf = ln.slice(ln.indexOf("{"));
      // try parse if single line JSON
      try {
        const obj = JSON.parse(buf);
        if (obj.answer || obj.tool_calls) {
          msgs.push({
            role: "assistant",
            content: String(obj.answer || ""),
            tool_calls: obj.tool_calls || [],
            time: new Date().toISOString(),
          });
          inAnswer = false;
          buf = "";
        }
      } catch {
        // wait for multi-line
      }
    } else if (inAnswer) {
      buf += "\n" + ln;
      try {
        const obj = JSON.parse(buf);
        msgs.push({
          role: "assistant",
          content: String(obj.answer || ""),
          tool_calls: obj.tool_calls || [],
          time: new Date().toISOString(),
        });
        inAnswer = false;
        buf = "";
      } catch {
        if (buf.length > 8000) inAnswer = false;
      }
    }
    // also capture user prompts from logs? they appear as Prompt: ...
    if (ln.includes("Prompt:")) {
      const p = ln.split("Prompt:").slice(1).join("Prompt:").trim().slice(0, 400);
      if (p) msgs.push({ role: "user", content: p, time: new Date().toISOString() });
    }
  }
  return { msgs, subagentCalls: [] };
}

export function ChatWindow({ runId, tunnelUrl, liveMode }: { runId: number | null; tunnelUrl: string | null; liveMode: boolean }) {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [tools, setTools] = useState<any[]>([]);
  const [liveLog, setLiveLog] = useState<string>("");
  const [liveMsgs, setLiveMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("idle");
  const [err, setErr] = useState("");
  const scrollerRef = useRef<HTMLDivElement>(null);

  async function fetchChat() {
    if (!runId) return;
    try {
      // Prefer artifact; if not yet uploaded this will 404 and we keep live log
      const res = await fetch(`/api/github/artifact?run=${runId}&name=nish-agent-${runId}&json=agent_chat.json`, { cache: "no-store" });
      if (!res.ok) return;
      const ct = res.headers.get("content-type") || "";
      let data: any;
      if (ct.includes("json")) data = await res.json();
      else {
        const txt = await res.text();
        try { data = JSON.parse(txt); } catch { return; }
      }
      if (Array.isArray(data) && data.length) setMessages(data);
      // tools jsonl
      const toolsRes = await fetch(`/api/github/artifact?run=${runId}&name=nish-agent-${runId}&json=agent_tools.jsonl`, { cache: "no-store" }).then((r) => r.text()).catch(() => "");
      if (toolsRes && toolsRes.trim()) {
        const lines = toolsRes.trim().split("\n").filter(Boolean);
        const parsed = lines.map((l) => { try { return JSON.parse(l); } catch { return { raw: l }; } }).slice(-20);
        if (parsed.length) setTools(parsed);
      }
    } catch {}
  }

  async function fetchLive() {
    if (!runId) return;
    try {
      const res = await fetch(`/api/github/logs?run=${runId}&logs=1`, { cache: "no-store" });
      const j = await res.json();
      if (j.run) setStatus(`${j.run.status}${j.run.conclusion ? " · " + j.run.conclusion : ""}`);
      if (j.logTail) {
        setLiveLog(j.logTail);
        const parsed = parseLiveLogTail(j.logTail);
        if (parsed.msgs.length) setLiveMsgs(parsed.msgs);
      }
    } catch {}
    // Also try live chat history directly via tunnel if available (instant, not waiting for artifact or log tail)
    if (tunnelUrl) {
      try {
        const r = await fetch(`/api/agent/files?run=${runId}&path=__nish/chat&tunnel=${encodeURIComponent(tunnelUrl)}`, { cache: "no-store" });
        if (r.ok) {
          const ct = r.headers.get("content-type") || "";
          let data: any = null;
          if (ct.includes("json")) data = await r.json().catch(() => null);
          else {
            const txt = await r.text();
            try { data = JSON.parse(txt); } catch { data = null; }
          }
          if (Array.isArray(data) && data.length) {
            const last = data as Msg[];
            setLiveMsgs(last.slice(-12));
            // also update tools from live if needed
            try {
              const tr = await fetch(`/api/agent/files?run=${runId}&path=__nish/tools&tunnel=${encodeURIComponent(tunnelUrl)}`, { cache: "no-store" });
              if (tr.ok) {
                const tj = await tr.json().catch(() => null);
                if (Array.isArray(tj) && tj.length) setTools(tj.slice(-20) as any);
              }
            } catch {}
          }
        }
      } catch {}
    }
  }

  useEffect(() => {
    if (!runId) {
      setMessages([]);
      setTools([]);
      setLiveLog("");
      setLiveMsgs([]);
      setStatus("idle");
      return;
    }
    fetchChat();
    fetchLive();
    const id = setInterval(() => { fetchChat(); fetchLive(); }, 3500);
    return () => clearInterval(id);
  }, [runId, tunnelUrl]);

  useEffect(() => {
    scrollerRef.current?.scrollTo({ top: scrollerRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, liveMsgs, liveLog]);

  async function send() {
    if (!input.trim() || busy) return;
    const text = input.trim();
    setInput("");
    setBusy(true);
    setErr("");
    setMessages((m) => [...m, { role: "user", content: text, time: new Date().toISOString() }]);
    try {
      if (tunnelUrl) {
        const res = await fetch("/api/agent/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message: text, tunnel_url: tunnelUrl }) });
        const j = await res.json();
        if (!j.ok) {
          if (j.mode === "batch") setErr(j.hint || "Live tunnel unavailable — watching batch output.");
          else setErr(j.error || "Tunnel error");
        } else {
          setMessages((m) => [...m, { role: "assistant", content: String(j.reply || "(no reply)"), time: new Date().toISOString() }]);
        }
      } else {
        setErr("Live chat requires the Cloudflare tunnel. Start a new workflow with “Enable live tunnel” checked — the URL appears in live logs within ~30s. Meanwhile, the agent’s replies stream from the live log below and will also appear here as artifacts.");
      }
    } catch (e: any) {
      setErr(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  if (!runId) {
    return (
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="max-w-md w-full text-center">
          <div className="h-14 w-14 rounded-2xl bg-zinc-900 border border-zinc-800 grid place-items-center mx-auto shadow-soft">
            <svg width="22" height="22" viewBox="0 0 22 22" fill="none"><path d="M7 7H15M7 11H15M7 15H12" stroke="#a1a1aa" strokeWidth="1.4" strokeLinecap="round"/><rect x="3.5" y="2.5" width="15" height="17" rx="2" stroke="#27272a" strokeWidth="1.2"/></svg>
          </div>
          <h2 className="mt-4 text-[15px] font-semibold tracking-tight">Select a workflow</h2>
          <p className="mt-1.5 text-sm leading-relaxed text-zinc-500">Choose a run from the sidebar or create a new one. Live messages, thinking, tool activity, and generated files will appear here in real time — even before artifacts upload.</p>
        </div>
      </div>
    );
  }

  const displayMessages = messages.length ? messages : liveMsgs;
  const showLiveLog = liveLog && messages.length === 0;

  return (
    <div className="flex-1 flex flex-col min-h-0 bg-[#09090b]">
      {/* Header */}
      <div className="shrink-0 h-14 px-4 flex items-center gap-3 border-b border-zinc-800 bg-zinc-900/40 backdrop-blur">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold tracking-tight">Run #{runId}</span>
            <span className={`text-[11px] px-2 py-0.5 rounded-full font-medium border ${status.includes("success") ? "bg-emerald-950/40 border-emerald-900 text-emerald-300" : status.includes("failure") ? "bg-red-950/30 border-red-900 text-red-300" : status.includes("in_progress") || status.includes("queued") ? "bg-amber-950/30 border-amber-900 text-amber-300" : "bg-zinc-800 border-zinc-700 text-zinc-400"}`}>
              {status}
            </span>
            {tunnelUrl ? (
              <span className="hidden sm:inline-flex items-center gap-1.5 text-[11px] px-2 py-0.5 rounded-full bg-emerald-950/30 border border-emerald-900/50 text-emerald-300">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" /> Live
              </span>
            ) : (
              <span className="hidden sm:inline text-[11px] px-2 py-0.5 rounded-full bg-zinc-800 border border-zinc-700 text-zinc-500">Polling live log</span>
            )}
          </div>
          <div className="text-[11px] text-zinc-600 flex items-center gap-2">
            {tunnelUrl ? <a href={tunnelUrl} target="_blank" className="hover:text-zinc-400 transition-colors truncate max-w-[180px]">{tunnelUrl.replace("https://", "")}</a> : <span>{liveLog ? `${(liveLog.length/1024).toFixed(1)} KB live log · ${tools.length} tools · ${displayMessages.length} messages` : `Artifact polling · ${tools.length} tools · ${displayMessages.length} messages`}</span>}
          </div>
        </div>
        <a href={`https://github.com/Nishgamerrz/Ai-rant/actions/runs/${runId}`} target="_blank" className="h-8 px-3 rounded-xl bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 text-xs font-medium text-zinc-300 hover:text-white transition-colors hidden sm:flex items-center gap-1.5">
          GitHub <svg width="10" height="10" viewBox="0 0 10 10" fill="none"><path d="M3 7L7 3M7 3H4M7 3V6" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/></svg>
        </a>
      </div>

      {/* Subagent timeline — mandatory delegation visible (live fallback inside component) */}
      {runId && (
        <div className="shrink-0 border-b border-zinc-800/60 bg-zinc-900/30 px-3 py-2">
          <SubagentTimeline runId={runId} kind="agent" liveLog={liveLog || undefined} />
        </div>
      )}

      {/* Tool chips + detailed execution */}
      {tools.length > 0 && (
        <>
          <div className="shrink-0 px-3 py-2 border-b border-zinc-800/60 bg-zinc-900/20 flex gap-1.5 overflow-x-auto scrollbar-thin">
            {tools.slice(-10).map((t, i) => (
              <span key={i} className="shrink-0 inline-flex items-center gap-1.5 text-[11px] font-medium rounded-full bg-zinc-900 border border-zinc-800 text-zinc-400 px-2.5 py-1">
                <span className={`h-1.5 w-1.5 rounded-full ${t.output?.ok === false ? "bg-red-500" : t.output?.ok ? "bg-emerald-500" : "bg-violet-500"}`} />
                {t.tool || "tool"} <span className="text-zinc-600 hidden sm:inline">· {String(t.input?.query || t.input?.path || t.input?.cmd || t.input?.instruction || "").slice(0, 22) || "…"}</span>
              </span>
            ))}
          </div>
          <div className="shrink-0 border-b border-zinc-800/60 bg-zinc-900/30 max-h-[220px] overflow-auto divide-y divide-zinc-800/50">
            {tools.slice(-4).reverse().map((t, i) => {
              const input = t.input || {};
              const out = t.output || {};
              const cmd = input.cmd || input.command || input.query || input.path || input.instruction || "";
              const isErr = out.ok === false || out.error;
              return (
                <div key={i} className={`p-3 ${isErr ? "bg-red-950/10" : "bg-zinc-900/20"}`}>
                  <div className="flex items-center gap-2">
                    <span className={`h-6 w-6 rounded-lg grid place-items-center text-xs font-bold border ${isErr ? "bg-red-950/30 border-red-900 text-red-400" : out.ok ? "bg-emerald-950/30 border-emerald-900 text-emerald-400" : "bg-zinc-800 border-zinc-700 text-zinc-400"}`}>{isErr ? "!" : t.tool?.[0]?.toUpperCase() || "•"}</span>
                    <span className="text-xs font-semibold tracking-wide text-zinc-300">{t.tool}</span>
                    <span className={`ml-auto text-[11px] px-1.5 py-0.5 rounded-full border font-medium ${isErr ? "bg-red-950/30 border-red-900 text-red-300" : out.ok ? "bg-emerald-950/20 border-emerald-900/50 text-emerald-300" : "bg-zinc-800 border-zinc-700 text-zinc-500"}`}>{out.ok === true ? "ok" : out.ok === false ? "error" : "run"}{out.code !== undefined ? ` · code ${out.code}` : ""}</span>
                  </div>
                  {cmd && <div className="mt-2 rounded-lg bg-zinc-950 border border-zinc-800 p-2 text-xs font-mono text-zinc-400 whitespace-pre-wrap break-words">cmd: {String(cmd).slice(0, 600)}</div>}
                  {out.output && <pre className="mt-2 rounded-lg bg-zinc-950 border border-zinc-800 p-2 text-xs font-mono leading-relaxed text-zinc-300 whitespace-pre-wrap break-words max-h-[120px] overflow-auto">{String(out.output).slice(0, 2000)}</pre>}
                  {out.content && <pre className="mt-2 rounded-lg bg-zinc-950 border border-zinc-800 p-2 text-xs font-mono leading-relaxed text-zinc-300 whitespace-pre-wrap break-words max-h-[120px] overflow-auto">{String(out.content).slice(0, 2000)}</pre>}
                  {out.error && <div className="mt-2 rounded-lg bg-red-950/20 border border-red-900/30 p-2 text-xs font-mono text-red-300 whitespace-pre-wrap break-words">{String(out.error).slice(0, 800)}</div>}
                  {out.text && !out.output && <pre className="mt-2 rounded-lg bg-violet-950/10 border border-violet-900/20 p-2 text-xs font-mono leading-relaxed text-violet-200 whitespace-pre-wrap break-words max-h-[120px] overflow-auto">{String(out.text).slice(0, 2000)}</pre>}
                  {out.path && <div className="mt-1 text-[11px] text-emerald-400">→ {out.path} {out.bytes ? `(${out.bytes} bytes)` : ""}</div>}
                  {out.files && Array.isArray(out.files) && <div className="mt-1 text-[11px] text-zinc-500">files: {(out.files as string[]).slice(0,6).join(", ")}</div>}
                </div>
              );
            })}
          </div>
        </>
      )}

      {/* Messages + Live log */}
      <div ref={scrollerRef} className="flex-1 overflow-auto">
        <div className="max-w-3xl mx-auto w-full p-4 sm:p-6 space-y-4">
          {showLiveLog && (
            <div className="rounded-2xl border border-zinc-800 bg-zinc-900 overflow-hidden">
              <div className="h-8 px-3 flex items-center gap-2 border-b border-zinc-800 bg-zinc-900">
                <span className="h-2 w-2 rounded-full bg-amber-500 animate-pulse" />
                <span className="text-xs font-semibold tracking-wide text-zinc-300">Live stream · thinking & tool calls</span>
                <span className="ml-auto text-[11px] text-zinc-600">typing…</span>
              </div>
              <pre className="p-3 text-xs font-mono leading-relaxed whitespace-pre-wrap break-words max-h-[420px] overflow-auto text-zinc-300">
                {liveLog.slice(-8000)}
              </pre>
              <div className="px-3 py-2 border-t border-zinc-800 bg-zinc-950 text-[11px] text-zinc-500">Streaming directly from the runner’s job log via <code className="bg-zinc-800 px-1 rounded">/api/github/logs?logs=1</code>. Artifacts chat appears here automatically once the step uploads — no refresh needed.</div>
            </div>
          )}
          {displayMessages.length === 0 && !liveLog && (
            <div className="rounded-2xl border border-dashed border-zinc-800 bg-zinc-900/20 p-6 text-center">
              <div className="text-sm font-medium text-zinc-300">Waiting for agent</div>
              <div className="text-xs text-zinc-600 mt-1 leading-relaxed">The workflow is starting (model loading can take 60–90s on first pull). Thinking, tool calls, and sub-agent delegation stream here live.</div>
            </div>
          )}
          {displayMessages.map((m, i) => {
            const isUser = m.role === "user";
            const isTool = m.role === "tool";
            if (isTool) {
              const out = typeof m.output === "string" ? m.output : JSON.stringify(m.output, null, 2);
              return (
                <div key={i} className="rounded-2xl border border-violet-900/30 bg-violet-950/10 overflow-hidden animate-slideIn">
                  <div className="px-3.5 py-2 bg-violet-950/20 border-b border-violet-900/20 flex items-center gap-2">
                    <span className="h-6 w-6 rounded-lg bg-violet-600/20 border border-violet-700/30 grid place-items-center">
                      <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M4 4.5L4 7.5M6 3V9M8 4.5V7.5" stroke="#a78bfa" strokeWidth="1.2" strokeLinecap="round"/></svg>
                    </span>
                    <span className="text-xs font-semibold tracking-wide text-violet-300">Tool · {m.tool}</span>
                    <span className="ml-auto text-[11px] text-violet-300/60">output</span>
                  </div>
                  <pre className="p-3.5 text-xs font-mono leading-relaxed text-zinc-400 whitespace-pre-wrap break-words max-h-[220px] overflow-auto">{out.slice(0, 3000)}</pre>
                </div>
              );
            }
            return (
              <div key={i} className={`flex gap-3 ${isUser ? "justify-end" : "justify-start"} animate-slideIn`}>
                {!isUser && (
                  <div className="h-8 w-8 rounded-xl bg-zinc-800 border border-zinc-700 grid place-items-center shrink-0 mt-0.5">
                    <span className="text-[11px] font-bold tracking-wide text-zinc-400">AI</span>
                  </div>
                )}
                <div className={`max-w-[82%] rounded-2xl px-4 py-3 ${isUser ? "bg-white text-zinc-900 shadow-soft" : "bg-zinc-900 border border-zinc-800 text-zinc-100 shadow-soft"}`}>
                  {m.thought && !isUser && (
                    <details className="mb-2.5 group">
                      <summary className="list-none flex items-center gap-1.5 text-[11px] font-semibold tracking-wide text-zinc-500 hover:text-zinc-400 cursor-pointer select-none">
                        <svg width="10" height="10" viewBox="0 0 10 10" fill="none" className="group-open:rotate-90 transition-transform"><path d="M3 2L7 5L3 8" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/></svg>
                        Reasoning
                      </summary>
                      <div className="mt-2 rounded-xl bg-zinc-800/50 border border-zinc-800 p-3 text-xs font-mono leading-relaxed text-zinc-400 whitespace-pre-wrap break-words">{String(m.thought).slice(0, 2000)}</div>
                    </details>
                  )}
                  <div className="text-sm leading-relaxed whitespace-pre-wrap break-words">{m.content}</div>
                  {m.tool_calls && (m.tool_calls as any[]).length > 0 && (
                    <div className="mt-2.5 flex flex-wrap gap-1.5">
                      {(m.tool_calls as any[]).map((c: any, j: number) => (
                        <span key={j} className="text-[11px] font-medium rounded-full bg-zinc-800 border border-zinc-700 text-zinc-400 px-2 py-1">{c.tool || c.name || "tool"}</span>
                      ))}
                    </div>
                  )}
                  {m.time && <div className={`mt-2 text-[11px] ${isUser ? "text-zinc-500" : "text-zinc-600"}`}>{new Date(m.time).toLocaleTimeString()}</div>}
                </div>
                {isUser && <div className="h-8 w-8 rounded-xl bg-white border border-zinc-200 grid place-items-center shrink-0 mt-0.5"><span className="text-xs">●</span></div>}
              </div>
            );
          })}
          {!showLiveLog && liveLog && messages.length > 0 && (
            <details className="rounded-2xl border border-zinc-800 bg-zinc-900 overflow-hidden">
              <summary className="h-8 px-3 flex items-center gap-2 text-xs font-medium text-zinc-400 cursor-pointer select-none hover:text-zinc-300">
                <span className="h-1.5 w-1.5 rounded-full bg-zinc-600" /> Live log tail ({(liveLog.length/1024).toFixed(1)} KB) — expand to see runner output
              </summary>
              <pre className="p-3 text-xs font-mono leading-relaxed whitespace-pre-wrap break-words max-h-[300px] overflow-auto text-zinc-500 border-t border-zinc-800">{liveLog.slice(-6000)}</pre>
            </details>
          )}
          {err && <div className="rounded-2xl border border-amber-900/50 bg-amber-950/20 p-3.5 text-sm leading-relaxed text-amber-200">{err}</div>}
        </div>
      </div>

      {/* Composer */}
      <div className="shrink-0 p-3 sm:p-4 border-t border-zinc-800 bg-zinc-900/30">
        <div className="max-w-3xl mx-auto">
          <div className="flex gap-2">
            <div className="flex-1 relative">
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
                placeholder={tunnelUrl ? "Send a message to the live agent…" : "Live tunnel appears ~30s after start — chat streams via live log meanwhile"}
                className="w-full h-11 rounded-2xl bg-zinc-900 border border-zinc-800 focus:border-zinc-700 focus:bg-zinc-900 outline-none px-4 pr-12 text-sm text-white placeholder:text-zinc-600 transition-colors"
              />
              <span className="absolute right-3 top-3 text-zinc-600">
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M8 3.5V12.5M3.5 8H12.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" opacity="0.5"/></svg>
              </span>
            </div>
            <button onClick={send} disabled={busy || !input.trim()} className="h-11 px-5 rounded-2xl bg-white hover:bg-zinc-100 text-zinc-900 font-medium text-sm disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex items-center gap-2 shrink-0">
              {busy ? <span className="h-4 w-4 border-2 border-zinc-300 border-t-zinc-900 rounded-full animate-spin" /> : <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M2 7H11M11 7L7 3M11 7L7 11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>}
              Send
            </button>
          </div>
          <div className="mt-2 flex items-center gap-2 text-[11px] text-zinc-600">
            <span>⏎ send · ⇧⏎ newline</span>
            <span className="hidden sm:inline">· {liveMode && tunnelUrl ? "Connected via Cloudflare tunnel" : liveLog ? "Streaming live log — tunnel appears shortly" : "Polling artifact"}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
