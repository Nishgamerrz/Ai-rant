"use client";
import { useEffect, useState } from "react";

type Entry = { name: string; path: string; size?: number; kind: "file" | "dir" };

export function FileExplorer({ runId, onOpenFile, tunnelUrl }: { runId: number | null; onOpenFile: (path: string, content: string) => void; tunnelUrl?: string | null }) {
  const [artifacts, setArtifacts] = useState<any[]>([]);
  const [files, setFiles] = useState<Entry[] | null>(null);
  const [liveFiles, setLiveFiles] = useState<Entry[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [activeArtifact, setActiveArtifact] = useState<string | null>(null);
  const [liveMode, setLiveMode] = useState(false);

  async function loadArtifacts() {
    if (!runId) return;
    setLoading(true);
    setErr("");
    try {
      const j = await fetch(`/api/github/logs?run=${runId}`, { cache: "no-store" }).then((r) => r.json());
      if (j.error) throw new Error(j.error);
      const arts = j.artifacts || [];
      setArtifacts(arts);
      if (arts.length && !activeArtifact) {
        const ws = arts.find((a: any) => String(a.name).includes("workspace")) || arts.find((a: any) => String(a.name).includes("nish-agent")) || arts[0];
        if (ws) {
          setActiveArtifact(String(ws.id));
          loadFiles(String(ws.id));
        }
      }
    } catch (e: any) {
      setErr(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }

  async function loadFiles(artifactId: string) {
    setActiveArtifact(artifactId);
    setLoading(true);
    setErr("");
    try {
      const res = await fetch(`/api/github/artifact?id=${artifactId}`, { cache: "no-store" });
      if (!res.ok) throw new Error(`artifact ${res.status}`);
      const buf = await res.arrayBuffer();
      const JSZip = (await import("jszip")).default;
      const zip = await JSZip.loadAsync(buf);
      const entries: Entry[] = [];
      Object.keys(zip.files).forEach((k) => {
        const f = zip.files[k];
        if (f.dir) return;
        if (k.includes("__MACOSX")) return;
        const name = k.split("/").pop() || k;
        entries.push({ name, path: k, kind: "file", size: (f as any)._data?.uncompressedSize || 0 });
      });
      const priority = (n: string) => {
        if (n.includes("Map") || n.includes("map")) return 0;
        if (n.includes("chat")) return 1;
        if (n.includes("tools")) return 2;
        if (n.endsWith(".json")) return 3;
        if (n.endsWith(".txt")) return 4;
        if (n.endsWith(".png") || n.endsWith(".jpg")) return 5;
        return 6;
      };
      entries.sort((a, b) => priority(a.name) - priority(b.name) || a.name.localeCompare(b.name));
      setFiles(entries.slice(0, 80));
      if (entries.length === 0) setErr("Artifact is empty or still uploading.");
    } catch (e: any) {
      setErr(String(e.message || e));
      setFiles([]);
    } finally {
      setLoading(false);
    }
  }

  async function loadLive() {
    if (!runId) return;
    // try live via tunnel if available, else via logs tail inference
    const liveUrl = tunnelUrl ? `/api/agent/files?run=${runId}&path=.&tunnel=${encodeURIComponent(tunnelUrl)}` : null;
    if (liveUrl) {
      try {
        const r = await fetch(liveUrl, { cache: "no-store" });
        const j = await r.json().catch(() => null);
        if (j && j.ok && Array.isArray(j.files)) {
          const entries: Entry[] = (j.files as string[]).filter((f: string) => !f.startsWith("dir/") && !f.includes("__MACOSX")).map((f: string) => ({
            name: f.split("/").pop() || f,
            path: f,
            kind: "file" as const,
          }));
          // priority sort
          const priority = (n: string) => {
            if (/map|cam|world/i.test(n)) return 0;
            if (/chat|tools/i.test(n)) return 1;
            if (n.endsWith(".json")) return 2;
            if (n.endsWith(".py") || n.endsWith(".js") || n.endsWith(".html")) return 3;
            if (/\.(png|jpg|jpeg|mp4)$/i.test(n)) return 4;
            return 5;
          };
          entries.sort((a, b) => priority(a.name) - priority(b.name) || a.name.localeCompare(b.name));
          setLiveFiles(entries.slice(0, 80));
          setLiveMode(true);
          setErr("");
          return;
        }
      } catch {}
    }
    // fallback: infer files from live log tail? we already have live log via parent but not here
    // try artifact fallback already loaded
    setLiveMode(false);
  }

  useEffect(() => {
    setArtifacts([]);
    setFiles(null);
    setLiveFiles(null);
    setActiveArtifact(null);
    setLiveMode(false);
    if (runId) {
      loadArtifacts();
      loadLive();
    }
  }, [runId]);

  // poll live files when tunnelUrl present
  useEffect(() => {
    if (!runId || !tunnelUrl) return;
    loadLive();
    const id = setInterval(loadLive, 3500);
    return () => clearInterval(id);
  }, [runId, tunnelUrl]);

  if (!runId) {
    return (
      <div className="rounded-2xl border border-dashed border-zinc-800 bg-zinc-900/20 p-6 text-center">
        <div className="h-10 w-10 rounded-xl bg-zinc-800 grid place-items-center mx-auto">
          <svg width="18" height="18" viewBox="0 0 18 18" fill="none"><path d="M4 3.5H10L14 7.5V14.5H4V3.5Z" stroke="#71717a" strokeWidth="1.3" strokeLinejoin="round"/><path d="M10 3.5V7.5H14" stroke="#71717a" strokeWidth="1.3" strokeLinejoin="round"/></svg>
        </div>
        <div className="text-sm font-medium text-zinc-300 mt-3">No run selected</div>
        <div className="text-xs text-zinc-600 mt-1 leading-relaxed">Select a workflow to browse<br/>maps, cams, and generated files.</div>
      </div>
    );
  }

  const displayLive = liveMode && liveFiles && liveFiles.length > 0;
  const displayFiles = displayLive ? liveFiles : files;

  return (
    <div className="rounded-2xl bg-zinc-900 border border-zinc-800 overflow-hidden shadow-soft">
      <div className="h-10 px-3 flex items-center gap-2 border-b border-zinc-800 bg-zinc-900">
        <div className="h-6 w-6 rounded-lg bg-zinc-800 grid place-items-center shrink-0">
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M2.5 2H6L9.5 5V10H2.5V2Z" stroke="#a1a1aa" strokeWidth="1.2" strokeLinejoin="round"/><path d="M6 2V5H9.5" stroke="#27272a" strokeWidth="1.2"/></svg>
        </div>
        <span className="text-xs font-semibold tracking-wide text-zinc-200">Files</span>
        {liveMode && <span className="text-[11px] px-1.5 py-0.5 rounded-full bg-emerald-950/40 border border-emerald-900/50 text-emerald-300 animate-pulse">Live</span>}
        {!liveMode && artifacts.length > 0 && (
          <select value={activeArtifact || ""} onChange={(e) => loadFiles(e.target.value)} className="ml-2 h-7 rounded-lg bg-zinc-800 border border-zinc-700 text-xs text-zinc-300 px-2 max-w-[160px]">
            {artifacts.map((a) => (
              <option key={a.id} value={a.id}>{a.name}</option>
            ))}
          </select>
        )}
        {liveMode && <span className="ml-2 text-[11px] text-zinc-500">{liveFiles?.length} files</span>}
        <button onClick={() => { loadArtifacts(); loadLive(); }} className="ml-auto h-7 px-2.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 text-xs font-medium text-zinc-400 hover:text-zinc-200 transition-colors">Reload</button>
      </div>

      {liveMode && (
        <div className="px-3 py-1.5 bg-emerald-950/20 border-b border-emerald-900/20 text-[11px] text-emerald-300 flex items-center gap-1.5">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" /> Live via tunnel — updating every 3.5s as AI creates files
        </div>
      )}

      <div className="p-2 min-h-[180px] max-h-[420px] overflow-auto">
        {loading && (
          <div className="flex items-center gap-2 px-3 py-3 text-xs text-zinc-500">
            <span className="h-3 w-3 border border-zinc-700 border-t-zinc-400 rounded-full animate-spin" />
            Loading…
          </div>
        )}
        {err && !loading && <div className="mx-1 rounded-lg bg-amber-950/20 border border-amber-900/30 text-amber-300 text-xs p-2.5">{err}</div>}

        {!loading && displayFiles && displayFiles.length > 0 && (
          <div className="space-y-1">
            {displayFiles.map((f) => {
              const isMap = /map|cam|world/i.test(f.name);
              const isChat = /chat|tools|tunnel/i.test(f.name);
              const isMedia = /\.(png|jpg|jpeg|mp4|webm)$/i.test(f.name);
              const isCode = /\.(py|js|ts|html|json|txt|md)$/i.test(f.name);
              return (
                <button
                  key={f.path}
                  onClick={async () => {
                    try {
                      if (liveMode && tunnelUrl) {
                        // try live file fetch via tunnel
                        const res = await fetch(`/api/agent/files?run=${runId}&path=${encodeURIComponent(f.path)}&tunnel=${encodeURIComponent(tunnelUrl)}`, { cache: "no-store" });
                        const ct = res.headers.get("content-type") || "";
                        if (res.ok) {
                          if (ct.includes("application/json")) {
                            const j = await res.json().catch(() => null);
                            if (j && typeof j === "object" && j.files) {
                              // it's a dir listing, not file
                            } else {
                              onOpenFile(f.path, JSON.stringify(j, null, 2).slice(0, 50000));
                              return;
                            }
                          } else {
                            const txt = await res.text();
                            if (txt.startsWith('{"ok":false')) {
                              // fallback to artifact
                            } else {
                              onOpenFile(f.path, txt.slice(0, 50000));
                              return;
                            }
                          }
                        }
                      }
                      if (!activeArtifact) {
                        // try artifact fallback if no activeArtifact but artifacts exist
                        if (artifacts[0]) {
                          const res = await fetch(`/api/github/artifact?id=${artifacts[0].id}&json=${encodeURIComponent(f.path)}`, { cache: "no-store" });
                          const ct = res.headers.get("content-type") || "";
                          let txt: string;
                          if (ct.includes("application/json")) {
                            const j = await res.json();
                            txt = JSON.stringify(j, null, 2);
                          } else txt = await res.text();
                          onOpenFile(f.path, txt.slice(0, 50000));
                          return;
                        }
                        onOpenFile(f.path, "No artifact available");
                        return;
                      }
                      const res = await fetch(`/api/github/artifact?id=${activeArtifact}&json=${encodeURIComponent(f.path)}`, { cache: "no-store" });
                      const ct = res.headers.get("content-type") || "";
                      let txt: string;
                      if (ct.includes("application/json")) {
                        const j = await res.json();
                        txt = JSON.stringify(j, null, 2);
                      } else {
                        txt = await res.text();
                      }
                      if (isMedia && txt.length < 100 && txt.includes("not in zip")) {
                        window.open(`/api/github/artifact?id=${activeArtifact}`, "_blank");
                        return;
                      }
                      onOpenFile(f.path, txt.slice(0, 50000));
                    } catch (e: any) {
                      onOpenFile(f.path, String(e.message || e));
                    }
                  }}
                  className="w-full flex items-center gap-2.5 rounded-xl border border-zinc-800 bg-zinc-950/30 hover:bg-zinc-800/60 hover:border-zinc-700 px-3 py-2.5 text-left transition-colors group"
                >
                  <span className={`h-7 w-7 rounded-lg grid place-items-center shrink-0 border ${isMap ? "bg-emerald-950/30 border-emerald-900/30 text-emerald-400" : isChat ? "bg-violet-950/20 border-violet-900/30 text-violet-400" : isMedia ? "bg-amber-950/20 border-amber-900/30 text-amber-400" : isCode ? "bg-zinc-800 border-zinc-700 text-zinc-400" : "bg-zinc-800 border-zinc-700 text-zinc-500"}`}>
                    {isMap ? "◈" : isChat ? "◐" : isMedia ? "◎" : isCode ? "▭" : "▭"}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-xs font-medium text-zinc-200 truncate group-hover:text-white">{f.name}</span>
                    <span className="block text-[11px] text-zinc-600 truncate">{f.path}</span>
                  </span>
                  <span className="text-[11px] text-zinc-600 shrink-0">{f.size ? `${(f.size / 1024).toFixed(1)}k` : liveMode ? "live" : ""}</span>
                </button>
              );
            })}
          </div>
        )}

        {!loading && displayFiles && displayFiles.length === 0 && !err && <div className="px-3 py-6 text-center text-xs text-zinc-600">{liveMode ? "No files yet — AI will create them live" : "No files in this artifact yet — the run is still initializing."}</div>}
        {!loading && !displayFiles && artifacts.length === 0 && !liveMode && <div className="px-3 py-3 text-xs text-zinc-600">No artifacts yet. {tunnelUrl ? "Live files will appear here via tunnel." : "They appear after the first job uploads."}</div>}
      </div>

      {activeArtifact && !liveMode && (
        <div className="px-3 py-2 border-t border-zinc-800 bg-zinc-950/30 flex gap-2">
          <a href={`/api/github/artifact?id=${activeArtifact}`} target="_blank" className="flex-1 h-8 rounded-xl bg-white text-zinc-900 text-xs font-semibold hover:bg-zinc-100 transition-colors flex items-center justify-center gap-1.5">
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M6 2.5V9M3 6.5L6 9.5L9 6.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/></svg>
            Download zip
          </a>
          <button
            onClick={() => {
              const sel = artifacts.find((a) => String(a.id) === String(activeArtifact));
              if (sel) window.open(`/api/github/artifact?id=${sel.id}`, "_blank");
            }}
            className="h-8 px-3 rounded-xl bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 text-xs font-medium text-zinc-300 transition-colors"
          >
            Open
          </button>
        </div>
      )}
      {liveMode && (
        <div className="px-3 py-2 border-t border-zinc-800 bg-zinc-950/30 text-[11px] text-zinc-500">
          Live mode — files stream directly from runner workspace via <code className="bg-zinc-800 px-1 rounded">trycloudflare.com/__nish/files</code>
        </div>
      )}
    </div>
  );
}
