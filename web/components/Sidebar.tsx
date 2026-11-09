"use client";
import Link from "next/link";
import { useEffect, useState } from "react";

type Run = { id: number; display_title: string; status: string; conclusion: string | null; created_at: string; html_url: string };

function timeAgo(iso: string) {
  const d = (Date.now() - new Date(iso).getTime()) / 1000;
  if (d < 60) return `${Math.floor(d)}s ago`;
  if (d < 3600) return `${Math.floor(d / 60)}m ago`;
  if (d < 86400) return `${Math.floor(d / 3600)}h ago`;
  return new Date(iso).toLocaleDateString();
}

export function Sidebar({
  open,
  onClose,
  onNewChat,
  selectedRun,
  onSelectRun,
}: {
  open: boolean;
  onClose: () => void;
  onNewChat: () => void;
  selectedRun: number | null;
  onSelectRun: (id: number | null) => void;
}) {
  const [agentRuns, setAgentRuns] = useState<Run[]>([]);
  const [shortRuns, setShortRuns] = useState<Run[]>([]);
  const [err, setErr] = useState<string>("");

  async function load() {
    try {
      setErr("");
      const [a, b] = await Promise.all([
        fetch("/api/github/runs?kind=agent&per_page=12").then((r) => r.json()),
        fetch("/api/github/runs?kind=rbx&per_page=8").then((r) => r.json()),
      ]);
      if (a.error) throw new Error(a.error);
      if (b.error) throw new Error(b.error);
      setAgentRuns(a.runs || []);
      setShortRuns(b.runs || []);
    } catch (e: any) {
      setErr(String(e.message || e).slice(0, 220));
    }
  }
  useEffect(() => {
    load();
    const id = setInterval(load, 15000);
    return () => clearInterval(id);
  }, []);

  const Drawer = (
    <div className="flex h-full flex-col bg-panel border-r border-line">
      <div className="p-4 border-b border-line">
        <div className="flex items-center gap-3">
          <div className="h-9 w-9 rounded-xl bg-violet-600 grid place-items-center font-bold">N</div>
          <div>
            <div className="font-semibold leading-none">NishAgent</div>
            <div className="text-xs text-zinc-500">nishagent.vercel.app</div>
          </div>
          <button onClick={onClose} className="ml-auto md:hidden rounded-lg border border-zinc-800 px-2 py-1 text-xs">Close</button>
        </div>
        <button onClick={onNewChat} className="mt-4 w-full rounded-xl bg-white text-zinc-900 font-semibold py-2.5 hover:bg-zinc-100">＋ New chat</button>
        <div className="mt-3 text-xs text-zinc-500">Creates a workflow from the sidebar — pick Agent or RBX Short + model, then we dispatch via GitHub and show live logs + AI colours.</div>
      </div>

      <nav className="p-3 flex items-center gap-2 text-sm">
        <Link href="/" className="flex-1 rounded-lg bg-zinc-800 px-3 py-2 text-white">Agent chat</Link>
        <Link href="/rbxshort" className="flex-1 rounded-lg border border-zinc-800 px-3 py-2 text-zinc-300 hover:bg-zinc-800">RBX Short</Link>
      </nav>

      <div className="flex-1 overflow-y-auto px-3 pb-3 space-y-4">
        <section>
          <div className="flex items-center justify-between px-1 py-1">
            <h3 className="text-xs uppercase tracking-widest text-zinc-500">Agent chats — from workflows</h3>
            <button onClick={load} className="text-xs text-zinc-400 hover:text-white">Reload</button>
          </div>
          {err && <div className="rounded-lg bg-amber-950/40 border border-amber-800 text-amber-200 text-xs p-2">{err}</div>}
          <div className="space-y-1.5 mt-1">
            {agentRuns.length === 0 && <div className="text-xs text-zinc-600 px-1">No agent runs yet — start one with New chat.</div>}
            {agentRuns.map((r) => (
              <button
                key={r.id}
                onClick={() => onSelectRun(r.id)}
                className={`w-full text-left rounded-xl border px-3 py-2 ${selectedRun === r.id ? "bg-zinc-800 border-zinc-700" : "bg-zinc-900 border-zinc-800 hover:bg-zinc-800"}`}
              >
                <div className="text-xs text-zinc-400 flex items-center gap-2">
                  <span className={`h-2 w-2 rounded-full ${r.status === "completed" ? (r.conclusion === "success" ? "bg-emerald-500" : r.conclusion === "failure" ? "bg-red-500" : "bg-zinc-500") : "bg-amber-400 animate-pulse"}`} />
                  {r.status === "completed" ? r.conclusion : r.status} · {timeAgo(r.created_at)}
                </div>
                <div className="text-sm text-zinc-100 truncate">{r.display_title || `Run #${r.id}`}</div>
              </button>
            ))}
          </div>
        </section>

        <section>
          <h3 className="text-xs uppercase tracking-widest text-zinc-500 px-1">RBX Short runs</h3>
          <div className="space-y-1.5 mt-1">
            {shortRuns.map((r) => (
              <a key={r.id} href={r.html_url} target="_blank" className="block rounded-xl border border-zinc-800 bg-zinc-900 px-3 py-2 hover:bg-zinc-800">
                <div className="text-xs text-zinc-400 flex items-center gap-2">
                  <span className={`h-2 w-2 rounded-full ${r.status === "completed" ? (r.conclusion === "success" ? "bg-emerald-500" : "bg-zinc-500") : "bg-amber-400 animate-pulse"}`} />
                  {r.conclusion || r.status} · {timeAgo(r.created_at)}
                </div>
                <div className="text-sm text-zinc-100 truncate">{r.display_title}</div>
              </a>
            ))}
            {shortRuns.length === 0 && <div className="text-xs text-zinc-600">No RBX runs yet.</div>}
          </div>
        </section>

        <section className="rounded-xl bg-zinc-900 border border-zinc-800 p-3">
          <div className="text-xs font-semibold text-zinc-200">Secure — GitHub key stays on the server</div>
          <div className="text-xs text-zinc-500 mt-1">Vercel env var <code className="bg-zinc-800 px-1 rounded">GITHUB_TOKEN</code> is only read in <code className="bg-zinc-800 px-1 rounded">/api/*</code> routes. The browser never sees it. Live chat via a free Cloudflare tunnel (<code className="bg-zinc-800 px-1 rounded">*.trycloudflare.com</code>) when you enable it for an agent run — otherwise we poll the workflow artifacts.</div>
        </section>
      </div>

      <div className="p-3 border-t border-line text-xs text-zinc-600">
        <div>Built for brooo — dark grey, coloured AI logs, plan next/previous, load states.</div>
        <div className="mt-1 flex gap-2">
          <a href="https://github.com/Nishgamerrz/Ai-rant" target="_blank" className="underline">GitHub</a>
          <span>·</span>
          <a href="/rbxshort" className="underline">nishagent.vercel.app/rbxshort</a>
        </div>
      </div>
    </div>
  );

  return (
    <>
      {/* Desktop */}
      <div className="hidden md:block w-[320px] shrink-0 h-screen sticky top-0 overflow-hidden">{Drawer}</div>
      {/* Mobile overlay */}
      {open && (
        <div className="md:hidden fixed inset-0 z-40">
          <div className="absolute inset-0 bg-black/60" onClick={onClose} />
          <div className="absolute inset-y-0 left-0 w-[84%] max-w-[360px]">{Drawer}</div>
        </div>
      )}
    </>
  );
}
