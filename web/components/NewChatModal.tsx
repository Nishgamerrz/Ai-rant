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
  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-4">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-2xl rounded-2xl bg-card border border-line shadow-2xl max-h-[92vh] overflow-y-auto">
        <div className="sticky top-0 bg-card/90 backdrop-blur border-b border-line p-4 flex items-center gap-3">
          <div className="text-lg font-semibold">New chat</div>
          <div className="ml-auto flex gap-2">
            <button onClick={() => setKind("agent")} className={`px-3 py-1.5 rounded-xl text-sm border ${kind === "agent" ? "bg-white text-zinc-900 border-white" : "bg-zinc-900 border-zinc-700 text-zinc-300"}`}>Agent — web / code / files</button>
            <button onClick={() => setKind("rbx")} className={`px-3 py-1.5 rounded-xl text-sm border ${kind === "rbx" ? "bg-white text-zinc-900 border-white" : "bg-zinc-900 border-zinc-700 text-zinc-300"}`}>RBX Short — video</button>
          </div>
        </div>

        <div className="p-5 space-y-5">
          {kind === "agent" ? (
            <>
              <div className="rounded-xl bg-zinc-900 border border-zinc-800 p-3 text-xs text-zinc-400">Agent workflow can <b className="text-zinc-200">search the web, create files, create images, run commands in a sandbox, and delegate to the Gemini sub-agent</b> for code. It uses the same <b className="text-zinc-200">GITHUB_TOKEN</b> + free <b className="text-zinc-200">Cloudflare tunnel</b> so Vercel can talk live to the running runner and fetch <b className="text-zinc-200">ai tools used + chat history</b> for the sidebar and file explorer.</div>
              <div>
                <label className="text-xs uppercase tracking-wide text-zinc-400">Prompt for the agent</label>
                <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="e.g. Research the latest Next.js 15 changes, create a small demo page at demo/page.tsx and write a summary to SUMMARY.md" rows={4} className="mt-1 w-full rounded-xl bg-zinc-950 border border-zinc-800 p-3 text-sm text-white placeholder:text-zinc-600" />
              </div>
              <ModelSelector value={model} onChange={setModel} />
              <label className="flex items-center gap-2 text-sm text-zinc-300">
                <input type="checkbox" checked={enableTunnel} onChange={(e) => setEnableTunnel(e.target.checked)} className="rounded" />
                Enable free Cloudflare tunnel for live chat (recommended) — otherwise batch mode + artifact polling.
              </label>
            </>
          ) : (
            <>
              <div className="rounded-xl bg-zinc-900 border border-zinc-800 p-3 text-xs text-zinc-400">Generates a furnished Roblox-style short (MP4) — same inputs as the GitHub workflow. You’ll get live logs with colours, model load vs prompt-reading markers, and <b className="text-zinc-200">nishagent.vercel.app/rbxshort</b>.</div>
              <div>
                <label className="text-xs uppercase tracking-wide text-zinc-400">Story topic</label>
                <textarea value={storyTopic} onChange={(e) => setStoryTopic(e.target.value)} rows={3} className="mt-1 w-full rounded-xl bg-zinc-950 border border-zinc-800 p-3 text-sm text-white" />
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <label className="text-sm">Usernames <input value={usernames} onChange={(e) => setUsernames(e.target.value)} placeholder="normal,noob" className="mt-1 w-full rounded-xl bg-zinc-950 border border-zinc-800 px-3 py-2 text-sm" /></label>
                <label className="text-sm">Duration <select value={duration} onChange={(e) => setDuration(e.target.value)} className="mt-1 w-full rounded-xl bg-zinc-950 border border-zinc-800 px-3 py-2 text-sm"><option value="30">30</option><option value="45">45</option><option value="60">60</option><option value="90">90</option><option value="120">120</option><option value="150">150</option><option value="180">180</option></select></label>
                <label className="text-sm">Map detail <select value={mapDetail} onChange={(e) => setMapDetail(e.target.value)} className="mt-1 w-full rounded-xl bg-zinc-950 border border-zinc-800 px-3 py-2 text-sm"><option value="standard">standard</option><option value="dense">dense</option><option value="ultra">ultra</option></select></label>
                <label className="text-sm">Voice <select value={voice} onChange={(e) => setVoice(e.target.value)} className="mt-1 w-full rounded-xl bg-zinc-950 border border-zinc-800 px-3 py-2 text-sm"><option value="male">male</option><option value="female">female</option><option value="thin_male">thin_male</option></select></label>
              </div>
              <label className="text-sm">World theme (optional) <input value={worldTheme} onChange={(e) => setWorldTheme(e.target.value)} placeholder="AUTO FROM STORY" className="mt-1 w-full rounded-xl bg-zinc-950 border border-zinc-800 px-3 py-2 text-sm" /></label>
              <ModelSelector value={model} onChange={setModel} />
            </>
          )}

          {err && <div className="rounded-xl border border-red-900 bg-red-950/40 text-red-200 p-3 text-sm">{err}</div>}

          <div className="flex gap-3 justify-end">
            <button onClick={onClose} className="rounded-xl border border-zinc-700 px-4 py-2 text-sm">Cancel</button>
            <button
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                setErr("");
                try {
                  if (kind === "agent") {
                    if (!prompt.trim()) throw new Error("prompt required");
                    const res = await fetch("/api/github/dispatch", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ kind: "agent", prompt, model_quality: model, enable_tunnel: enableTunnel }) });
                    const j = await res.json();
                    if (!res.ok) throw new Error(j.error || "dispatch failed");
                    onStart({ kind: "agent", model, prompt, ...j });
                  } else {
                    if (!storyTopic.trim()) throw new Error("story_topic required");
                    const res = await fetch("/api/github/dispatch", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ kind: "rbx", story_topic: storyTopic, character_usernames: usernames, duration_seconds: duration, map_detail: mapDetail, model_quality: model, voice_style: voice, world_theme: worldTheme }) });
                    const j = await res.json();
                    if (!res.ok) throw new Error(j.error || "dispatch failed");
                    onStart({ kind: "rbx", model, storyTopic, ...j });
                  }
                } catch (e: any) {
                  setErr(String(e.message || e));
                } finally {
                  setBusy(false);
                }
              }}
              className="rounded-xl bg-violet-600 hover:bg-violet-500 px-5 py-2 text-sm font-semibold text-white disabled:opacity-50"
            >
              {busy ? "Dispatching…" : `Start ${kind === "agent" ? "agent" : "RBX short"} workflow →`}
            </button>
          </div>
          <div className="text-xs text-zinc-600">Requires <code className="bg-zinc-800 px-1 rounded">GITHUB_TOKEN</code> in Vercel env (GitHub PAT with Actions: read/write). Hard model preset is recommended for the agent as you asked.</div>
        </div>
      </div>
    </div>
  );
}
