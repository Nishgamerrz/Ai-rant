"use client";

export function LogViewer({ steps, runStatus, logTail }: { steps: any[]; runStatus: string; logTail?: string }) {
  const tail = (logTail || "").slice(-9000);
  if (!steps?.length && !tail) {
    return (
      <div className="rounded-2xl bg-zinc-900/50 border border-zinc-800 p-6 text-center">
        <div className="h-8 w-8 rounded-xl bg-zinc-800 grid place-items-center mx-auto">
          <span className="h-2 w-2 rounded-full bg-zinc-600 animate-pulse-subtle" />
        </div>
        <div className="text-sm font-medium text-zinc-300 mt-3">Waiting for workflow</div>
        <div className="text-xs text-zinc-600 mt-1">Steps will appear as the runner starts</div>
      </div>
    );
  }
  if (!steps?.length && tail) {
    return (
      <div className="space-y-3">
        <div className="rounded-2xl bg-zinc-900 border border-zinc-800 overflow-hidden">
          <div className="h-9 px-3.5 flex items-center gap-2 border-b border-zinc-800">
            <span className="h-2 w-2 rounded-full bg-amber-500 animate-pulse" />
            <span className="text-xs font-semibold tracking-wide text-zinc-200">Live log</span>
            <span className="ml-auto text-[11px] text-zinc-600">{(logTail!.length/1024).toFixed(1)} KB</span>
          </div>
          <RawLogBlock text={tail} />
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-2xl bg-zinc-900 border border-zinc-800 overflow-hidden shadow-soft">
      <div className="h-9 px-3.5 flex items-center gap-2.5 border-b border-zinc-800 bg-zinc-900">
        <div className="h-6 w-6 rounded-lg bg-zinc-800 grid place-items-center">
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M3 5.5h6M3 8.5h4" stroke="#a1a1aa" strokeWidth="1.2" strokeLinecap="round"/><rect x="1.5" y="1.5" width="9" height="9" rx="1.5" stroke="#27272a" strokeWidth="1"/></svg>
        </div>
        <span className="text-xs font-semibold tracking-wide text-zinc-200">Execution</span>
        <span className={`ml-1 text-[11px] px-2 py-0.5 rounded-full font-medium border ${runStatus.includes("success") ? "bg-emerald-950/50 border-emerald-900 text-emerald-300" : runStatus.includes("failure") ? "bg-red-950/30 border-red-900 text-red-300" : runStatus.includes("in_progress") ? "bg-amber-950/30 border-amber-900 text-amber-300" : "bg-zinc-800 border-zinc-700 text-zinc-400"}`}>
          {runStatus || "pending"}
        </span>
      </div>
      {tail && (
        <div className="border-b border-zinc-800 bg-zinc-950/50">
          <div className="h-7 px-3 flex items-center gap-2 text-[11px] font-medium text-zinc-500">
            <span className="h-1.5 w-1.5 rounded-full bg-amber-500 animate-pulse" /> Live runner log tail — {(tail.length/1024).toFixed(1)} KB
            <span className="ml-auto text-zinc-600">thinking streams here before artifact</span>
          </div>
          <div className="max-h-[260px] overflow-auto">
            <RawLogBlock text={tail.slice(-6000)} />
          </div>
        </div>
      )}
      <div className="divide-y divide-zinc-800/60 max-h-[320px] overflow-auto">
        {steps.map((s: any, i: number) => {
          const isSuccess = s.conclusion === "success";
          const isFailed = s.conclusion === "failure";
          const isRunning = s.status === "in_progress" || s.status === "queued";
          return (
            <div key={i} className="flex items-center gap-3 px-3.5 py-2.5 hover:bg-zinc-800/40 transition-colors">
              <span className={`h-6 w-6 rounded-lg grid place-items-center shrink-0 border text-[11px] font-bold ${
                isSuccess ? "bg-emerald-950/50 border-emerald-900/50 text-emerald-400" :
                isFailed ? "bg-red-950/30 border-red-900/50 text-red-400" :
                isRunning ? "bg-amber-950/30 border-amber-900/50 text-amber-300" :
                "bg-zinc-800 border-zinc-700 text-zinc-500"
              }`}>
                {isSuccess ? "✓" : isFailed ? "×" : isRunning ? "◐" : "○"}
              </span>
              <span className={`text-xs truncate font-medium ${isSuccess ? "text-zinc-300" : isFailed ? "text-red-300" : isRunning ? "text-amber-200" : "text-zinc-500"}`}>{s.name}</span>
              <span className="ml-auto text-[11px] font-medium tracking-wide text-zinc-600 shrink-0 uppercase">{s.conclusion || s.status}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function RawLogBlock({ text }: { text: string }) {
  const lines = text.split("\n");
  const kindFor = (ln: string) => {
    const l = ln.toLowerCase();
    if (l.includes("thinking") || l.includes("▸")) return "thinking";
    if (l.includes("answer") || l.includes("assistant")) return "answer";
    if (l.includes("tool") || l.includes("gemini")) return "tool";
    if (l.includes("plan")) return "plan";
    if (l.includes("success") || l.includes("✓")) return "success";
    if (l.includes("warning")) return "warning";
    if (l.includes("error") || l.includes("failed") || l.includes("✗")) return "error";
    return "muted";
  };
  return (
    <pre className="rounded-2xl bg-zinc-950 border border-zinc-800 p-4 text-xs font-mono overflow-auto max-h-[360px] whitespace-pre-wrap break-words leading-relaxed">
      {lines.map((ln, i) => {
        const k = kindFor(ln);
        const cls = k === "thinking" ? "text-zinc-500" : k === "answer" ? "text-cyan-300" : k === "tool" ? "text-violet-300" : k === "plan" ? "text-blue-300" : k === "success" ? "text-emerald-400" : k === "error" ? "text-red-400" : "text-zinc-600";
        return <div key={i} className={cls}>{ln}</div>;
      })}
    </pre>
  );
}
