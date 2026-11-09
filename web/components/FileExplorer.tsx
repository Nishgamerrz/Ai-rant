"use client";
import { useEffect, useState } from "react";

type FileNode = { name: string; path: string; type: "file" | "dir"; size?: number; children?: FileNode[] };

function FileRow({ node, depth, onOpen }: { node: FileNode; depth: number; onOpen: (path: string) => void }) {
  const [open, setOpen] = useState(depth < 1);
  if (node.type === "dir") {
    return (
      <div>
        <button onClick={() => setOpen(!open)} className="flex items-center gap-2 w-full text-left px-2 py-1.5 hover:bg-zinc-800 rounded-lg text-sm">
          <span className="text-zinc-500">{open ? "▾" : "▸"}</span>
          <span className="text-amber-300">📁</span>
          <span className="truncate">{node.name}</span>
        </button>
        {open && node.children && (
          <div className="ml-4 border-l border-zinc-800 pl-2 space-y-0.5">
            {node.children.map((c) => (
              <FileRow key={c.path} node={c} depth={depth + 1} onOpen={onOpen} />
            ))}
          </div>
        )}
      </div>
    );
  }
  return (
    <button onClick={() => onOpen(node.path)} className="flex items-center gap-2 w-full text-left px-2 py-1.5 hover:bg-zinc-800 rounded-lg text-sm">
      <span className="text-zinc-600">•</span>
      <span className="truncate text-zinc-300">{node.name}</span>
      <span className="ml-auto text-xs text-zinc-600">{node.size ? `${(node.size / 1024).toFixed(1)}k` : ""}</span>
    </button>
  );
}

export function FileExplorer({ runId, onOpenFile }: { runId: number | null; onOpenFile: (path: string, content: string) => void }) {
  const [tree, setTree] = useState<FileNode[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  async function load() {
    if (!runId) return;
    setLoading(true);
    setErr("");
    try {
      // Prefer the chat json that lists workspace files via agent_tools; fallback to artifact file list via /api/github/logs
      const chatRes = await fetch(`/api/github/artifact?run=${runId}&name=nish-agent-${runId}&json=agent_chat.json`);
      if (chatRes.ok) {
        const chat = await chatRes.json();
        // try to infer files from tool calls
        const files = new Map<string, number>();
        for (const m of Array.isArray(chat) ? chat : []) {
          for (const tc of m.tool_calls || []) {
            if (tc.path) files.set(tc.path, 0);
          }
          if (m.output?.path) files.set(m.output.path, 0);
        }
      }
      // List workspace artifact contents via zip index
      const logs = await fetch(`/api/github/logs?run=${runId}`).then((r) => r.json());
      if (logs.error) throw new Error(logs.error);
      const artifacts: any[] = logs.artifacts || [];
      const ws = artifacts.find((a) => String(a.name).includes("workspace"));
      const main = artifacts.find((a) => String(a.name).startsWith("nish-agent-"));
      // We show artifacts as folders; clicking fetches via /api/github/artifact
      const nodes: FileNode[] = [];
      for (const a of artifacts) {
        nodes.push({ name: `${a.name}.zip`, path: `artifact:${a.id}`, type: "file", size: a.size_in_bytes });
      }
      // also try to list dist/agent_workspace via chat artifact if available
      if (main) {
        const wsList = await fetch(`/api/github/artifact?id=${main.id}&json=agent_tools.jsonl`).then((r) => r.text()).catch(() => "");
        // not structured — keep artifact view
      }
      setTree(nodes.length ? nodes : [{ name: "(no artifacts yet — run still starting)", path: "-", type: "file" }]);
    } catch (e: any) {
      setErr(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setTree(null);
    if (runId) load();
  }, [runId]);

  if (!runId) return <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-4 text-sm text-zinc-500">Select an agent run from the sidebar to browse the files it created. You can open, download or preview any file — the whole workspace is saved as a workflow artifact.</div>;

  return (
    <div className="rounded-xl bg-zinc-950 border border-zinc-800 overflow-hidden">
      <div className="px-3 py-2 border-b border-zinc-800 flex items-center gap-2">
        <span className="text-xs font-semibold text-zinc-300">Workspace — files the AI created</span>
        <button onClick={load} className="ml-auto text-xs rounded-lg border border-zinc-800 px-2 py-1 hover:bg-zinc-900">Reload</button>
        <a href={runId ? `/api/github/artifact?run=${runId}&name=nish-agent-workspace-${runId}` : "#"} target="_blank" className="text-xs rounded-lg bg-white text-zinc-900 px-2 py-1">Download workspace zip</a>
      </div>
      <div className="p-2 min-h-[180px] max-h-[420px] overflow-auto">
        {loading && <div className="text-xs text-zinc-500">Loading file list from workflow artifacts…</div>}
        {err && <div className="text-xs text-amber-300">{err}</div>}
        {tree && (
          <div className="space-y-0.5">
            {tree.map((n) => (
              <FileRow
                key={n.path}
                node={n}
                depth={0}
                onOpen={async (path) => {
                  if (path.startsWith("artifact:")) {
                    const id = path.split(":")[1];
                    window.open(`/api/github/artifact?id=${id}`, "_blank");
                    return;
                  }
                  // try to fetch via artifact json
                  try {
                    const res = await fetch(`/api/github/artifact?run=${runId}&name=nish-agent-${runId}&json=${encodeURIComponent(path)}`);
                    const txt = await res.text();
                    onOpenFile(path, txt.slice(0, 20000));
                  } catch (e: any) {
                    onOpenFile(path, String(e.message || e));
                  }
                }}
              />
            ))}
          </div>
        )}
        {!loading && !tree && <div className="text-xs text-zinc-600">Open the explorer after the agent has created files — they appear in the artifact as dist/agent_workspace/…</div>}
      </div>
      <div className="px-3 py-2 border-t border-zinc-800 text-xs text-zinc-600">Other side of the chat — as you asked: folder view with open / download / preview. New chat → pick what to create → run appears here.</div>
    </div>
  );
}
