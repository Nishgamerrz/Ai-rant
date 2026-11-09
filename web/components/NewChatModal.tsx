"use client";
import { useState } from "react";
import { ModelSelector } from "./ModelSelector";

export function NewChatModal({ open, onClose, onStart }: { open: boolean; onClose: () => void; onStart: (payload: any) => void }) {
  const [kind, setKind] = useState<"agent" | "rbx">("agent");
  const [model, setModel] = useState("hard");
  const [prompt, setPrompt] = useState("");
  const [storyTopic, setStoryTopic] = useState("In a world where the last person to fall asleep each night gets one wish, two brothers keep each other awake on purpose");
  const [usernames, setUsernames] = useState("normal,noob");
  const [duration, setDuration] = useState("120");
  const [mapDetail, setMapDetail] = useState("dense");
  const [voice, setVoice] = useState("male");
  const [worldTheme, setWorldTheme] = useState("");
  const [enableTunnel, setEnableTunnel] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  if (!open) return null;

  async function handleStart() {
    setBusy(true);
    setErr("");
    try {
      const before = Date.now();
      if (kind === "agent") {
        if (!prompt.trim()) throw new Error("Please enter a prompt.");
        const res = await fetch("/api/github/dispatch", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ kind: "agent", prompt: prompt.trim(), model_quality: model, enable_tunnel: enableTunnel ? "true" : "false" }),
        });
        const j = await res.json();
        if (!res.ok) throw new Error(j.error || "Dispatch failed");
        // Poll for new run
        let runId: number | null = null;
        for (let i = 0; i < 10; i++) {
          await new Promise((r) => setTimeout(r, 1500));
          try {
            const rj = await fetch("/api/github/runs?kind=agent&per_page=5", { cache: "no-store" }).then((r) => r.json());
            const newest = rj?.runs?.[0];
            if (newest && new Date(newest.created_at).getTime() > before - 5000) {
              runId = newest.id;
              break;
            }
          } catch {}
        }
        onStart({ kind: "agent", model, prompt, runId });
        onClose();
        if (runId) {
          // Small delay to let caller handle
          setTimeout(() => {}, 100);
        }
      } else {
        if (!storyTopic.trim()) throw new Error("Story topic is required.");
        const res = await fetch("/api/github/dispatch", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            kind: "rbx",
            story_topic: storyTopic.trim(),
            character_usernames: usernames.trim(),
            duration_seconds: duration,
            map_detail: mapDetail,
            model_quality: model,
            voice_style: voice,
            world_theme: worldTheme.trim(),
          }),
        });
        const j = await res.json();
        if (!res.ok) throw new Error(j.error || "Dispatch failed");
        let runId: number | null = null;
        for (let i = 0; i < 10; i++) {
          await new Promise((r) => setTimeout(r, 1500));
          try {
            const rj = await fetch("/api/github/runs?kind=rbx&per_page=5", { cache: "no-store" }).then((r) => r.json());
            const newest = rj?.runs?.[0];
            if (newest && new Date(newest.created_at).getTime() > before - 5000) {
              runId = newest.id;
              break;
            }
          } catch {}
        }
        onStart({ kind: "rbx", model, storyTopic, runId });
        onClose();
      }
    } catch (e: any) {
      setErr(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-md" onClick={() => !busy && onClose()} />
      <div className="relative w-full max-w-[560px] rounded-[20px] bg-zinc-900 border border-zinc-800 shadow-large max-h-[92vh] overflow-hidden flex flex-col animate-slideIn">
        {/* Header */}
        <div className="shrink-0 px-6 pt-6 pb-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-[17px] font-semibold tracking-tight">New workflow</h2>
              <p className="text-xs text-zinc-500 mt-1">Create an agent task or a Roblox short. Dispatched securely via GitHub.</p>
            </div>
            <button onClick={() => !busy && onClose()} className="h-8 w-8 grid place-items-center rounded-full bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 text-zinc-400 hover:text-zinc-200 transition-colors">
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M4 4L10 10M10 4L4 10" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/></svg>
            </button>
          </div>

          <div className="mt-5 p-1 rounded-xl bg-zinc-950 border border-zinc-800 flex gap-1">
            <button
              onClick={() => setKind("agent")}
              className={`flex-1 h-8 rounded-lg text-xs font-medium transition-all ${kind === "agent" ? "bg-white text-zinc-900 shadow-soft" : "text-zinc-500 hover:text-zinc-300"}`}
            >
              Agent · code & research
            </button>
            <button
              onClick={() => setKind("rbx")}
              className={`flex-1 h-8 rounded-lg text-xs font-medium transition-all ${kind === "rbx" ? "bg-white text-zinc-900 shadow-soft" : "text-zinc-500 hover:text-zinc-300"}`}
            >
              Short · video
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-auto px-6 pb-2 space-y-5">
          {kind === "agent" ? (
            <>
              <div>
                <label className="text-[11px] font-semibold tracking-widest text-zinc-500 uppercase">Prompt</label>
                <textarea
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  placeholder="Describe what the agent should do — research, build a page, generate files…"
                  rows={4}
                  className="mt-2 w-full rounded-xl bg-zinc-950 border border-zinc-800 focus:border-zinc-700 focus:bg-zinc-900 outline-none p-3.5 text-sm text-white placeholder:text-zinc-600 transition-colors resize-none"
                />
              </div>
              <ModelSelector value={model} onChange={setModel} />
              <label className="flex items-start gap-3 rounded-xl bg-zinc-950 border border-zinc-800 p-3.5 cursor-pointer hover:border-zinc-700 transition-colors">
                <input type="checkbox" checked={enableTunnel} onChange={(e) => setEnableTunnel(e.target.checked)} className="mt-0.5 rounded border-zinc-700 bg-zinc-900 text-white focus:ring-0" />
                <div className="min-w-0">
                  <div className="text-sm font-medium text-zinc-200">Enable live tunnel</div>
                  <div className="text-xs text-zinc-500 leading-relaxed">Recommended. Opens a secure Cloudflare tunnel so you can chat with the running agent in real time. Otherwise replies are polled from artifacts.</div>
                </div>
              </label>
            </>
          ) : (
            <>
              <div>
                <label className="text-[11px] font-semibold tracking-widest text-zinc-500 uppercase">Story topic</label>
                <textarea value={storyTopic} onChange={(e) => setStoryTopic(e.target.value)} rows={3} className="mt-2 w-full rounded-xl bg-zinc-950 border border-zinc-800 focus:border-zinc-700 outline-none p-3 text-sm text-white resize-none" />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-[11px] font-semibold tracking-widest text-zinc-500 uppercase">Usernames</label>
                  <input value={usernames} onChange={(e) => setUsernames(e.target.value)} placeholder="normal,noob" className="mt-2 w-full rounded-xl bg-zinc-950 border border-zinc-800 focus:border-zinc-700 outline-none px-3 py-2.5 text-sm" />
                </div>
                <div>
                  <label className="text-[11px] font-semibold tracking-widest text-zinc-500 uppercase">Duration</label>
                  <select value={duration} onChange={(e) => setDuration(e.target.value)} className="mt-2 w-full rounded-xl bg-zinc-950 border border-zinc-800 focus:border-zinc-700 outline-none px-3 py-2.5 text-sm">
                    <option value="30">30s</option><option value="45">45s</option><option value="60">60s</option><option value="90">90s</option><option value="120">120s</option><option value="150">150s</option><option value="180">180s</option>
                  </select>
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
                <label className="text-[11px] font-semibold tracking-widest text-zinc-500 uppercase">World theme <span className="normal-case tracking-normal text-zinc-600 font-normal">— optional</span></label>
                <input value={worldTheme} onChange={(e) => setWorldTheme(e.target.value)} placeholder="Auto from story" className="mt-2 w-full rounded-xl bg-zinc-950 border border-zinc-800 focus:border-zinc-700 outline-none px-3 py-2.5 text-sm" />
              </div>
              <ModelSelector value={model} onChange={setModel} />
            </>
          )}

          {err && <div className="rounded-xl border border-red-900/50 bg-red-950/20 text-red-300 p-3 text-sm leading-relaxed">{err}</div>}
        </div>

        <div className="shrink-0 p-4 border-t border-zinc-800 bg-zinc-900 flex items-center justify-end gap-2">
          <button onClick={() => !busy && onClose()} disabled={busy} className="h-9 px-4 rounded-xl border border-zinc-700 bg-zinc-800 hover:bg-zinc-700 text-sm font-medium text-zinc-300 hover:text-white disabled:opacity-50 transition-colors">Cancel</button>
          <button
            onClick={handleStart}
            disabled={busy}
            className="h-9 px-5 rounded-xl bg-white hover:bg-zinc-100 text-zinc-900 text-sm font-semibold disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2 shadow-soft"
          >
            {busy ? <><span className="h-4 w-4 border-2 border-zinc-300 border-t-zinc-900 rounded-full animate-spin" /> Dispatching…</> : <>Start workflow <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M4 3L8 6L4 9" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/></svg></>}
          </button>
        </div>
      </div>
    </div>
  );
}
