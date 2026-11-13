"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ModelSelector } from "@/components/ModelSelector";
import { LogViewer } from "@/components/LogViewer";
import { FileExplorer } from "@/components/FileExplorer";
import { SubagentTimeline } from "@/components/SubagentTimeline";

type Run = { id: number; display_title: string; status: string; conclusion: string | null; created_at: string; html_url: string };

function StatusBadge({ status, conclusion }: { status: string; conclusion: string | null }) {
  const isRunning = status !== "completed";
  const isSuccess = conclusion === "success";
  const isFailed = conclusion === "failure";
  return (
    <span className={`inline-flex items-center gap-1.5 text-[11px] font-semibold tracking-wide px-2 py-1 rounded-full border ${
      isRunning ? "bg-amber-950/30 border-amber-900 text-amber-300" : isSuccess ? "bg-emerald-950/30 border-emerald-900 text-emerald-300" : isFailed ? "bg-red-950/30 border-red-900 text-red-300" : "bg-zinc-800 border-zinc-700 text-zinc-400"
    }`}>
      <span className={`h-1.5 w-1.5 rounded-full ${isRunning ? "bg-amber-400 animate-pulse" : isSuccess ? "bg-emerald-400" : isFailed ? "bg-red-400" : "bg-zinc-500"}`} />
      {isRunning ? status.toUpperCase() : (conclusion || status).toUpperCase()}
    </span>
  );
}

export default function RbxShortPage() {
  const [storyTopic, setStoryTopic] = useState("In a world where the last person to fall asleep each night gets one wish, two brothers keep each other awake on purpose in a cramped bedroom");
  const [usernames, setUsernames] = useState("normal,noob");
  const [duration, setDuration] = useState("150");
  const [mapDetail, setMapDetail] = useState("dense");
  const [model, setModel] = useState("hard");
  const [voice, setVoice] = useState("thin_male");
  const [worldTheme, setWorldTheme] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [steps, setSteps] = useState<any[]>([]);
  const [status, setStatus] = useState("idle");
  const [artifacts, setArtifacts] = useState<any[]>([]);
  const [tab, setTab] = useState<"overview" | "execution" | "intelligence" | "files">("overview");
  const [intelligence, setIntelligence] = useState<{ plan?: string; narration?: string; thinking?: string; loading: boolean }>({ loading: false });
  const [deleting, setDeleting] = useState<number | null>(null);
  const [preview, setPreview] = useState<{ path: string; content: string } | null>(null);
  const [liveLog, setLiveLog] = useState<string>("");

  // Handle ?run= param
  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    const r = q.get("run");
    if (r) setSelected(Number(r));
  }, []);

  async function loadRuns() {
    try {
      const j = await fetch("/api/github/runs?kind=rbx&per_page=16", { cache: "no-store" }).then((r) => r.json());
      if (j.runs) setRuns(j.runs);
    } catch {}
  }
  useEffect(() => {
    loadRuns();
    const id = setInterval(loadRuns, 8000);
    return () => clearInterval(id);
  }, []);

  const poll = useCallback(async () => {
    if (!selected) return;
    try {
      const j = await fetch(`/api/github/logs?run=${selected}&logs=1`, { cache: "no-store" }).then((r) => r.json());
      if (j.steps) setSteps(j.steps);
      if (j.run) setStatus(`${j.run.status}${j.run.conclusion ? " · " + j.run.conclusion : ""}`);
      if (j.logTail) setLiveLog(j.logTail);
      if (j.artifacts) setArtifacts(j.artifacts);
    } catch {}
  }, [selected]);
  useEffect(() => {
    if (!selected) {
      setSteps([]);
      setStatus("idle");
      setArtifacts([]);
      setLiveLog("");
      return;
    }
    setTab("execution");
    poll();
    const id = setInterval(poll, 3500);
    return () => clearInterval(id);
  }, [selected, poll]);

  const fetchIntelligence = useCallback(async () => {
    if (!selected || tab !== "intelligence") return;
    setIntelligence({ loading: true });
    try {
      // Try to fetch plan, narration, and log-derived thinking from artifacts
      const tryFetch = async (name: string) => {
        try {
          const res = await fetch(`/api/github/artifact?run=${selected}&name=Roblox-Story-Short-MP4&json=${name}`, { cache: "no-store" });
          if (res.ok) {
            const ct = res.headers.get("content-type") || "";
            if (ct.includes("json")) return JSON.stringify(await res.json(), null, 2);
            return await res.text();
          }
        } catch {}
        return null;
      };
      // RBX artifacts are often named Roblox-Story-Short-MP4, but also check generic
      const plan = await tryFetch("Roblox_Story_Map.json") || await tryFetch("map.json") || null;
      const narration = await tryFetch("narration.txt") || null;
      // Also try agent chat equivalent if present
      setIntelligence({ plan: plan || undefined, narration: narration || undefined, loading: false });
    } catch {
      setIntelligence({ loading: false });
    }
  }, [selected, tab]);
  useEffect(() => { fetchIntelligence(); }, [fetchIntelligence]);

  async function dispatch() {
    setBusy(true);
    setMsg(null);
    const before = Date.now();
    try {
      const res = await fetch("/api/github/dispatch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          kind: "rbx",
          story_topic: storyTopic,
          character_usernames: usernames,
          duration_seconds: duration,
          map_detail: mapDetail,
          model_quality: model,
          voice_style: voice,
          world_theme: worldTheme,
        }),
      });
      const j = await res.json();
      if (!res.ok) {
        // 409 = workflow already running / dispatch throttled — still poll for the run
        if (res.status === 409 || String(j.error||"").includes("409") || String(j.error||"").toLowerCase().includes("already")) {
          setMsg({ text: "Dispatch accepted (workflow already queued) — tracking latest run…", ok: true });
        } else throw new Error(j.error);
      } else {
        setMsg({ text: "Workflow dispatched. Tracking new run…", ok: true });
      }
      // Poll for new run and select it
      for (let i = 0; i < 10; i++) {
        await new Promise((r) => setTimeout(r, 1400));
        await loadRuns();
        try {
          const rj = await fetch("/api/github/runs?kind=rbx&per_page=5", { cache: "no-store" }).then((r) => r.json());
          const newest = rj?.runs?.[0];
          if (newest && new Date(newest.created_at).getTime() > before - 5000) {
            setSelected(newest.id);
            setTab("execution");
            setMsg({ text: `Run #${newest.id} started — viewing live execution.`, ok: true });
            break;
          }
        } catch {}
      }
    } catch (e: any) {
      setMsg({ text: String(e.message || e), ok: false });
    } finally {
      setBusy(false);
    }
  }

  async function delRun(id: number) {
    if (!confirm(`Delete run #${id}?`)) return;
    setDeleting(id);
    try {
      const res = await fetch(`/api/github/delete?run=${id}`, { method: "DELETE" });
      const j = await res.json();
      if (!res.ok) throw new Error(j.error || "delete failed");
      setRuns((prev) => prev.filter((r) => r.id !== id));
      if (selected === id) setSelected(null);
    } catch (e: any) {
      alert("Delete failed: " + String(e.message || e));
    } finally {
      setDeleting(null);
    }
  }

  return (
    <div className="min-h-screen bg-[#09090b]">
      {/* Header */}
      <div className="sticky top-0 z-20 bg-[#09090b]/80 backdrop-blur-xl border-b border-zinc-800/80">
        <div className="max-w-[1280px] mx-auto px-4 sm:px-6 h-14 flex items-center gap-4">
          <Link href="/" className="h-8 w-8 rounded-xl bg-zinc-900 border border-zinc-800 grid place-items-center hover:bg-zinc-800 transition-colors">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M8 3L3 7L8 11" stroke="#a1a1aa" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/></svg>
          </Link>
          <div className="min-w-0">
            <div className="text-sm font-semibold tracking-tight flex items-center gap-2">Roblox Short Studio <span className="hidden sm:inline-flex text-[11px] px-2 py-0.5 rounded-full bg-zinc-900 border border-zinc-800 text-zinc-500 font-medium">nishagent.vercel.app/rbxshort</span></div>
            <div className="text-xs text-zinc-500 hidden sm:block">Furnished worlds · cinematic cameras · voice & captions — all from one workflow</div>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <Link href="/" className="hidden sm:flex h-8 px-3 rounded-xl bg-zinc-900 border border-zinc-800 text-xs font-medium text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 transition-colors items-center gap-1.5">Agent <svg width="10" height="10" viewBox="0 0 10 10" fill="none"><path d="M3 7L7 3M7 3H4M7 3V6" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/></svg></Link>
          </div>
        </div>
      </div>

      <div className="max-w-[1280px] mx-auto px-4 sm:px-6 py-6 grid grid-cols-1 lg:grid-cols-[420px_1fr] gap-6">
        {/* Left: Form */}
        <div className="space-y-4">
          <div className="rounded-2xl bg-zinc-900 border border-zinc-800 shadow-soft overflow-hidden">
            <div className="p-5 border-b border-zinc-800">
              <h2 className="text-[13px] font-semibold tracking-tight">Create Short</h2>
              <p className="text-xs text-zinc-500 mt-1 leading-relaxed">Inputs map directly to the GitHub workflow. Dispatch is secured server-side.</p>
            </div>
            <div className="p-5 space-y-4">
              <div>
                <label className="text-[11px] font-semibold tracking-widest text-zinc-500 uppercase">Story topic</label>
                <textarea value={storyTopic} onChange={(e) => setStoryTopic(e.target.value)} rows={3} className="mt-2 w-full rounded-xl bg-zinc-950 border border-zinc-800 focus:border-zinc-700 focus:bg-zinc-900 outline-none p-3 text-sm leading-relaxed resize-none transition-colors" />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-[11px] font-semibold tracking-widest text-zinc-500 uppercase">Cast</label>
                  <input value={usernames} onChange={(e) => setUsernames(e.target.value)} placeholder="normal,noob" className="mt-2 w-full rounded-xl bg-zinc-950 border border-zinc-800 focus:border-zinc-700 outline-none px-3 py-2.5 text-sm transition-colors" />
                  <div className="text-[11px] text-zinc-600 mt-1">Comma separated</div>
                </div>
                <div>
                  <label className="text-[11px] font-semibold tracking-widest text-zinc-500 uppercase">Short timing</label>
                  <select value={duration} onChange={(e) => setDuration(e.target.value)} className="mt-2 w-full rounded-xl bg-zinc-950 border border-zinc-800 focus:border-zinc-700 outline-none px-3 py-2.5 text-sm">
                    <option value="30">30s</option><option value="45">45s</option><option value="60">60s</option><option value="90">90s</option><option value="120">120s</option><option value="150">150s</option><option value="180">180s</option>
                  </select>
                  <div className="text-[11px] leading-relaxed text-zinc-600 mt-1">AI chooses the exact ending within the selected minute band. For example, 60s can end at 1:45, never 2:01.</div>
                </div>
                <div>
                  <label className="text-[11px] font-semibold tracking-widest text-zinc-500 uppercase">Detail</label>
                  <select value={mapDetail} onChange={(e) => setMapDetail(e.target.value)} className="mt-2 w-full rounded-xl bg-zinc-950 border border-zinc-800 focus:border-zinc-700 outline-none px-3 py-2.5 text-sm">
                    <option value="standard">Standard</option><option value="dense">Dense</option><option value="ultra">Ultra</option>
                  </select>
                </div>
                <div>
                  <label className="text-[11px] font-semibold tracking-widest text-zinc-500 uppercase">Voice</label>
                  <select value={voice} onChange={(e) => setVoice(e.target.value)} className="mt-2 w-full rounded-xl bg-zinc-950 border border-zinc-800 focus:border-zinc-700 outline-none px-3 py-2.5 text-sm">
                    <option value="male">Male</option><option value="female">Female</option><option value="thin_male">Thin male</option>
                  </select>
                </div>
              </div>

              <div>
                <label className="text-[11px] font-semibold tracking-widest text-zinc-500 uppercase">World theme <span className="normal-case tracking-normal font-normal text-zinc-600">· optional</span></label>
                <input value={worldTheme} onChange={(e) => setWorldTheme(e.target.value)} placeholder="Auto from story" className="mt-2 w-full rounded-xl bg-zinc-950 border border-zinc-800 focus:border-zinc-700 outline-none px-3 py-2.5 text-sm" />
              </div>
              <p className="text-[11px] leading-relaxed text-zinc-600">Lighting is planned automatically from the story and reference look, with changes on meaningful scene beats.</p>

              <ModelSelector value={model} onChange={setModel} />

              <button onClick={dispatch} disabled={busy} className="w-full h-11 rounded-xl bg-white hover:bg-zinc-100 text-zinc-900 font-semibold text-sm disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2 shadow-soft">
                {busy ? <><span className="h-4 w-4 border-2 border-zinc-300 border-t-zinc-900 rounded-full animate-spin" /> Dispatching…</> : <>Generate short <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M5 3L9 7L5 11" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/></svg></>}
              </button>

              {msg && <div className={`rounded-xl border p-3 text-sm leading-relaxed ${msg.ok ? "bg-emerald-950/20 border-emerald-900/50 text-emerald-300" : "bg-red-950/20 border-red-900/50 text-red-300"}`}>{msg.text}</div>}
            </div>
          </div>

          <div className="rounded-2xl bg-zinc-900/50 border border-zinc-800 p-4">
            <div className="text-xs font-semibold tracking-wide text-zinc-300">How it works — direct API</div>
            <div className="text-xs text-zinc-500 leading-relaxed mt-1.5">No tunnel. Every thought, plan, and tool streams via direct GitHub API polling. The last plan is one persistent box that stays alive until the workflow dies.</div>
          </div>
        </div>

        {/* Right: Runs + Detail — also supports polling subagent */}
        <div className="min-w-0 space-y-4">
          {/* Runs list */}
          <div className="rounded-2xl bg-zinc-900 border border-zinc-800 shadow-soft overflow-hidden">
            <div className="h-12 px-4 flex items-center gap-3 border-b border-zinc-800">
              <h3 className="text-sm font-semibold tracking-tight">Recent runs</h3>
              <span className="text-xs text-zinc-600">{runs.length} total</span>
              <button onClick={loadRuns} className="ml-auto h-7 px-2.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 text-xs font-medium text-zinc-400 hover:text-zinc-200 transition-colors">Reload</button>
            </div>
            <div className="p-2 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2 gap-2 max-h-[280px] overflow-auto">
              {runs.length === 0 && <div className="col-span-full px-3 py-8 text-center text-sm text-zinc-600">No runs yet — create your first short.</div>}
              {runs.map((r) => {
                const active = selected === r.id;
                return (
                  <button
                    key={r.id}
                    onClick={() => setSelected(r.id)}
                    className={`group relative text-left rounded-xl border p-3 transition-all ${active ? "bg-white border-white shadow-soft" : "bg-zinc-950 border-zinc-800 hover:bg-zinc-900 hover:border-zinc-700"}`}
                  >
                    <div className="flex items-center gap-2">
                      <span className={`h-2 w-2 rounded-full shrink-0 ${r.status !== "completed" ? "bg-amber-500 animate-pulse" : r.conclusion === "success" ? "bg-emerald-500" : r.conclusion === "failure" ? "bg-red-500" : "bg-zinc-500"}`} />
                      <span className={`text-[11px] font-semibold tracking-wide truncate ${active ? "text-zinc-600" : "text-zinc-500"}`}>{r.status === "completed" ? (r.conclusion?.toUpperCase() || "DONE") : r.status.toUpperCase()}</span>
                      <span className={`ml-auto text-[11px] ${active ? "text-zinc-500" : "text-zinc-600"}`}>{new Date(r.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
                    </div>
                    <div className={`text-sm font-medium truncate mt-1.5 ${active ? "text-zinc-900" : "text-zinc-200"}`}>{r.display_title || `Run #${r.id}`}</div>
                    <div className={`text-xs truncate ${active ? "text-zinc-600" : "text-zinc-600"}`}>#{r.id} · {new Date(r.created_at).toLocaleDateString()}</div>
                    <button
                      onClick={(e) => { e.stopPropagation(); delRun(r.id); }}
                      disabled={deleting === r.id}
                      className={`absolute top-2 right-2 h-6 w-6 grid place-items-center rounded-lg opacity-0 group-hover:opacity-100 transition-all ${active ? "bg-zinc-900 text-white hover:bg-zinc-800" : "bg-zinc-800 text-zinc-500 hover:text-red-400 hover:bg-zinc-700"} disabled:opacity-50`}
                      title="Delete run"
                    >
                      {deleting === r.id ? <span className="h-3 w-3 border border-zinc-600 border-t-zinc-300 rounded-full animate-spin" /> : <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M3 3.5L3 8.5M8 3.5L8 8.5M1.5 3.5H9.5M3.5 3.5V2.5H7.5V3.5" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round"/></svg>}
                    </button>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Detail */}
          {selected ? (
            <div className="rounded-2xl bg-zinc-900 border border-zinc-800 shadow-soft overflow-hidden">
              <div className="px-4 pt-4">
                <div className="flex items-center gap-3">
                  <h3 className="text-sm font-semibold tracking-tight">Run #{selected}</h3>
                  <StatusBadge status={status.includes("completed") ? "completed" : status.includes("in_progress") ? "in_progress" : "queued"} conclusion={status.includes("success") ? "success" : status.includes("failure") ? "failure" : null} />
                  <a href={`https://github.com/Nishgamerrz/Ai-rant/actions/runs/${selected}`} target="_blank" className="ml-auto text-xs px-2.5 py-1 rounded-full bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 text-zinc-400 hover:text-zinc-200 transition-colors">GitHub →</a>
                  <button onClick={() => delRun(selected)} disabled={deleting === selected} className="h-7 px-2.5 rounded-full bg-red-950/30 hover:bg-red-900/40 border border-red-900/50 text-xs font-medium text-red-300 hover:text-red-200 transition-colors disabled:opacity-50">
                    {deleting === selected ? "Deleting…" : "Delete"}
                  </button>
                </div>
                <div className="mt-3 flex gap-1 p-1 rounded-xl bg-zinc-950 border border-zinc-800 w-fit">
                  {[
                    { id: "overview", label: "Overview" },
                    { id: "execution", label: "Execution" },
                    { id: "intelligence", label: "Plan & Thinking" },
                    { id: "files", label: "Files" },
                  ].map((t) => (
                    <button key={t.id} onClick={() => setTab(t.id as any)} className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${tab === t.id ? "bg-white text-zinc-900 shadow-soft" : "text-zinc-500 hover:text-zinc-300"}`}>{t.label}</button>
                  ))}
                </div>
              </div>

              <div className="p-4">
                {tab === "overview" && (
                  <div className="space-y-3">
                    <div className="rounded-xl bg-zinc-950 border border-zinc-800 p-3.5">
                      <div className="text-xs font-semibold tracking-wide text-zinc-400 uppercase">Status</div>
                      <div className="text-sm font-medium text-zinc-200 mt-1">{status || "loading…"}</div>
                      <div className="text-xs text-zinc-600 mt-1">Live updates every 3.5s · artifacts appear as steps complete</div>
                    </div>
                    {artifacts.length > 0 && (
                      <div className="rounded-xl bg-zinc-950 border border-zinc-800 p-3.5">
                        <div className="text-xs font-semibold tracking-wide text-zinc-400 uppercase">Artifacts</div>
                        <div className="mt-2 space-y-1.5">
                          {artifacts.slice(0, 6).map((a) => (
                            <a key={a.id} href={`/api/github/artifact?id=${a.id}`} target="_blank" className="flex items-center gap-2 rounded-lg bg-zinc-900 border border-zinc-800 hover:bg-zinc-800 px-3 py-2 transition-colors">
                              <span className="text-xs font-medium text-zinc-200 truncate">{a.name}</span>
                              <span className="ml-auto text-[11px] text-zinc-600">{(a.size_in_bytes / 1024).toFixed(0)} KB</span>
                              <span className="text-[11px] px-2 py-0.5 rounded-full bg-white text-zinc-900 font-medium">Download</span>
                            </a>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
                {tab === "execution" && <LogViewer steps={steps} runStatus={status} logTail={liveLog} />}
                {tab === "intelligence" && (
                  <div className="space-y-3">
                    {liveLog && (
                      <div className="rounded-xl bg-zinc-900 border border-zinc-800 overflow-hidden">
                        <div className="h-8 px-3 flex items-center gap-2 border-b border-zinc-800 bg-zinc-900">
                          <span className="h-2 w-2 rounded-full bg-amber-500 animate-pulse" />
                          <span className="text-xs font-semibold tracking-wide text-zinc-300">Live — persistent plan · thinking & tools (direct API)</span>
                          <span className="ml-auto text-[11px] text-zinc-600">{(liveLog.length/1024).toFixed(1)} KB — no tunnel</span>
                        </div>
                        <pre className="p-3 text-xs font-mono leading-relaxed whitespace-pre-wrap break-words max-h-[320px] overflow-auto text-zinc-400">{liveLog.slice(-6000)}</pre>
                        <div className="px-3 py-2 border-t border-zinc-800 bg-zinc-950 text-[11px] text-zinc-500">This persistent plan stays alive until workflow dies, streaming every thought via direct GitHub API polling.</div>
                      </div>
                    )}
                    {intelligence.loading ? (
                      <div className="flex items-center gap-2 text-xs text-zinc-500 py-6 justify-center"><span className="h-3 w-3 border border-zinc-700 border-t-zinc-400 rounded-full animate-spin" /> Loading plan…</div>
                    ) : (
                      <>
                        {intelligence.narration && (
                          <div className="rounded-xl bg-zinc-950 border border-zinc-800 p-4">
                            <div className="text-xs font-semibold tracking-wide text-zinc-500 uppercase flex items-center gap-2"><span className="h-2 w-2 rounded-full bg-cyan-500" /> Narration</div>
                            <pre className="mt-2 text-sm leading-relaxed whitespace-pre-wrap break-words text-zinc-300 font-sans">{intelligence.narration.slice(0, 4000)}</pre>
                          </div>
                        )}
                        {intelligence.plan ? (
                          <div className="rounded-xl bg-zinc-950 border border-zinc-800 p-4">
                            <div className="text-xs font-semibold tracking-wide text-zinc-500 uppercase flex items-center gap-2"><span className="h-2 w-2 rounded-full bg-violet-500" /> World Plan</div>
                            <pre className="mt-2 text-xs font-mono leading-relaxed whitespace-pre-wrap break-words text-zinc-400 max-h-[420px] overflow-auto">{intelligence.plan.slice(0, 8000)}</pre>
                          </div>
                        ) : (
                          <div className="rounded-xl border border-dashed border-zinc-800 bg-zinc-900/30 p-6 text-center">
                            <div className="text-sm font-medium text-zinc-400">Plan not yet available</div>
                            <div className="text-xs text-zinc-600 mt-1 leading-relaxed">The AI is still thinking or the artifact hasn’t uploaded. Stay on this tab — it auto-retries. You can also check Execution for live step logs.</div>
                          </div>
                        )}
                        {!intelligence.narration && !intelligence.plan && !intelligence.loading && (
                          <div className="rounded-xl bg-amber-950/20 border border-amber-900/30 p-3 text-xs leading-relaxed text-amber-200">Intelligence artifacts are only available after the “Plan” and “Generate” steps upload. Polling continues in the background.</div>
                        )}
                      </>
                    )}
                    <SubagentTimeline runId={selected} kind="rbx" liveLog={liveLog || undefined} />
                  </div>
                )}
                {tab === "files" && (
                  <FileExplorer runId={selected} onOpenFile={(path, content) => setPreview({ path, content })} />
                )}
              </div>
            </div>
          ) : (
            <div className="rounded-2xl border border-dashed border-zinc-800 bg-zinc-900/20 p-8 text-center">
              <div className="h-10 w-10 rounded-xl bg-zinc-800 grid place-items-center mx-auto">
                <svg width="18" height="18" viewBox="0 0 18 18" fill="none"><path d="M9 4V14M4 9H14" stroke="#71717a" strokeWidth="1.4" strokeLinecap="round"/></svg>
              </div>
              <div className="text-sm font-medium text-zinc-300 mt-3">Select a run to inspect</div>
              <div className="text-xs text-zinc-600 mt-1">Execution logs, AI thinking, world plan, and downloadable files appear here — no need to open GitHub.</div>
            </div>
          )}
        </div>
      </div>

      {preview && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/60 backdrop-blur-md" onClick={() => setPreview(null)} />
          <div className="relative w-full max-w-4xl max-h-[88vh] rounded-2xl bg-zinc-900 border border-zinc-800 shadow-large flex flex-col animate-slideIn">
            <div className="shrink-0 h-11 px-4 flex items-center gap-3 border-b border-zinc-800">
              <span className="text-xs font-semibold tracking-wide text-zinc-300 truncate">{preview.path}</span>
              <button onClick={() => setPreview(null)} className="ml-auto h-7 w-7 grid place-items-center rounded-full bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 text-zinc-400">
                <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M3 3L9 9M9 3L3 9" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/></svg>
              </button>
            </div>
            <pre className="flex-1 overflow-auto p-4 text-xs font-mono leading-relaxed whitespace-pre-wrap break-words text-zinc-300">{preview.content.slice(0, 80000)}</pre>
          </div>
        </div>
      )}
    </div>
  );
}
