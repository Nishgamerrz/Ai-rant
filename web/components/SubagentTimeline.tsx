"use client";
import { useEffect, useState } from "react";

type SubagentCall = {
  id: string;
  topic?: string;
  kind?: string;
  instruction: string;
  input?: string;
  provider?: string;
  seconds?: number;
  fileEdited?: string;
  output?: string;
  text?: string;
  ok?: boolean;
  error?: string;
  live?: boolean;
};

function parseLiveLogForSubagent(tail: string): SubagentCall[] {
  const calls: SubagentCall[] = [];
  // Detect subagent tool blocks in live log: look for JSON with "tool":"subagent"
  const re = /"tool"\s*:\s*"subagent"[\s\S]{0,1200}?"instruction"\s*:\s*"([^"]{8,300})"/g;
  let m: RegExpExecArray | null;
  let idx = 0;
  while ((m = re.exec(tail)) !== null) {
    const instr = m[1];
    // try to get topic nearby
    const chunk = tail.slice(Math.max(0, m.index - 400), m.index + 1500);
    const topicMatch = chunk.match(/"topic"\s*:\s*"([^"]+)"/);
    const inputMatch = chunk.match(/"input"\s*:\s*"([^"]{0,200})"/);
    calls.push({
      id: `live-sub-${idx++}`,
      topic: topicMatch ? topicMatch[1] : "code",
      kind: "subagent",
      instruction: instr,
      input: inputMatch ? inputMatch[1] : "",
      provider: chunk.includes("groq") ? "groq" : chunk.includes("gemini") ? "gemini" : "live",
      output: "Delegated — waiting for sub-agent reply in log…",
      live: true,
      ok: undefined,
    });
    if (calls.length >= 6) break;
  }
  // Also detect the result line: [tool subagent] -> { ok, text, applied_to }
  const resRe = /\[tool subagent\][^\n]*->\s*(\{[^\n]{0,2000}\})/g;
  while ((m = resRe.exec(tail)) !== null) {
    try {
      const obj = JSON.parse(m[1]);
      calls.push({
        id: `live-res-${idx++}`,
        topic: obj.topic || "code",
        kind: "subagent",
        instruction: obj.instruction || "subagent result",
        provider: obj.provider || obj.model || "live",
        seconds: obj.seconds,
        fileEdited: obj.applied_to,
        output: obj.text || obj.output || JSON.stringify(obj).slice(0, 3000),
        ok: obj.ok,
        live: true,
      });
    } catch {}
    if (calls.length >= 8) break;
  }
  return calls.slice(0, 8);
}

export function SubagentTimeline({ runId, kind, liveLog }: { runId: number | null; kind: "agent" | "rbx"; liveLog?: string }) {
  const [calls, setCalls] = useState<SubagentCall[]>([]);
  const [liveCalls, setLiveCalls] = useState<SubagentCall[]>([]);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);

  // If liveLog prop provided, parse immediately
  useEffect(() => {
    if (liveLog && liveLog.length > 200) {
      const parsed = parseLiveLogForSubagent(liveLog);
      if (parsed.length) setLiveCalls(parsed);
    } else if (!liveLog) {
      setLiveCalls([]);
    }
  }, [liveLog]);

  useEffect(() => {
    if (!runId) {
      setCalls([]);
      return;
    }
    let cancelled = false;
    async function load() {
      setLoading(true);
      try {
        if (kind === "agent") {
          const txt = await fetch(`/api/github/artifact?run=${runId}&name=nish-agent-${runId}&json=agent_tools.jsonl`, { cache: "no-store" }).then((r) => r.text()).catch(() => "");
          if (cancelled) return;
          if (txt && txt.trim() && !txt.includes("Not Found") && !txt.includes("no artifact")) {
            const lines = txt.trim().split("\n").filter(Boolean);
            const parsed = lines.map((l) => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean);
            const subs: SubagentCall[] = [];
            for (const p of parsed) {
              if (p.tool === "subagent") {
                const out = p.output || {};
                subs.push({
                  id: p.input?.id || `sub-${subs.length}`,
                  topic: p.input?.topic || p.input?.instruction?.slice(0, 20) || "code",
                  kind: "subagent",
                  instruction: p.input?.instruction || p.input?.prompt || "",
                  input: p.input?.input || "",
                  provider: out.model || out.provider || (out.raw?.includes("groq") ? "groq" : out.ok ? "gemini" : "unknown"),
                  seconds: out.seconds,
                  fileEdited: out.applied_to || undefined,
                  output: out.text || out.output || JSON.stringify(out, null, 2).slice(0, 4000),
                  ok: out.ok,
                  error: out.error,
                });
              }
            }
            if (!cancelled) setCalls(subs);
            if (subs.length) {
              setLoading(false);
              return;
            }
          }
          // fallback: live log fetch if artifact empty
          if (!cancelled && !liveLog) {
            try {
              const lr = await fetch(`/api/github/logs?run=${runId}&logs=1`, { cache: "no-store" }).then((r) => r.json()).catch(() => null);
              if (lr?.logTail) {
                const parsedLive = parseLiveLogForSubagent(lr.logTail);
                if (!cancelled && parsedLive.length) setLiveCalls(parsedLive);
              }
            } catch {}
          }
        } else {
          // RBX: try to fetch subagent artifacts from main artifact
          const candidates = [
            `subagent_results.json`,
            `story_subagent_results.json`,
            `subagent_tasks.json`,
            `story_subagent_tasks.json`,
          ];
          const subs: SubagentCall[] = [];
          for (const name of candidates) {
            try {
              const res = await fetch(`/api/github/artifact?run=${runId}&name=Roblox-Story-Short-MP4&json=${name}`, { cache: "no-store" });
              if (!res.ok) continue;
              const ct = res.headers.get("content-type") || "";
              let data: any;
              if (ct.includes("json")) data = await res.json();
              else {
                const txt = await res.text();
                try { data = JSON.parse(txt); } catch { data = { raw: txt }; }
              }
              if (data?.results) {
                for (const r of data.results) {
                  subs.push({
                    id: r.id || `rbx-${subs.length}`,
                    topic: r.topic || r.kind || "map",
                    kind: r.kind || "write",
                    instruction: r.instruction || r.prompt || "",
                    input: r.input || "",
                    provider: r.provider || data.provider || (r.model?.includes("groq") ? "groq" : "gemini"),
                    seconds: r.seconds,
                    fileEdited: r.applied_to,
                    output: r.text || r.output || JSON.stringify(r, null, 2).slice(0, 5000),
                    ok: r.ok !== false,
                  });
                }
              } else if (Array.isArray(data?.tasks)) {
                for (const t of data.tasks) {
                  subs.push({
                    id: t.id || `task-${subs.length}`,
                    topic: t.topic || t.kind,
                    kind: t.kind,
                    instruction: t.instruction || "",
                    input: t.input || "",
                    output: "Awaiting result…",
                  });
                }
              }
            } catch {}
          }
          if (!cancelled) setCalls(subs);
          if (!subs.length && !liveLog) {
            // try live log for rbx as well
            try {
              const lr = await fetch(`/api/github/logs?run=${runId}&logs=1`, { cache: "no-store" }).then((r) => r.json()).catch(() => null);
              if (lr?.logTail) {
                const parsedLive = parseLiveLogForSubagent(lr.logTail);
                if (!cancelled && parsedLive.length) setLiveCalls(parsedLive);
              }
            } catch {}
          }
        }
      } catch {}
      if (!cancelled) setLoading(false);
    }
    load();
    const id = setInterval(load, 8000);
    return () => { cancelled = true; clearInterval(id); };
  }, [runId, kind, liveLog]);

  const display = calls.length ? calls : liveCalls;

  if (!runId) {
    return (
      <div className="rounded-2xl border border-dashed border-zinc-800 bg-zinc-900/20 p-6 text-center">
        <div className="text-xs font-semibold tracking-widest text-zinc-600 uppercase">Subagent</div>
        <div className="text-sm text-zinc-500 mt-1">Select a run to see subagent activity</div>
      </div>
    );
  }

  if (loading && display.length === 0) {
    return (
      <div className="rounded-2xl bg-zinc-900 border border-zinc-800 p-4 flex items-center gap-3">
        <span className="h-4 w-4 border-2 border-zinc-700 border-t-zinc-400 rounded-full animate-spin" />
        <span className="text-xs text-zinc-500">Loading subagent timeline…</span>
      </div>
    );
  }

  if (display.length === 0) {
    return (
      <div className="rounded-2xl bg-zinc-900 border border-zinc-800 p-4">
        <div className="flex items-center gap-2">
          <span className="h-6 w-6 rounded-lg bg-zinc-800 grid place-items-center">
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M6 1.5L2 3.5V8.5L6 10.5L10 8.5V3.5L6 1.5Z" stroke="#71717a" strokeWidth="1.1"/><path d="M6 1.5V10.5M2 3.5L6 5.5L10 3.5" stroke="#71717a" strokeWidth="1.1"/></svg>
          </span>
          <span className="text-xs font-semibold tracking-wide text-zinc-400">Subagent · No calls yet</span>
        </div>
        <div className="text-xs text-zinc-600 mt-2 leading-relaxed">
          The AI hasn’t delegated to the subagent for this run yet. Live log is polled every 3.5s — delegation appears here before artifacts upload. For Short, the first response must include a <code className="bg-zinc-800 px-1 rounded">map/cameras</code> + <code className="bg-zinc-800 px-1 rounded">models</code> task. For Agent, the first message must include a <code className="bg-zinc-800 px-1 rounded">subagent</code> tool call.
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-2xl bg-zinc-900 border border-zinc-800 overflow-hidden shadow-soft">
      <div className="h-10 px-3.5 flex items-center gap-2 border-b border-zinc-800 bg-zinc-900">
        <div className="h-6 w-6 rounded-lg bg-violet-600/15 border border-violet-800/30 grid place-items-center">
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M4 6L6 8L8 4" stroke="#a78bfa" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/><circle cx="6" cy="6" r="4.5" stroke="#a78bfa" strokeWidth="1.1" opacity="0.5"/></svg>
        </div>
        <span className="text-xs font-semibold tracking-wide text-zinc-200">Subagent</span>
        <span className="text-[11px] px-2 py-0.5 rounded-full bg-violet-600 text-white font-medium">{display.length} {display.length === 1 ? "task" : "tasks"}</span>
        {display[0]?.live && <span className="text-[11px] px-1.5 py-0.5 rounded-full bg-amber-950/40 border border-amber-900/50 text-amber-300">live log</span>}
        <span className="ml-auto text-[11px] text-zinc-600 hidden sm:inline">Gemini → Groq fallback · provider · seconds · file</span>
      </div>
      <div className="divide-y divide-zinc-800/60 max-h-[420px] overflow-auto">
        {display.map((c, idx) => {
          const isOpen = expanded === c.id;
          return (
            <div key={c.id + idx} className="p-3.5 hover:bg-zinc-800/20 transition-colors">
              <button onClick={() => setExpanded(isOpen ? null : c.id)} className="w-full text-left flex items-start gap-3">
                <span className={`mt-0.5 h-6 w-6 rounded-lg grid place-items-center shrink-0 border text-xs font-bold ${c.ok === false ? "bg-red-950/30 border-red-900 text-red-400" : c.live ? "bg-amber-950/30 border-amber-900 text-amber-300" : "bg-emerald-950/20 border-emerald-900/50 text-emerald-400"}`}>
                  {c.ok === false ? "×" : c.live ? "◐" : "✓"}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-xs font-semibold tracking-wide text-zinc-200">{c.id}</span>
                    <span className="text-[11px] px-1.5 py-0.5 rounded-full bg-zinc-800 border border-zinc-700 text-zinc-400 font-medium">{c.topic || "generic"} · {c.kind || "answer"}</span>
                    {c.provider && <span className="text-[11px] px-1.5 py-0.5 rounded-full bg-zinc-900 border border-zinc-800 text-zinc-500">{c.provider}</span>}
                    {c.seconds !== undefined && <span className="text-[11px] text-zinc-600">{c.seconds}s</span>}
                    {c.live && <span className="text-[11px] px-1 py-0.5 rounded bg-amber-950/30 text-amber-300 border border-amber-900/30">streaming</span>}
                  </div>
                  <div className="text-xs font-medium text-zinc-300 mt-1 line-clamp-2 leading-relaxed">{c.instruction || "(no instruction)"}</div>
                  {c.input && <div className="text-[11px] text-zinc-600 truncate mt-1">input: {String(c.input).slice(0, 120)}</div>}
                  {c.fileEdited && <div className="text-[11px] text-emerald-400 mt-1">→ {c.fileEdited}</div>}
                </div>
                <span className={`h-6 w-6 grid place-items-center rounded-lg border shrink-0 transition-colors ${isOpen ? "bg-zinc-800 border-zinc-700 text-zinc-300" : "bg-zinc-900 border-zinc-800 text-zinc-600"}`}>
                  <svg width="10" height="10" viewBox="0 0 10 10" fill="none" className={`${isOpen ? "rotate-180" : ""} transition-transform`}><path d="M2 4L5 7L8 4" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/></svg>
                </span>
              </button>
              {isOpen && (
                <div className="mt-3 space-y-3 animate-slideIn">
                  <div className="rounded-xl bg-zinc-950 border border-zinc-800 p-3">
                    <div className="text-[11px] font-semibold tracking-widest text-zinc-500 uppercase">Sent to subagent</div>
                    <div className="mt-2 text-xs font-mono leading-relaxed text-zinc-400 whitespace-pre-wrap break-words bg-zinc-900 rounded-lg p-2.5 border border-zinc-800">{c.instruction}</div>
                    {c.input && <div className="mt-2 text-xs font-mono leading-relaxed text-zinc-600 whitespace-pre-wrap break-words bg-zinc-900/50 rounded-lg p-2.5 border border-zinc-800/50">{String(c.input).slice(0, 3000)}</div>}
                  </div>
                  <div className="rounded-xl bg-violet-950/10 border border-violet-900/20 p-3">
                    <div className="text-[11px] font-semibold tracking-widest text-violet-300 uppercase">Returned {c.live ? "· live" : ""}</div>
                    <pre className="mt-2 text-xs font-mono leading-relaxed whitespace-pre-wrap break-words text-zinc-300 max-h-[320px] overflow-auto">{(c.output || c.text || "(empty)").slice(0, 8000)}</pre>
                    {c.error && <div className="mt-2 text-xs text-red-400">Error: {c.error}</div>}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
