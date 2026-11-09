"use client";
import { useEffect, useState } from "react";

type FileNode = { name: string; path: string; type: "file" | "dir"; size?: number };

export function FileExplorer({ runId, onOpenFile }: { runId: number | null; onOpenFile: (path: string, content: string) => void }) {
  const [artifacts, setArtifacts] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  async function load() {
    if (!runId) return;
    setLoading(true);
    setErr("");
    try {
      const j = await fetch(`/api/github/logs?run=${runId}`, { cache: "no-store" }).then((r) => r.json());
      if (j.error) throw new Error(j.error);
      setArtifacts(j.artifacts || []);
    } catch (e: any) {
      setErr(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setArtifacts([]);
    if (runId) load();
  }, [runId]);

  if (!runId) {
    return (
      <div className="rounded-2xl border border-dashed border-zinc-800 bg-zinc-900/30 p-6 text-center">
        <div className="h-10 w-10 rounded-xl bg-zinc-800 grid place-items-center mx-auto">
          <svg width="18" height="18" viewBox="0 0 18 18" fill="none"><path d="M4 3.5H10L14 7.5V14.5H4V3.5Z" stroke="#71717a" strokeWidth="1.3" strokeLinejoin="round"/><path d="M10 3.5V7.5H14" stroke="#71717a" strokeWidth="1.3" strokeLinejoin="round"/></svg>
        </div>
        <div className="text-sm font-medium text-zinc-300 mt-3">No run selected</div>
        <div className="text-xs text-zinc-600 mt-1 leading-relaxed">Select a workflow from the sidebar to inspect<br/>generated files and artifacts.</div>
      </div>
    );
  }

  return (
    <div className="rounded-2xl bg-zinc-900 border border-zinc-800 overflow-hidden shadow-soft">
      <div className="h-10 px-3.5 flex items-center gap-2 border-b border-zinc-800 bg-zinc-900">
        <div className="h-6 w-6 rounded-lg bg-zinc-800 grid place-items-center">
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M2.5 2H6L9.5 5V10H2.5V2Z" stroke="#a1a1aa" strokeWidth="1.2" strokeLinejoin="round"/><path d="M6 2V5H9.5" stroke="#27272a" strokeWidth="1.2"/></svg>
        </div>
        <span className="text-xs font-semibold tracking-wide text-zinc-200">Artifacts</span>
        <span className="text-[11px] text-zinc-600">{artifacts.length} files</span>
        <button onClick={load} className="ml-auto h-7 px-2.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 text-xs font-medium text-zinc-400 hover:text-zinc-200 transition-colors">Reload</button>
      </div>

      <div className="p-2">
        {loading && (
          <div className="flex items-center gap-2 px-3 py-3 text-xs text-zinc-500">
            <span className="h-3 w-3 border border-zinc-700 border-t-zinc-400 rounded-full animate-spin" />
            Loading artifacts...
          </div>
        )}
        {err && <div className="mx-2 rounded-lg bg-amber-950/30 border border-amber-900/50 text-amber-300 text-xs p-2.5">{err}</div>}
        {!loading && artifacts.length === 0 && !err && <div className="px-3 py-6 text-center text-xs text-zinc-600">No artifacts yet — the run is still initializing. They appear as <code className="bg-zinc-800 px-1 py-0.5 rounded text-zinc-400">dist/</code> once the job uploads.</div>}
        <div className="space-y-1">
          {artifacts.map((a) => (
            <div key={a.id} className="group flex items-center gap-3 rounded-xl border border-zinc-800 bg-zinc-950/40 hover:bg-zinc-800/60 hover:border-zinc-700 px-3 py-2.5 transition-colors">
              <div className="h-8 w-8 rounded-lg bg-violet-600/15 border border-violet-800/30 grid place-items-center shrink-0">
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M4 3H10M4 7H10M4 11H7" stroke="#a78bfa" strokeWidth="1.3" strokeLinecap="round"/></svg>
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-xs font-medium text-zinc-200 truncate">{a.name}</div>
                <div className="text-[11px] text-zinc-600">{a.expired ? "expired" : `${(a.size_in_bytes / 1024).toFixed(1)} KB · zip`}</div>
              </div>
              <div className="flex items-center gap-1 shrink-0">
                <button
                  onClick={async () => {
                    window.open(`/api/github/artifact?id=${a.id}`, "_blank");
                  }}
                  className="h-7 px-2.5 rounded-lg bg-white text-zinc-900 text-xs font-medium hover:bg-zinc-100 transition-colors"
                >
                  Download
                </button>
                <button
                  onClick={async () => {
                    try {
                      // Try to preview first file as text
                      const res = await fetch(`/api/github/artifact?id=${a.id}&json=agent_chat.json`);
                      const txt = await res.text();
                      onOpenFile(`${a.name}/agent_chat.json`, txt.slice(0, 30000));
                    } catch {}
                    window.open(`/api/github/artifact?id=${a.id}`, "_blank");
                  }}
                  className="h-7 w-7 grid place-items-center rounded-lg bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 text-zinc-400 hover:text-zinc-200 transition-colors"
                  title="Preview"
                >
                  <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M1.5 6C1.5 6 3.5 2.5 6 2.5C8.5 2.5 10.5 6 10.5 6C10.5 6 8.5 9.5 6 9.5C3.5 9.5 1.5 6 1.5 6Z" stroke="currentColor" strokeWidth="1.2"/><circle cx="6" cy="6" r="1.5" stroke="currentColor" strokeWidth="1.2"/></svg>
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      {artifacts.length > 0 && (
        <div className="px-3.5 py-2.5 border-t border-zinc-800 bg-zinc-950/40">
          <a href={`/api/github/artifact?run=${runId}&name=nish-agent-workspace-${runId}`} target="_blank" className="flex items-center justify-center gap-2 h-8 rounded-xl bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 text-xs font-medium text-zinc-300 hover:text-white transition-colors">
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M6 2.5V9M3 6.5L6 9.5L9 6.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/></svg>
            Download workspace
          </a>
        </div>
      )}
    </div>
  );
}
