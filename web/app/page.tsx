"use client";
import { useEffect, useState } from "react";
import { Sidebar } from "@/components/Sidebar";
import { ChatWindow } from "@/components/ChatWindow";
import { FileExplorer } from "@/components/FileExplorer";
import { LogViewer } from "@/components/LogViewer";
import { NewChatModal } from "@/components/NewChatModal";

export default function Home() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [selectedRun, setSelectedRun] = useState<number | null>(null);
  const [tunnelUrl, setTunnelUrl] = useState<string | null>(null);
  const [showFiles, setShowFiles] = useState(true);
  const [preview, setPreview] = useState<{ path: string; content: string } | null>(null);
  // live log state for selected run
  const [steps, setSteps] = useState<any[]>([]);
  const [runStatus, setRunStatus] = useState("idle");

  async function pollLogs() {
    if (!selectedRun) return;
    try {
      const j = await fetch(`/api/github/logs?run=${selectedRun}`, { cache: "no-store" }).then((r) => r.json());
      if (j.steps) setSteps(j.steps);
      if (j.run) setRunStatus(j.run.status + (j.run.conclusion ? " · " + j.run.conclusion : ""));
      // tunnel
      const t = await fetch(`/api/agent/tunnel?run=${selectedRun}`, { cache: "no-store" }).then((r) => r.json()).catch(() => null);
      if (t?.tunnel_url) setTunnelUrl(t.tunnel_url);
      else setTunnelUrl(null);
    } catch {}
  }

  useEffect(() => {
    if (!selectedRun) {
      setSteps([]);
      setRunStatus("idle");
      setTunnelUrl(null);
      return;
    }
    pollLogs();
    const id = setInterval(pollLogs, 4000);
    return () => clearInterval(id);
  }, [selectedRun]);

  return (
    <div className="min-h-screen bg-ink flex">
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} onNewChat={() => setModalOpen(true)} selectedRun={selectedRun} onSelectRun={setSelectedRun} />

      <div className="flex-1 flex flex-col min-h-screen min-w-0">
        {/* Top bar */}
        <div className="sticky top-0 z-10 bg-ink/80 backdrop-blur border-b border-line px-3 py-2 flex items-center gap-2">
          <button onClick={() => setSidebarOpen(true)} className="md:hidden rounded-xl border border-zinc-800 px-3 py-2 text-sm">☰ Chats</button>
          <div className="min-w-0">
            <div className="font-semibold text-sm flex items-center gap-2">Agent chat <span className="hidden sm:inline text-xs px-2 py-0.5 rounded-full bg-violet-600 text-white">GitHub workflows + Cloudflare tunnel</span></div>
            <div className="text-xs text-zinc-500 hidden sm:block">Search the web · create files & images · run commands · Gemini sub-agent for code — all in the sandbox. Sidebar holds every chat, right side holds the files.</div>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <button onClick={() => setShowFiles(!showFiles)} className="rounded-xl border border-zinc-800 px-3 py-2 text-xs hover:bg-zinc-900">{showFiles ? "Hide files" : "Show files"}</button>
            <button onClick={() => setModalOpen(true)} className="hidden sm:inline rounded-xl bg-white text-zinc-900 font-semibold px-4 py-2 text-sm">＋ New chat</button>
          </div>
        </div>

        <div className="flex-1 flex min-h-0">
          {/* Chat */}
          <div className="flex-1 flex flex-col min-w-0 border-r border-line/60">
            <ChatWindow runId={selectedRun} tunnelUrl={tunnelUrl} liveMode={Boolean(tunnelUrl)} />
          </div>

          {/* File explorer + logs side — per spec: "other side of the chat when a new chat ... also a folder to see the files that ai created or open the files download or open folders at other side of the chat" */}
          {showFiles && (
            <div className="hidden lg:flex w-[420px] shrink-0 flex-col bg-panel/60 overflow-hidden">
              <div className="p-3 space-y-3 overflow-auto">
                <FileExplorer runId={selectedRun} onOpenFile={(path, content) => setPreview({ path, content })} />
                <LogViewer steps={steps} runStatus={runStatus} />
                <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-3">
                  <div className="text-xs font-semibold text-zinc-200">How it works — for the UI you asked for</div>
                  <ul className="mt-2 space-y-1 text-xs text-zinc-400 list-disc list-inside">
                    <li><b className="text-zinc-200">New chat</b> → pick <b>Agent</b> (prompt + hard model) or <b>RBX Short</b> (topic/usernames) → we POST <code className="bg-zinc-800 px-1 rounded">/api/github/dispatch</code> which uses the server-only <code className="bg-zinc-800 px-1 rounded">GITHUB_TOKEN</code> to dispatch the workflow.</li>
                    <li><b className="text-zinc-200">Live logs</b> coloured like the runner (thinking grey, answer cyan, tool violet) — we poll <code className="bg-zinc-800 px-1 rounded">/api/github/logs?run=…</code> every 4s. Model loads vs prompt-reading (“plan next / previous loads”) come from <code className="bg-zinc-800 px-1 rounded">/api/ps</code> honesty already in the workflow.</li>
                    <li><b className="text-zinc-200">Cloudflare tunnel</b>: tick <b>Enable tunnel</b> when you create an Agent chat — the workflow runs <code className="bg-zinc-800 px-1 rounded">cloudflared tunnel --url http://127.0.0.1:8787</code> and prints a <code className="bg-zinc-800 px-1 rounded">https://…trycloudflare.com</code> URL. We store it in <code className="bg-zinc-800 px-1 rounded">dist/tunnel_url.txt</code> and proxy live messages through <code className="bg-zinc-800 px-1 rounded">/api/agent/chat</code>.</li>
                    <li><b className="text-zinc-200">Chats sidebar</b> loads from <code className="bg-zinc-800 px-1 rounded">/api/github/runs</code> — every workflow becomes a chat. Works on mobile as a drawer.</li>
                    <li><b className="text-zinc-200">Files</b>: every tool (<code className="bg-zinc-800 px-1 rounded">create_file</code>, <code>create_image</code>, <code>run_cmd</code>) writes under <code className="bg-zinc-800 px-1 rounded">dist/agent_workspace</code>. It’s uploaded as an artifact — preview any file here, open folders, or download the zip.</li>
                    <li><b className="text-zinc-200">Sub-agent</b>: the “hard” agent workflow can call <code className="bg-zinc-800 px-1 rounded">subagent</code> (Gemini → Groq fallback) for code, so the local AI delegates hard work.</li>
                  </ul>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Mobile files drawer */}
        {showFiles && (
          <div className="lg:hidden border-t border-line p-3 space-y-3 bg-panel">
            <FileExplorer runId={selectedRun} onOpenFile={(p, c) => setPreview({ path: p, content: c })} />
            <LogViewer steps={steps} runStatus={runStatus} />
          </div>
        )}

        {/* File preview */}
        {preview && (
          <div className="fixed inset-0 z-40 grid place-items-center p-4">
            <div className="absolute inset-0 bg-black/70" onClick={() => setPreview(null)} />
            <div className="relative w-full max-w-3xl rounded-2xl bg-zinc-950 border border-zinc-800 max-h-[84vh] overflow-hidden flex flex-col">
              <div className="px-4 py-3 border-b border-zinc-800 flex items-center gap-3">
                <div className="text-sm font-semibold truncate">{preview.path}</div>
                <button onClick={() => setPreview(null)} className="ml-auto rounded-lg border border-zinc-700 px-3 py-1.5 text-xs">Close</button>
                <a href={`data:text/plain;charset=utf-8,${encodeURIComponent(preview.content)}`} download={preview.path.split("/").pop() || "file.txt"} className="rounded-lg bg-white text-zinc-900 px-3 py-1.5 text-xs font-semibold">Download</a>
              </div>
              <pre className="p-4 text-xs font-mono whitespace-pre-wrap break-words overflow-auto">{preview.content}</pre>
            </div>
          </div>
        )}
      </div>

      <NewChatModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onStart={(payload) => {
          setModalOpen(false);
          // After dispatch, refresh runs and select the newest
          setTimeout(async () => {
            const j = await fetch("/api/github/runs?kind=agent&per_page=1").then((r) => r.json()).catch(() => null);
            const newest = j?.runs?.[0]?.id;
            if (newest) setSelectedRun(newest);
          }, 3000);
        }}
      />
    </div>
  );
}
