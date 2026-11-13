"use client";

const AI_STAGE = /ai|prompt|story|narration|subagent|sub-agent|map|world|camera|short|mp4|lighting|avatar|speech/i;
const ROUTINE_STAGE = /checkout|set up|setup|install|download|cache|preflight|npm|pip|apt|upload|copy|reclaim|publish|post /i;

export function LogViewer({ steps, runStatus }: {
  steps: any[];
  runStatus: string;
  logTail?: string;
}) {
  // This panel deliberately exposes only meaningful AI/pipeline stage status.
  // The raw job tail contains echoed shell commands, env blocks, curl and package
  // installation output; those belong to GitHub diagnostics, not the AI log view.
  const relevantSteps = (steps || []).filter((step: any) => {
    const name = String(step.name || "");
    return AI_STAGE.test(name) && !ROUTINE_STAGE.test(name) && name !== "Complete job";
  });
  const active = relevantSteps.find((step: any) => step.status === "in_progress");
  const failed = relevantSteps.filter((step: any) => step.conclusion === "failure");

  return (
    <section className="rounded-2xl bg-zinc-900 border border-zinc-800 overflow-hidden shadow-soft">
      <div className="px-4 py-3 flex items-center gap-3 border-b border-zinc-800">
        <div className="h-6 w-6 rounded-lg bg-violet-600/15 border border-violet-800/30 grid place-items-center text-[11px] text-violet-300">AI</div>
        <div>
          <div className="text-xs font-semibold tracking-wide text-zinc-200">Short workflow status</div>
          <div className="text-[11px] text-zinc-500 mt-0.5">{relevantSteps.length} relevant stages</div>
        </div>
        <span className={`ml-auto text-[10px] px-2 py-1 rounded-full border font-medium ${
          runStatus.includes("success") ? "bg-emerald-950/40 border-emerald-900 text-emerald-300"
            : runStatus.includes("failure") ? "bg-red-950/30 border-red-900 text-red-300"
              : runStatus.includes("in_progress") ? "bg-amber-950/30 border-amber-900 text-amber-300"
                : "bg-zinc-800 border-zinc-700 text-zinc-400"
        }`}>{runStatus || "pending"}</span>
      </div>
      <div className="px-4 py-2.5 border-b border-zinc-800/70 bg-zinc-950/60 text-[11px] text-zinc-500">
        AI prompts, answers and subagent edits are shown below. Shell commands, environment dumps, setup, install and curl output are hidden.
      </div>
      {active && (
        <div className="px-4 py-3 flex items-center gap-2 text-xs text-amber-200">
          <span className="h-1.5 w-1.5 rounded-full bg-amber-400 animate-pulse" />
          <span>Current stage: {active.name}</span>
        </div>
      )}
      {failed.length > 0 && (
        <div className="px-4 py-2 border-t border-zinc-800/70 text-xs text-red-300">
          Failed AI/pipeline stage{failed.length === 1 ? "" : "s"}: {failed.map((step: any) => step.name).join(", ")}
        </div>
      )}
      {!active && failed.length === 0 && relevantSteps.length > 0 && (
        <div className="px-4 py-3 text-xs text-zinc-500">Stage status is available; open AI Activity below for the full prompts and returned text.</div>
      )}
    </section>
  );
}
