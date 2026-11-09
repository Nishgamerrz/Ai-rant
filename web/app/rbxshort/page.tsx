"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { ModelSelector } from "@/components/ModelSelector";
import { LogViewer } from "@/components/LogViewer";

export default function RbxShortPage() {
  const [storyTopic, setStoryTopic] = useState("In a world where the last person to fall asleep each night gets one wish, two brothers keep each other awake on purpose in a cramped bedroom");
  const [usernames, setUsernames] = useState("normal,noob");
  const [duration, setDuration] = useState("120");
  const [mapDetail, setMapDetail] = useState("dense");
  const [model, setModel] = useState("hard");
  const [voice, setVoice] = useState("male");
  const [worldTheme, setWorldTheme] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [runs, setRuns] = useState<any[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [steps, setSteps] = useState<any[]>([]);
  const [status, setStatus] = useState("idle");

  async function loadRuns() {
    try {
      const j = await fetch("/api/github/runs?kind=rbx&per_page=12").then((r) => r.json());
      if (j.runs) setRuns(j.runs);
    } catch {}
  }
  useEffect(() => {
    loadRuns();
    const id = setInterval(loadRuns, 8000);
    return () => clearInterval(id);
  }, []);

  async function poll() {
    if (!selected) return;
    try {
      const j = await fetch(`/api/github/logs?run=${selected}`).then((r) => r.json());
      if (j.steps) setSteps(j.steps);
      if (j.run) setStatus(j.run.status + (j.run.conclusion ? " · " + j.run.conclusion : ""));
    } catch {}
  }
  useEffect(() => {
    if (!selected) return;
    poll();
    const id = setInterval(poll, 4000);
    return () => clearInterval(id);
  }, [selected]);

  async function dispatch() {
    setBusy(true);
    setMsg("");
    try {
      const res = await fetch("/api/github/dispatch", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ kind: "rbx", story_topic: storyTopic, character_usernames: usernames, duration_seconds: duration, map_detail: mapDetail, model_quality: model, voice_style: voice, world_theme: worldTheme }) });
      const j = await res.json();
      if (!res.ok) throw new Error(j.error);
      setMsg("✓ Dispatched! Watch the workflow below — logs are coloured like the runner, model load vs prompt-reading shown in the plan steps. Refresh runs to see it.");
      setTimeout(loadRuns, 2500);
    } catch (e: any) {
      setMsg("✗ " + String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen bg-ink">
      <div className="sticky top-0 z-10 bg-ink/80 backdrop-blur border-b border-line">
        <div className="max-w-6xl mx-auto px-4 py-3 flex items-center gap-3">
          <Link href="/" className="rounded-xl border border-zinc-800 px-3 py-2 text-sm hover:bg-zinc-900">← Agent</Link>
          <div>
            <div className="font-semibold">RBX Short — nishagent.vercel.app/rbxshort</div>
            <div className="text-xs text-zinc-500">Same inputs & models as the GitHub workflow · live logs in colours · fully secure via GITHUB_TOKEN</div>
          </div>
          <a href="https://github.com/Nishgamerrz/Ai-rant/actions/workflows/main.yml" target="_blank" className="ml-auto hidden sm:inline text-xs underline text-zinc-400">Workflow on GitHub →</a>
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-4 py-6 grid grid-cols-1 lg:grid-cols-[1.1fr_0.9fr] gap-6">
        {/* Form */}
        <div className="rounded-2xl bg-card border border-line p-5 space-y-4">
          <h2 className="text-lg font-semibold">Generate Roblox-style short (MP4)</h2>
          <div className="rounded-xl bg-zinc-900 border border-zinc-800 p-3 text-xs text-zinc-400">All fields map 1:1 to the workflow inputs. We call <code className="bg-zinc-800 px-1 rounded">/api/github/dispatch</code> which uses the server-only <code className="bg-zinc-800 px-1 rounded">GITHUB_TOKEN</code> (set in Vercel → Settings → Environment Variables) to dispatch <code className="bg-zinc-800 px-1 rounded">main.yml</code>. You can pick any model — Fast / Medium / Hard / Smart 11B / Animation Best — as you asked.</div>

          <div>
            <label className="text-xs uppercase tracking-wide text-zinc-400">Story topic</label>
            <textarea value={storyTopic} onChange={(e) => setStoryTopic(e.target.value)} rows={3} className="mt-1 w-full rounded-xl bg-zinc-950 border border-zinc-800 p-3 text-sm" />
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <label className="text-sm">Usernames <input value={usernames} onChange={(e) => setUsernames(e.target.value)} placeholder="normal,noob" className="mt-1 w-full rounded-xl bg-zinc-950 border border-zinc-800 px-3 py-2 text-sm" /></label>
            <label className="text-sm">Duration <select value={duration} onChange={(e) => setDuration(e.target.value)} className="mt-1 w-full rounded-xl bg-zinc-950 border border-zinc-800 px-3 py-2 text-sm"><option value="30">30</option><option value="45">45</option><option value="60">60</option><option value="90">90</option><option value="120">120</option><option value="150">150</option><option value="180">180</option></select></label>
            <label className="text-sm">Map detail <select value={mapDetail} onChange={(e) => setMapDetail(e.target.value)} className="mt-1 w-full rounded-xl bg-zinc-950 border border-zinc-800 px-3 py-2 text-sm"><option value="standard">standard</option><option value="dense">dense</option><option value="ultra">ultra</option></select></label>
            <label className="text-sm">Voice <select value={voice} onChange={(e) => setVoice(e.target.value)} className="mt-1 w-full rounded-xl bg-zinc-950 border border-zinc-800 px-3 py-2 text-sm"><option value="male">male</option><option value="female">female</option><option value="thin_male">thin_male</option></select></label>
          </div>
          <label className="text-sm">World theme (optional) <input value={worldTheme} onChange={(e) => setWorldTheme(e.target.value)} placeholder="AUTO FROM STORY" className="mt-1 w-full rounded-xl bg-zinc-950 border border-zinc-800 px-3 py-2 text-sm" /></label>
          <ModelSelector value={model} onChange={setModel} />
          <button onClick={dispatch} disabled={busy} className="w-full rounded-xl bg-violet-600 hover:bg-violet-500 px-5 py-3 font-semibold disabled:opacity-50">{busy ? "Dispatching…" : "Run workflow →"}</button>
          {msg && <div className={`rounded-xl border p-3 text-sm ${msg.startsWith("✓") ? "border-emerald-900 bg-emerald-950/30 text-emerald-200" : "border-red-900 bg-red-950/30 text-red-200"}`}>{msg}</div>}
          <div className="text-xs text-zinc-600">Tip: use <b className="text-zinc-400">Hard</b> for the agent workflow when you want the best reasoning for code, as you requested. Shorts can use Medium for speed.</div>
        </div>

        {/* Runs + logs */}
        <div className="space-y-4">
          <div className="rounded-2xl bg-card border border-line p-4">
            <div className="flex items-center gap-2">
              <h3 className="font-semibold">Recent short runs</h3>
              <button onClick={loadRuns} className="ml-auto text-xs rounded-lg border border-zinc-700 px-2 py-1">Reload</button>
            </div>
            <div className="mt-3 space-y-2 max-h-[360px] overflow-auto">
              {runs.length === 0 && <div className="text-xs text-zinc-600">No runs yet — dispatch one.</div>}
              {runs.map((r) => (
                <button key={r.id} onClick={() => setSelected(r.id)} className={`w-full text-left rounded-xl border px-3 py-2 ${selected === r.id ? "bg-zinc-800 border-zinc-700" : "bg-zinc-900 border-zinc-800 hover:bg-zinc-800"}`}>
                  <div className="text-xs text-zinc-400 flex items-center gap-2">
                    <span className={`h-2 w-2 rounded-full ${r.status === "completed" ? (r.conclusion === "success" ? "bg-emerald-500" : "bg-zinc-500") : "bg-amber-400 animate-pulse"}`} />
                    {r.conclusion || r.status} · {new Date(r.created_at).toLocaleString()}
                  </div>
                  <div className="text-sm truncate">{r.display_title}</div>
                </button>
              ))}
            </div>
            {selected && (
              <a href={`https://github.com/Nishgamerrz/Ai-rant/actions/runs/${selected}`} target="_blank" className="mt-3 inline-block text-xs underline text-zinc-400">Open run #{selected} on GitHub →</a>
            )}
          </div>

          <LogViewer steps={steps} runStatus={status} />
          <div className="rounded-xl bg-zinc-900 border border-zinc-800 p-3 text-xs text-zinc-500">Logs show model load vs prompt-reading honestly (via <code className="bg-zinc-800 px-1 rounded">/api/ps</code>), coloured like the runner, with plan next/previous loads. Artefacts (MP4 + stills) appear on the run page after it completes.</div>
        </div>
      </div>
    </div>
  );
}
