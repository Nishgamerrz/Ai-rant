"use client";
import { useCallback, useEffect, useState } from "react";
import { Sidebar } from "@/components/Sidebar";
import { ChatWindow } from "@/components/ChatWindow";
import { FileExplorer } from "@/components/FileExplorer";
import { LogViewer } from "@/components/LogViewer";
import { NewChatModal } from "@/components/NewChatModal";
import { SubagentTimeline } from "@/components/SubagentTimeline";

export default function Home() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [selectedRun, setSelectedRun] = useState<number | null>(null);
  const [rightTab, setRightTab] = useState<"files" | "logs" | "subagent">("files");
  const [preview, setPreview] = useState<{ path: string; content: string } | null>(null);
  const [steps, setSteps] = useState<any[]>([]);
  const [runStatus, setRunStatus] = useState("idle");
  const [liveLog, setLiveLog] = useState<string>("");
  const [chatNotice, setChatNotice] = useState("");

  const pollLogs = useCallback(async () => {
    if (!selectedRun) return;
    try {
      const j = await fetch(`/api/github/logs?run=${selectedRun}&logs=1`, { cache: "no-store" }).then((r) => r.json());
      if (j.steps) setSteps(j.steps);
      if (j.run) {
        const st = j.run.status + (j.run.conclusion ? " · " + j.run.conclusion : "");
        setRunStatus(st);
        if (j.run.status === "in_progress" || j.run.status === "queued") {
          setRightTab((prev) => prev);
        }
      }
      if (j.logTail) setLiveLog(j.logTail);
    } catch {}
  }, [selectedRun]);

  useEffect(() => {
    if (!selectedRun) {
      setSteps([]);
      setRunStatus("idle");
      setLiveLog("");
      return;
    }
    setRightTab("logs");
    pollLogs();
    const id = setInterval(pollLogs, 3500);
    return () => clearInterval(id);
  }, [selectedRun, pollLogs]);

  return (
    <div className="min-h-screen bg-[#09090b] flex">
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} onNewChat={() => setModalOpen(true)} selectedRun={selectedRun} onSelectRun={(run) => { setChatNotice(""); setSelectedRun(run); }} />

      <div className="flex-1 flex flex-col min-h-screen min-w-0">
        {/* Header */}
        <div className="sticky top-0 z-10 bg-[#09090b]/80 backdrop-blur-xl border-b border-zinc-800/80">
          <div className="h-14 px-4 flex items-center gap-3">
            <button onClick={() => setSidebarOpen(true)} className="md:hidden h-9 w-9 grid place-items-center rounded-xl bg-zinc-900 border border-zinc-800 text-zinc-400">
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M3 5H13M3 8H13M3 11H13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg>
            </button>
            <div className="min-w-0 hidden sm:block">
              <h1 className="text-sm font-semibold tracking-tight leading-none">Agent Workspace</h1>
              <p className="text-xs text-zinc-500 leading-none mt-1">Real-time workflow chat · direct GitHub API · no tunnel</p>
            </div>
            <div className="ml-auto flex items-center gap-2">
              <div className="hidden lg:flex items-center gap-1 p-1 rounded-xl bg-zinc-900 border border-zinc-800">
                <button onClick={() => setRightTab("files")} className={`px-2.5 py-1.5 rounded-lg text-xs font-medium transition-colors ${rightTab === "files" ? "bg-white text-zinc-900 shadow-soft" : "text-zinc-500 hover:text-zinc-300"}`}>Files</button>
                <button onClick={() => setRightTab("logs")} className={`px-2.5 py-1.5 rounded-lg text-xs font-medium transition-colors ${rightTab === "logs" ? "bg-white text-zinc-900 shadow-soft" : "text-zinc-500 hover:text-zinc-300"}`}>Logs</button>
                <button onClick={() => setRightTab("subagent")} className={`px-2.5 py-1.5 rounded-lg text-xs font-medium transition-colors ${rightTab === "subagent" ? "bg-white text-zinc-900 shadow-soft" : "text-zinc-500 hover:text-zinc-300"}`}>Subagent</button>
              </div>
              <button onClick={() => setModalOpen(true)} className="h-9 px-4 rounded-xl bg-white text-zinc-900 font-medium text-sm flex items-center gap-2 hover:bg-zinc-100 transition-colors shadow-soft">
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M7 2.5V11.5M2.5 7H11.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/></svg>
                <span className="hidden sm:inline">New workflow</span>
                <span className="sm:hidden">New</span>
              </button>
            </div>
          </div>
        </div>

        <div className="flex-1 flex min-h-0">
          {/* Chat */}
          <div className="flex-1 flex flex-col min-w-0">
            <ChatWindow runId={selectedRun} notice={chatNotice} />
          </div>

          {/* Right panel — desktop */}
          <div className="hidden lg:flex w-[380px] shrink-0 border-l border-zinc-800/80 bg-zinc-900/20 flex-col">
            <div className="flex-1 overflow-auto p-3 space-y-3">
              {rightTab === "files" && <FileExplorer runId={selectedRun} onOpenFile={(path, content) => setPreview({ path, content })} />}
              {rightTab === "logs" && <LogViewer steps={steps} runStatus={runStatus} logTail={liveLog} />}
              {rightTab === "subagent" && <SubagentTimeline runId={selectedRun} kind="agent" liveLog={liveLog || undefined} />}
              {rightTab === "files" && selectedRun && <div className="pt-3 border-t border-zinc-800/60"><SubagentTimeline runId={selectedRun} kind="agent" liveLog={liveLog || undefined} /></div>}
              {rightTab === "logs" && selectedRun && <div className="pt-3 border-t border-zinc-800/60"><FileExplorer runId={selectedRun} onOpenFile={(path, content) => setPreview({ path, content })} /></div>}
            </div>
          </div>
        </div>

        {/* Mobile tabs */}
        <div className="lg:hidden border-t border-zinc-800/80 bg-zinc-900/40 p-3 space-y-3">
          <div className="flex gap-1 p-1 rounded-xl bg-zinc-900 border border-zinc-800 w-fit">
            <button onClick={() => setRightTab("files")} className={`px-3 py-1.5 rounded-lg text-xs font-medium ${rightTab === "files" ? "bg-white text-zinc-900" : "text-zinc-500"}`}>Files</button>
            <button onClick={() => setRightTab("logs")} className={`px-3 py-1.5 rounded-lg text-xs font-medium ${rightTab === "logs" ? "bg-white text-zinc-900" : "text-zinc-500"}`}>Logs</button>
            <button onClick={() => setRightTab("subagent")} className={`px-3 py-1.5 rounded-lg text-xs font-medium ${rightTab === "subagent" ? "bg-white text-zinc-900" : "text-zinc-500"}`}>Subagent</button>
          </div>
          {rightTab === "files" && <FileExplorer runId={selectedRun} onOpenFile={(p, c) => setPreview({ path: p, content: c })} />}
          {rightTab === "logs" && <LogViewer steps={steps} runStatus={runStatus} logTail={liveLog} />}
          {rightTab === "subagent" && <SubagentTimeline runId={selectedRun} kind="agent" liveLog={liveLog || undefined} />}
        </div>

        {/* Preview modal */}
        {preview && (
          <div className="fixed inset-0 z-40 flex items-center justify-center p-4">
            <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setPreview(null)} />
            <div className="relative w-full max-w-3xl rounded-2xl bg-zinc-900 border border-zinc-800 shadow-large max-h-[85vh] overflow-hidden flex flex-col animate-slideIn">
              <div className="h-12 px-4 flex items-center gap-3 border-b border-zinc-800 shrink-0">
                <div className="text-sm font-medium truncate">{preview.path}</div>
                <button onClick={() => setPreview(null)} className="ml-auto h-8 px-3 rounded-xl bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 text-xs font-medium text-zinc-300 transition-colors">Close</button>
                <a href={`data:text/plain;charset=utf-8,${encodeURIComponent(preview.content)}`} download={preview.path.split("/").pop() || "file.txt"} className="h-8 px-3 rounded-xl bg-white text-zinc-900 text-xs font-semibold hover:bg-zinc-100 transition-colors flex items-center">Download</a>
              </div>
              <pre className="flex-1 p-4 text-xs font-mono leading-relaxed whitespace-pre-wrap break-words overflow-auto text-zinc-300">{preview.content}</pre>
            </div>
          </div>
        )}
      </div>

      <NewChatModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onStart={(payload: any) => {
          setModalOpen(false);
          const rid = payload?.runId;
          const chatToken = String(payload?.chatToken || "");
          setChatNotice(String(payload?.chatNotice || ""));
          const rememberSession = (run: number) => {
            if (!chatToken) return;
            sessionStorage.setItem(`nishagent_chat_${run}`, chatToken);
            sessionStorage.removeItem("nishagent_pending_chat_key");
          };
          if (rid) {
            rememberSession(rid);
            setSelectedRun(rid);
          } else {
            if (chatToken) sessionStorage.setItem("nishagent_pending_chat_key", chatToken);
            const createdAfter = Number(payload?.createdAfter || 0);
            const dispatchId = String(payload?.dispatchId || "");
            void (async () => {
              for (let i = 0; i < 30; i++) {
                await new Promise((resolve) => setTimeout(resolve, 1000));
                try {
                  const j = await fetch("/api/github/runs?kind=agent&per_page=10", { cache: "no-store" }).then((r) => r.json());
                  const match = dispatchId
                    ? j?.runs?.find((run: any) => String(run.display_title || "").includes(dispatchId))
                    : j?.runs?.find((run: any) => !createdAfter || new Date(run.created_at).getTime() >= createdAfter);
                  if (match?.id) {
                    rememberSession(match.id);
                    setSelectedRun(match.id);
                    return;
                  }
                } catch {}
              }
            })();
          }
        }}
      />
    </div>
  );
}
