"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";

type Run = {
  id: number;
  display_title: string;
  status: string;
  conclusion: string | null;
  created_at: string;
  html_url: string;
  name?: string;
};

function timeAgo(iso: string) {
  const d = (Date.now() - new Date(iso).getTime()) / 1000;
  if (d < 60) return `${Math.floor(d)}s`;
  if (d < 3600) return `${Math.floor(d / 60)}m`;
  if (d < 86400) return `${Math.floor(d / 3600)}h`;
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function StatusDot({ status, conclusion }: { status: string; conclusion: string | null }) {
  if (status !== "completed") return <span className="h-2 w-2 rounded-full bg-amber-500 animate-pulse shadow-[0_0_6px_rgba(245,158,11,0.5)]" />;
  if (conclusion === "success") return <span className="h-2 w-2 rounded-full bg-emerald-500 shadow-[0_0_6px_rgba(16,185,129,0.5)]" />;
  if (conclusion === "failure") return <span className="h-2 w-2 rounded-full bg-red-500 shadow-[0_0_6px_rgba(239,68,68,0.5)]" />;
  if (conclusion === "cancelled") return <span className="h-2 w-2 rounded-full bg-zinc-500" />;
  return <span className="h-2 w-2 rounded-full bg-zinc-600" />;
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
  const pathname = usePathname();
  const isAgent = pathname === "/" || pathname?.startsWith("/agent");
  const isRbx = pathname === "/rbxshort";

  const [agentRuns, setAgentRuns] = useState<Run[]>([]);
  const [shortRuns, setShortRuns] = useState<Run[]>([]);
  const [err, setErr] = useState("");
  const [deleting, setDeleting] = useState<number | null>(null);

  async function load() {
    try {
      setErr("");
      const [a, b] = await Promise.all([
        fetch("/api/github/runs?kind=agent&per_page=12", { cache: "no-store" }).then((r) => r.json()),
        fetch("/api/github/runs?kind=rbx&per_page=12", { cache: "no-store" }).then((r) => r.json()),
      ]);
      if (a.error) throw new Error(a.error);
      if (b.error) throw new Error(b.error);
      setAgentRuns(a.runs || []);
      setShortRuns(b.runs || []);
    } catch (e: any) {
      setErr(String(e.message || e).slice(0, 200));
    }
  }

  useEffect(() => {
    load();
    const id = setInterval(load, 15000);
    return () => clearInterval(id);
  }, []);

  async function delRun(id: number, e: React.MouseEvent) {
    e.stopPropagation();
    if (!confirm(`Delete workflow run #${id}? This cannot be undone.`)) return;
    setDeleting(id);
    try {
      const res = await fetch(`/api/github/delete?run=${id}`, { method: "DELETE" });
      const j = await res.json();
      if (!res.ok) throw new Error(j.error || "delete failed");
      // Optimistically remove
      setAgentRuns((prev) => prev.filter((r) => r.id !== id));
      setShortRuns((prev) => prev.filter((r) => r.id !== id));
      if (selectedRun === id) onSelectRun(null);
    } catch (e: any) {
      alert("Delete failed: " + String(e.message || e));
    } finally {
      setDeleting(null);
    }
  }

  const Drawer = (
    <div className="flex h-full flex-col bg-[#0f0f10] border-r border-zinc-800/80">
      {/* Brand */}
      <div className="p-5 border-b border-zinc-800/80">
        <div className="flex items-center gap-3">
          <div className="h-9 w-9 rounded-xl bg-white text-zinc-900 grid place-items-center font-bold text-[13px] tracking-tight shadow-soft">
            NA
          </div>
          <div className="min-w-0">
            <div className="font-semibold text-[14px] tracking-tight leading-none">NishAgent</div>
            <div className="text-[11px] text-zinc-500 font-medium tracking-wide">AI WORKSPACE</div>
          </div>
          <button onClick={onClose} className="ml-auto md:hidden h-8 w-8 grid place-items-center rounded-lg bg-zinc-900 border border-zinc-800 text-zinc-400">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M4 4L12 12M12 4L4 12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg>
          </button>
        </div>
        <button
          onClick={onNewChat}
          className="mt-4 w-full h-10 rounded-xl bg-white hover:bg-zinc-100 text-zinc-900 font-medium text-sm flex items-center justify-center gap-2 transition-colors shadow-soft"
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M7 2.5V11.5M2.5 7H11.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/></svg>
          New workflow
        </button>
      </div>

      {/* Nav */}
      <div className="p-3 flex gap-1.5">
        <Link
          href="/"
          className={`flex-1 h-8 rounded-lg flex items-center justify-center gap-1.5 text-xs font-medium transition-colors ${
            isAgent ? "bg-zinc-900 text-white border border-zinc-800" : "text-zinc-500 hover:text-zinc-300 hover:bg-zinc-900/50"
          }`}
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M4 3.5H10M4 7H10M4 10.5H7" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/><rect x="2.5" y="1.5" width="9" height="11" rx="1.5" stroke="currentColor" strokeWidth="1.2"/></svg>
          Agent
        </Link>
        <Link
          href="/rbxshort"
          className={`flex-1 h-8 rounded-lg flex items-center justify-center gap-1.5 text-xs font-medium transition-colors ${
            isRbx ? "bg-zinc-900 text-white border border-zinc-800" : "text-zinc-500 hover:text-zinc-300 hover:bg-zinc-900/50"
          }`}
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M2.5 4.5L7 2L11.5 4.5V9.5L7 12L2.5 9.5V4.5Z" stroke="currentColor" strokeWidth="1.2"/><path d="M2.5 4.5L7 7L11.5 4.5" stroke="currentColor" strokeWidth="1.2"/></svg>
          Short
        </Link>
      </div>

      {/* Runs */}
      <div className="flex-1 overflow-y-auto px-3 pt-1 pb-4 space-y-6 scrollbar-thin">
        <section>
          <div className="flex items-center justify-between px-1 py-2">
            <h3 className="text-[11px] font-semibold tracking-widest text-zinc-500 uppercase">Agent</h3>
            <button onClick={load} className="h-6 w-6 grid place-items-center rounded-md hover:bg-zinc-900 text-zinc-600 hover:text-zinc-400 transition-colors">
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M1.5 6A4.5 4.5 0 0 1 8.8 2.3M10.5 6A4.5 4.5 0 0 1 3.2 9.7" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/><path d="M8.8 1.5V2.8H7.5M3.2 10.5V9.2H4.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/></svg>
            </button>
          </div>
          {err && <div className="mx-1 mb-2 rounded-lg bg-amber-950/30 border border-amber-900/50 text-amber-300 text-xs p-2.5 leading-relaxed">{err}</div>}
          <div className="space-y-1">
            {agentRuns.length === 0 && !err && <div className="text-xs text-zinc-600 px-2 py-3 text-center leading-relaxed">No runs yet.<br/><span className="text-zinc-500">Start a workflow to begin.</span></div>}
            {agentRuns.map((r) => (
              <div
                key={r.id}
                onClick={() => onSelectRun(r.id)}
                className={`group relative w-full text-left rounded-xl border px-3 py-2.5 cursor-pointer transition-all ${
                  selectedRun === r.id ? "bg-zinc-900 border-zinc-700 shadow-soft" : "bg-zinc-900/40 border-zinc-800/60 hover:bg-zinc-900 hover:border-zinc-800"
                }`}
              >
                <div className="flex items-center gap-2 min-w-0">
                  <StatusDot status={r.status} conclusion={r.conclusion} />
                  <span className="text-[11px] font-medium text-zinc-500 tracking-wide truncate">{r.status === "completed" ? (r.conclusion?.toUpperCase() || "DONE") : r.status.toUpperCase()}</span>
                  <span className="text-[11px] text-zinc-600">· {timeAgo(r.created_at)}</span>
                  <button
                    onClick={(e) => delRun(r.id, e)}
                    disabled={deleting === r.id}
                    className="ml-auto opacity-0 group-hover:opacity-100 h-6 w-6 grid place-items-center rounded-md hover:bg-zinc-800 text-zinc-500 hover:text-red-400 transition-all disabled:opacity-50"
                    title="Delete workflow run"
                  >
                    {deleting === r.id ? (
                      <span className="h-3 w-3 border border-zinc-600 border-t-zinc-300 rounded-full animate-spin" />
                    ) : (
                      <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M3 3.5L3 9.5M9 3.5L9 9.5M1.5 3.5H10.5M4 3.5V2.5H8V3.5" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" strokeLinejoin="round"/></svg>
                    )}
                  </button>
                </div>
                <div className="text-[13px] font-medium text-zinc-200 truncate mt-1 pr-2 leading-tight">{r.display_title || `Run #${r.id}`}</div>
                <div className="text-[11px] text-zinc-600 truncate">#{r.id}</div>
              </div>
            ))}
          </div>
        </section>

        <section>
          <h3 className="text-[11px] font-semibold tracking-widest text-zinc-500 uppercase px-1 py-2">Shorts</h3>
          <div className="space-y-1">
            {shortRuns.length === 0 && <div className="text-xs text-zinc-600 px-2">No short runs yet.</div>}
            {shortRuns.map((r) => (
              <div
                key={r.id}
                onClick={() => {
                  // Select in main view if on agent, else navigate to rbxshort with selection via query? For now open in rbxshort context: select via onSelectRun if on rbxshort page, else link to rbxshort
                  if (isRbx) {
                    onSelectRun(r.id);
                  } else {
                    window.location.href = `/rbxshort?run=${r.id}`;
                  }
                }}
                className={`group relative w-full text-left rounded-xl border px-3 py-2.5 cursor-pointer transition-all ${
                  selectedRun === r.id && isRbx ? "bg-zinc-900 border-zinc-700 shadow-soft" : "bg-zinc-900/40 border-zinc-800/60 hover:bg-zinc-900 hover:border-zinc-800"
                }`}
              >
                <div className="flex items-center gap-2 min-w-0">
                  <StatusDot status={r.status} conclusion={r.conclusion} />
                  <span className="text-[11px] font-medium text-zinc-500 tracking-wide truncate">{r.status === "completed" ? (r.conclusion?.toUpperCase() || "DONE") : r.status.toUpperCase()}</span>
                  <span className="text-[11px] text-zinc-600">· {timeAgo(r.created_at)}</span>
                  <button
                    onClick={(e) => delRun(r.id, e)}
                    disabled={deleting === r.id}
                    className="ml-auto opacity-0 group-hover:opacity-100 h-6 w-6 grid place-items-center rounded-md hover:bg-zinc-800 text-zinc-500 hover:text-red-400 transition-all"
                    title="Delete"
                  >
                    {deleting === r.id ? <span className="h-3 w-3 border border-zinc-600 border-t-zinc-300 rounded-full animate-spin" /> : <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M3 3.5L3 9.5M9 3.5L9 9.5M1.5 3.5H10.5M4 3.5V2.5H8V3.5" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round"/></svg>}
                  </button>
                </div>
                <div className="text-[13px] font-medium text-zinc-200 truncate mt-1 pr-2 leading-tight">{r.display_title || `Short #${r.id}`}</div>
              </div>
            ))}
          </div>
        </section>
      </div>

      <div className="p-3 border-t border-zinc-800/80">
        <div className="flex items-center gap-2 text-[11px] text-zinc-600">
          <span className="h-2 w-2 rounded-full bg-emerald-500/80 shadow-[0_0_4px_rgba(16,185,129,0.4)]" />
          System operational
          <a href="https://github.com/Nishgamerrz/Ai-rant" target="_blank" className="ml-auto hover:text-zinc-400 transition-colors">GitHub</a>
        </div>
      </div>
    </div>
  );

  return (
    <>
      <div className="hidden md:block w-[300px] shrink-0 h-screen sticky top-0 overflow-hidden">{Drawer}</div>
      {open && (
        <div className="md:hidden fixed inset-0 z-40">
          <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
          <div className="absolute inset-y-0 left-0 w-[85%] max-w-[320px] shadow-large animate-slideIn">{Drawer}</div>
        </div>
      )}
    </>
  );
}
