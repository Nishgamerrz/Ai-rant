"use client";
import { kindForLine, stripAnsi } from "@/lib/colors";

// Renders live workflow steps with colours matching tools/console_style.py.
// Also shows plan next/previous (model prefill vs reload) from the logs API.
export function LogViewer({ steps, runStatus }: { steps: any[]; runStatus: string }) {
  if (!steps?.length) return <div className="text-xs text-zinc-600">No steps yet — the runner is still starting…</div>;
  return (
    <div className="rounded-xl bg-zinc-950 border border-zinc-800 overflow-hidden">
      <div className="px-3 py-2 border-b border-zinc-800 flex items-center gap-2 text-xs">
        <span className={`h-2 w-2 rounded-full ${runStatus === "completed" ? "bg-zinc-500" : "bg-amber-400 animate-pulse"}`} />
        <span className="text-zinc-400">Workflow logs</span>
        <span className="text-zinc-600">· colours: thinking grey · answer cyan · tool violet · success green</span>
      </div>
      <div className="max-h-[320px] overflow-auto font-mono text-xs">
        {steps.map((s: any, i: number) => {
          const kind =
            s.conclusion === "success" ? "success" : s.conclusion === "failure" ? "error" : s.conclusion === "skipped" ? "muted" : s.status === "in_progress" ? "notice" : "muted";
          const icon = s.conclusion === "success" ? "✓" : s.conclusion === "failure" ? "✗" : s.status === "in_progress" ? "◐" : "○";
          return (
            <div key={i} className="flex gap-3 px-3 py-1.5 border-b border-zinc-900/60 hover:bg-zinc-900/40">
              <span className={`shrink-0 font-bold ${kind === "success" ? "text-emerald-400" : kind === "error" ? "text-red-400" : kind === "notice" ? "text-amber-300" : "text-zinc-600"}`}>{icon}</span>
              <span className={`truncate ${kind === "success" ? "log-success" : kind === "error" ? "log-error" : kind === "notice" ? "log-notice" : "text-zinc-400"}`}>{s.name}</span>
              <span className="ml-auto text-zinc-600 shrink-0">{s.conclusion || s.status}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function RawLogBlock({ text }: { text: string }) {
  // For AI messages that already contain ANSI, keep them coloured
  const lines = text.split("\n");
  return (
    <pre className="rounded-xl bg-zinc-950 border border-zinc-800 p-3 text-xs font-mono overflow-auto max-h-[320px] whitespace-pre-wrap break-words">
      {lines.map((ln, i) => {
        const kind = kindForLine(ln);
        const clean = stripAnsi(ln);
        const cls =
          kind === "thinking"
            ? "log-thinking"
            : kind === "answer"
            ? "log-answer"
            : kind === "tool"
            ? "log-tool"
            : kind === "plan"
            ? "log-plan"
            : kind === "success"
            ? "log-success"
            : kind === "warning"
            ? "log-warning"
            : kind === "error"
            ? "log-error"
            : kind === "frame"
            ? "log-frame"
            : "text-zinc-500";
        return (
          <div key={i} className={cls}>
            {clean}
          </div>
        );
      })}
    </pre>
  );
}
