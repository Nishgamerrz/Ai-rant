"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { SubagentTimeline } from "./SubagentTimeline";
import { encodeFaceReference } from "@/lib/faceReference";

type Msg = { role: string; content: string; thought?: string; tool_calls?: any[]; time?: string; tool?: string; output?: any; id?: string; queue_id?: string; delivery?: string };

function parseLiveLogTail(tail: string): { msgs: Msg[]; tools: any[] } {
  const msgs: Msg[] = [];
  const tools: any[] = [];
  const lines = tail.split("\n");
  let buf = "";
  let inAnswer = false;
  for (const ln of lines) {
    // thinking box: look for boxed thinking already handled in RawLogBlock, but also capture for msg
    if (ln.includes("answer") && ln.includes("▸")) {
      inAnswer = true;
      buf = ln.slice(ln.indexOf("{"));
      try {
        const obj = JSON.parse(buf);
        if (obj.answer || obj.tool_calls) {
          msgs.push({ role: "assistant", content: String(obj.answer || ""), tool_calls: obj.tool_calls || [], time: new Date().toISOString() });
          inAnswer = false;
          buf = "";
        }
      } catch {}
    } else if (inAnswer) {
      buf += "\n" + ln;
      try {
        const obj = JSON.parse(buf);
        msgs.push({ role: "assistant", content: String(obj.answer || ""), tool_calls: obj.tool_calls || [], time: new Date().toISOString() });
        inAnswer = false;
        buf = "";
      } catch {
        if (buf.length > 9000) inAnswer = false;
      }
    }
    if (ln.includes("Prompt:")) {
      const p = ln.split("Prompt:").slice(1).join("Prompt:").trim().slice(0, 500);
      if (p) msgs.push({ role: "user", content: p, time: new Date().toISOString() });
    }
    // tool lines: [tool xxx] -> {ok:...}
    if (ln.includes("[tool ") && ln.includes("->")) {
      try {
        const m = ln.match(/\[tool ([^\]]+)\].*->\s*(\{.*\})/);
        if (m) {
          const tool = m[1].trim();
          const out = JSON.parse(m[2]);
          tools.push({ tool, output: out, input: {} });
        }
      } catch {}
    }
    if (ln.includes("[gemini sub-agent]") || ln.includes("Subagent")) {
      // capture subagent as tool too
    }
  }
  return { msgs, tools };
}

export function ChatWindow({ runId, notice = "" }: { runId: number | null; notice?: string }) {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [tools, setTools] = useState<any[]>([]);
  const [liveLog, setLiveLog] = useState<string>("");
  const [liveMsgs, setLiveMsgs] = useState<Msg[]>([]);
  const [liveTools, setLiveTools] = useState<any[]>([]);
  const [status, setStatus] = useState("idle");
  const [err, setErr] = useState("");
  const [chatToken, setChatToken] = useState("");
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [uploadingReference, setUploadingReference] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const scrollerRef = useRef<HTMLDivElement>(null);

  const fetchChat = useCallback(async () => {
    if (!runId) return;
    let artifactMessages: Msg[] = [];
    try {
      const res = await fetch(`/api/github/artifact?run=${runId}&name=nish-agent-${runId}&json=agent_chat.json`, { cache: "no-store" });
      if (res.ok) {
        const ct = res.headers.get("content-type") || "";
        let data: any;
        if (ct.includes("json")) data = await res.json();
        else {
          const txt = await res.text();
          try { data = JSON.parse(txt); } catch { data = null; }
        }
        if (Array.isArray(data)) artifactMessages = data;
      }
    } catch {}

    let queuedMessages: Msg[] = [];
    if (chatToken) {
      try {
        const response = await fetch(`/api/agent/chat?run=${runId}`, {
          headers: { Authorization: `Bearer ${chatToken}` }, cache: "no-store",
        });
        if (response.ok) {
          const data = await response.json();
          queuedMessages = (data.messages || []).map((item: any) => ({
            role: "user", content: String(item.message || ""), time: item.createdAt,
            id: item.id, queue_id: item.clientId || item.id, delivery: "queued",
          }));
        }
      } catch {}
    }

    const toolsRes = await fetch(`/api/github/artifact?run=${runId}&name=nish-agent-${runId}&json=agent_tools.jsonl`, { cache: "no-store" }).then((r) => r.text()).catch(() => "");
    if (toolsRes && toolsRes.trim()) {
      const lines = toolsRes.trim().split("\n").filter(Boolean);
      const parsed = lines.map((l) => { try { return JSON.parse(l); } catch { return { raw: l }; } }).slice(-20);
      if (parsed.length) setTools(parsed);
    }

    setMessages((previous) => {
      const merged = [...artifactMessages];
      for (const item of queuedMessages) {
        if (!merged.some((message) => message.queue_id === item.queue_id)) merged.push(item);
      }
      for (const pending of previous.filter((message) => message.delivery === "sending" || message.delivery === "failed" || message.delivery === "queued")) {
        if (!merged.some((message) => message.queue_id === pending.queue_id)) merged.push(pending);
      }
      return merged;
    });
  }, [runId, chatToken]);

  const fetchLive = useCallback(async () => {
    if (!runId) return;
    try {
      const res = await fetch(`/api/github/logs?run=${runId}&logs=1`, { cache: "no-store" });
      const j = await res.json();
      if (j.run) setStatus(`${j.run.status}${j.run.conclusion ? " · " + j.run.conclusion : ""}`);
      if (j.logTail) {
        setLiveLog(j.logTail);
        const parsed = parseLiveLogTail(j.logTail);
        if (parsed.msgs.length) setLiveMsgs(parsed.msgs);
        if (parsed.tools.length) setLiveTools(parsed.tools);
      }
    } catch {}
  }, [runId]);

  async function sendMessage(event: any) {
    event.preventDefault();
    const message = draft.trim();
    if (!runId || !chatToken || !message || sending) return;
    if (!status.includes("in_progress") && !status.includes("queued")) {
      setErr("This agent run has ended. Start a new workflow to send another prompt.");
      return;
    }
    const clientId = typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    const optimistic: Msg = {
      role: "user", content: message, time: new Date().toISOString(),
      queue_id: clientId, delivery: "sending",
    };
    setMessages((previous) => [...previous, optimistic]);
    setDraft("");
    setSending(true);
    setErr("");
    try {
      const response = await fetch("/api/agent/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${chatToken}` },
        body: JSON.stringify({ runId, message, clientId }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || "Message could not be delivered");
      setMessages((previous) => previous.map((item) => item.queue_id === clientId
        ? { ...item, id: data.message?.id, delivery: "queued", time: data.message?.createdAt || item.time }
        : item));
    } catch (error: any) {
      const messageText = String(error?.message || error);
      setMessages((previous) => previous.map((item) => item.queue_id === clientId
        ? { ...item, delivery: "failed" }
        : item));
      setErr(messageText);
    } finally {
      setSending(false);
    }
  }

  async function uploadFaceReference(file: File) {
    if (!runId || !chatToken) {
      setErr("This run has no registered image/chat session. Start a new Agent workflow first.");
      return;
    }
    if (!status.includes("in_progress") && !status.includes("queued") && status !== "idle") {
      setErr("This agent run has ended; it cannot accept another image.");
      return;
    }
    const clientId = typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID() : `image-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    setUploadingReference(true);
    setErr("");
    try {
      const encoded = await encodeFaceReference(file);
      const response = await fetch("/api/agent/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${chatToken}` },
        body: JSON.stringify({ runId, action: "image", ...encoded, clientId }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || "Reference image could not be queued");
      setMessages((previous) => [...previous, {
        role: "user", content: data.message?.message || "Supplied face reference image.",
        time: data.message?.createdAt || new Date().toISOString(), id: data.message?.id,
        queue_id: clientId, delivery: "queued",
      }]);
    } catch (error: any) {
      setErr(String(error?.message || error));
    } finally {
      setUploadingReference(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  useEffect(() => {
    setChatToken(runId ? sessionStorage.getItem(`nishagent_chat_${runId}`) || "" : "");
    setDraft("");
    setSending(false);
    setErr("");
  }, [runId]);

  useEffect(() => {
    if (!runId) {
      setMessages([]);
      setTools([]);
      setLiveLog("");
      setLiveMsgs([]);
      setLiveTools([]);
      setStatus("idle");
      return;
    }
    fetchChat();
    fetchLive();
    const id = setInterval(() => { fetchChat(); fetchLive(); }, 3500);
    return () => clearInterval(id);
  }, [runId, chatToken, fetchChat, fetchLive]);

  useEffect(() => {
    scrollerRef.current?.scrollTo({ top: scrollerRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, liveMsgs, liveLog, tools, liveTools]);

  if (!runId) {
    return (
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="max-w-md w-full text-center">
          <div className="h-14 w-14 rounded-2xl bg-zinc-900 border border-zinc-800 grid place-items-center mx-auto shadow-soft">
            <svg width="22" height="22" viewBox="0 0 22 22" fill="none"><path d="M7 7H15M7 11H15M7 15H12" stroke="#a1a1aa" strokeWidth="1.4" strokeLinecap="round"/><rect x="3.5" y="2.5" width="15" height="17" rx="2" stroke="#27272a" strokeWidth="1.2"/></svg>
          </div>
          <h2 className="mt-4 text-[15px] font-semibold tracking-tight">Select a workflow</h2>
          <p className="mt-1.5 text-sm leading-relaxed text-zinc-500">Choose a run from the sidebar or create a new one. Live thinking, tool calls, and files stream here in real time via direct GitHub API — no tunnel needed.</p>
        </div>
      </div>
    );
  }

  const displayMessages = messages.length ? messages : liveMsgs;
  const displayTools = tools.length ? tools : liveTools;
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
            <span className="hidden sm:inline-flex items-center gap-1.5 text-[11px] px-2 py-0.5 rounded-full bg-zinc-800 border border-zinc-700 text-zinc-400">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" /> Direct API
            </span>
          </div>
          <div className="text-[11px] text-zinc-600">
            {liveLog ? `${(liveLog.length/1024).toFixed(1)} KB live log · ${displayTools.length} tools · ${displayMessages.length} messages — direct GitHub API` : `Artifact polling · ${displayTools.length} tools · ${displayMessages.length} messages`}
          </div>
        </div>
        <a href={`https://github.com/Nishgamerrz/Ai-rant/actions/runs/${runId}`} target="_blank" className="h-8 px-3 rounded-xl bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 text-xs font-medium text-zinc-300 hover:text-white transition-colors hidden sm:flex items-center gap-1.5">
          GitHub <svg width="10" height="10" viewBox="0 0 10 10" fill="none"><path d="M3 7L7 3M7 3H4M7 3V6" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/></svg>
        </a>
      </div>

      {/* Subagent timeline — always visible via direct API */}
      {runId && (
        <div className="shrink-0 border-b border-zinc-800/60 bg-zinc-900/30 px-3 py-2">
          <SubagentTimeline runId={runId} kind="agent" liveLog={liveLog || undefined} />
        </div>
      )}

      {/* Tool chips + detailed execution — direct from artifact or live log */}
      {displayTools.length > 0 && (
        <>
          <div className="shrink-0 px-3 py-2 border-b border-zinc-800/60 bg-zinc-900/20 flex gap-1.5 overflow-x-auto scrollbar-thin">
            {displayTools.slice(-10).map((t, i) => (
              <span key={i} className="shrink-0 inline-flex items-center gap-1.5 text-[11px] font-medium rounded-full bg-zinc-900 border border-zinc-800 text-zinc-400 px-2.5 py-1">
                <span className={`h-1.5 w-1.5 rounded-full ${t.output?.ok === false ? "bg-red-500" : t.output?.ok ? "bg-emerald-500" : "bg-violet-500"}`} />
                {t.tool || "tool"} <span className="text-zinc-600 hidden sm:inline">· {String(t.input?.query || t.input?.path || t.input?.cmd || t.input?.instruction || "").slice(0, 22) || "…"}</span>
              </span>
            ))}
          </div>
          <div className="shrink-0 border-b border-zinc-800/60 bg-zinc-900/30 max-h-[220px] overflow-auto divide-y divide-zinc-800/50">
            {displayTools.slice(-4).reverse().map((t, i) => {
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

      {/* Messages + Live log — single persistent plan box */}
      <div ref={scrollerRef} className="flex-1 overflow-auto">
        <div className="max-w-3xl mx-auto w-full p-4 sm:p-6 space-y-4">
          {showLiveLog && (
            <div className="rounded-2xl border border-zinc-800 bg-zinc-900 overflow-hidden">
              <div className="h-8 px-3 flex items-center gap-2 border-b border-zinc-800 bg-zinc-900">
                <span className="h-2 w-2 rounded-full bg-amber-500 animate-pulse" />
                <span className="text-xs font-semibold tracking-wide text-zinc-300">Live — persistent plan · thinking & tools (direct API)</span>
                <span className="ml-auto text-[11px] text-zinc-600">streams until workflow dies</span>
              </div>
              <pre className="p-3 text-xs font-mono leading-relaxed whitespace-pre-wrap break-words max-h-[520px] overflow-auto text-zinc-300">
                {liveLog.slice(-9000)}
              </pre>
              <div className="px-3 py-2 border-t border-zinc-800 bg-zinc-950 text-[11px] text-zinc-500">This is the single persistent plan box — it stays alive until the workflow timeout, showing every thought, tool, and file via direct GitHub API polling. No Cloudflare tunnel.</div>
            </div>
          )}
          {displayMessages.length === 0 && !liveLog && (
            <div className="rounded-2xl border border-dashed border-zinc-800 bg-zinc-900/20 p-6 text-center">
              <div className="text-sm font-medium text-zinc-300">Waiting for agent</div>
              <div className="text-xs text-zinc-600 mt-1 leading-relaxed">The workflow is starting (model loading can take 60–90s). Thinking, tool calls, and files stream here live via direct API — the last plan stays active until the run finishes.</div>
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
                  {(m.time || (isUser && m.delivery)) && <div className={`mt-2 flex items-center gap-2 text-[11px] ${isUser ? "text-zinc-500" : "text-zinc-600"}`}>
                    {m.time && <span>{new Date(m.time).toLocaleTimeString()}</span>}
                    {isUser && m.delivery && <span>{m.delivery === "failed" ? "not sent" : m.delivery === "sending" ? "sending…" : "queued to this run"}</span>}
                  </div>}
                </div>
                {isUser && <div className="h-8 w-8 rounded-xl bg-white border border-zinc-200 grid place-items-center shrink-0 mt-0.5"><span className="text-xs">●</span></div>}
              </div>
            );
          })}
          {!showLiveLog && liveLog && messages.length > 0 && (
            <details className="rounded-2xl border border-zinc-800 bg-zinc-900 overflow-hidden">
              <summary className="h-8 px-3 flex items-center gap-2 text-xs font-medium text-zinc-400 cursor-pointer select-none hover:text-zinc-300">
                <span className="h-1.5 w-1.5 rounded-full bg-zinc-600" /> Live log tail ({(liveLog.length/1024).toFixed(1)} KB) — persistent plan still streaming
              </summary>
              <pre className="p-3 text-xs font-mono leading-relaxed whitespace-pre-wrap break-words max-h-[300px] overflow-auto text-zinc-500 border-t border-zinc-800">{liveLog.slice(-6000)}</pre>
            </details>
          )}
          {err && <div className="rounded-2xl border border-amber-900/50 bg-amber-950/20 p-3.5 text-sm leading-relaxed text-amber-200">{err}</div>}
        </div>
      </div>

      {/* Same-run message composer — encrypted GitHub Actions variable queue, no tunnel */}
      <div className="shrink-0 p-3 sm:p-4 border-t border-zinc-800 bg-zinc-900/30">
        <div className="max-w-3xl mx-auto">
          {chatToken && (status === "idle" || status.includes("in_progress") || status.includes("queued")) ? (
            <form onSubmit={sendMessage} className="rounded-2xl bg-zinc-950 border border-zinc-800 focus-within:border-zinc-700 p-2 flex items-end gap-2">
              <input ref={fileInputRef} type="file" accept="image/*" className="hidden" aria-label="Attach a face reference image" onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void uploadFaceReference(file);
              }} />
              <textarea
                value={draft}
                onChange={(event) => setDraft(event.target.value.slice(0, 4000))}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    if (draft.trim() && !sending) void sendMessage(event);
                  }
                }}
                placeholder="Send a follow-up to this same running plan…"
                rows={1}
                maxLength={4000}
                className="min-h-10 max-h-32 flex-1 resize-y bg-transparent outline-none px-2 py-2 text-sm text-zinc-100 placeholder:text-zinc-600"
                aria-label="Message the active agent run"
              />
              <button type="button" onClick={() => fileInputRef.current?.click()} disabled={uploadingReference || sending} className="h-9 px-3 rounded-xl border border-zinc-700 bg-zinc-900 text-zinc-300 text-xs font-medium hover:bg-zinc-800 disabled:opacity-40 transition-colors" title="Upload and encrypt a face reference image">
                {uploadingReference ? "Photo…" : "Photo"}
              </button>
              <button type="submit" disabled={!draft.trim() || sending || uploadingReference} className="h-9 px-3.5 rounded-xl bg-white text-zinc-900 text-xs font-semibold hover:bg-zinc-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
                {sending ? "Sending…" : "Send"}
              </button>
              <div className="absolute sr-only" aria-live="polite">{err}</div>
            </form>
          ) : (
            <div className="rounded-xl bg-zinc-800/50 border border-zinc-800 px-3 py-2.5 text-xs leading-relaxed text-zinc-400">
              {!chatToken && (status.includes("in_progress") || status.includes("queued"))
                ? "This older run has no registered live-message session. Start a new Agent workflow to chat in the same plan."
                : status.includes("completed") || status.includes("success") || status.includes("failure")
                  ? "This run has ended. Start a new workflow to continue."
                  : "Select an active Agent run to send a follow-up in the same persistent plan. Logs and artifacts use the direct GitHub API — no Cloudflare tunnel."}
            </div>
          )}
          {notice && <div className="mt-2 text-xs text-amber-300" role="status">{notice}</div>}
          {err && <div className="mt-2 text-xs text-amber-300" role="status">{err}</div>}
          {chatToken && <div className="mt-1.5 px-1 text-[10px] text-zinc-600">Enter to send · Shift+Enter for a new line · same run · direct GitHub API</div>}
        </div>
      </div>
    </div>
  );
}
