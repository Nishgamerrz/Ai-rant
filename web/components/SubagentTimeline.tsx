"use client";

import { useEffect, useMemo, useState } from "react";

type FileEdit = { path: string; operation?: string; bytes?: number; content?: string; tool?: string };
type ProviderAttempt = { provider?: string; model?: string; status?: string; reason?: string; fallback_to?: string; seconds?: number };
type SubagentCall = {
  key: string;
  id: string;
  source?: string;
  topic?: string;
  kind?: string;
  instruction?: string;
  originalInstruction?: string;
  input?: string;
  context?: string;
  provider?: string;
  providerModel?: string;
  seconds?: number;
  fileEdited?: string;
  fileEdits?: FileEdit[];
  output?: string;
  ok?: boolean;
  status?: string;
  error?: string;
  applyError?: string;
  attempts?: ProviderAttempt[];
  toolCalls?: unknown[];
  toolResults?: unknown[];
  files?: string[];
  live?: boolean;
};

type ActivityRecord = Record<string, any>;

function providerName(provider?: string, model?: string) {
  const slug = String(provider || "").toLowerCase();
  const name = slug === "bazaarlink" ? "BazaarLink" : slug === "gemini" ? "Gemini"
    : slug === "groq" ? "Groq" : provider || "Provider unknown";
  return model ? `${name} · ${model}` : name;
}

function fallbackName(attempt: ProviderAttempt) {
  const target = String(attempt.fallback_to || "");
  if (!target) return "";
  if (["bazaarlink", "gemini", "groq"].includes(target.toLowerCase())) return providerName(target);
  return String(attempt.provider || "").toLowerCase() === "groq"
    ? providerName("groq", target) : target;
}

function parseLiveLogForSubagent(tail: string): SubagentCall[] {
  const events: ActivityRecord[] = [];
  const marker = "[ai-log] ";
  for (const line of String(tail || "").split(/\r?\n/)) {
    const index = line.indexOf(marker);
    if (index < 0) continue;
    try {
      const value = JSON.parse(line.slice(index + marker.length).trim());
      if (value && typeof value === "object" && !Array.isArray(value)) events.push(value);
    } catch {
      // The active log tail may end in the middle of a JSON record.
    }
  }

  const calls: SubagentCall[] = [];
  const active = new Map<string, number>();
  let sequence = 0;
  for (const event of events) {
    if (event.stage !== "subagent") continue;
    const type = String(event.type || "");
    const taskId = String(event.task_id || event.id || "");
    if (!taskId) continue;
    const activityId = String(event.activity_id || taskId);
    if (type === "subagent_task") {
      const call: SubagentCall = {
        key: `live:${sequence++}:${taskId}`,
        id: taskId,
        topic: event.topic,
        kind: event.kind,
        instruction: event.preview || "Task instructions are stored in the run artifact.",
        provider: "",
        status: "started",
        output: "Waiting for the subagent reply and full result artifact…",
        live: true,
      };
      calls.push(call);
      active.set(activityId, calls.length - 1);
      continue;
    }
    let index = active.get(activityId);
    if (index === undefined) {
      calls.push({
        key: `live:${sequence++}:${taskId}`,
        id: taskId,
        topic: event.topic,
        kind: event.kind,
        instruction: event.preview || "Task instructions are stored in the run artifact.",
        live: true,
      });
      index = calls.length - 1;
      active.set(activityId, index);
    }
    const current = calls[index];
    if (type === "provider_attempt") {
      current.attempts = [...(current.attempts || []), event];
      if (event.status === "answered") {
        current.provider = event.provider;
        current.providerModel = event.model;
      }
      continue;
    }
    if (type === "subagent_result") {
      current.provider = event.provider || current.provider;
      current.providerModel = event.provider_model || current.providerModel;
      current.seconds = event.seconds;
      current.status = event.status || (event.ok ? "complete" : "failed");
      current.ok = event.ok;
      current.output = event.error || event.preview || "Full response is being loaded from the run artifact.";
      current.error = event.error;
      current.fileEdited = event.edited_files?.join(", ") || event.applied_to;
    }
  }
  return calls;
}

async function readTextArtifact(runId: number, artifactName: string, fileName: string): Promise<string | null> {
  try {
    const response = await fetch(
      `/api/github/artifact?run=${runId}&name=${encodeURIComponent(artifactName)}&json=${encodeURIComponent(fileName)}`,
      { cache: "no-store" },
    );
    return response.ok ? await response.text() : null;
  } catch {
    return null;
  }
}

async function readJsonArtifact(runId: number, name: string,
                                artifactName = "Roblox-Story-Short-MP4"): Promise<any | null> {
  const text = await readTextArtifact(runId, artifactName, name);
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function parseActivityArtifact(text: string): SubagentCall[] {
  const events: ActivityRecord[] = String(text || "").split(/\r?\n/).flatMap((line) => {
    try { return line.trim() ? [JSON.parse(line)] : []; } catch { return []; }
  });
  const calls = new Map<string, SubagentCall>();
  for (const event of events) {
    if (event.stage !== "subagent") continue;
    const type = String(event.type || "");
    const id = String(event.task_id || event.id || "");
    if (!id) continue;
    const key = `activity:${event.activity_id || id}`;
    const previous = calls.get(key) || { key, id, attempts: [], fileEdits: [], live: false };
    const call: SubagentCall = {
      ...previous,
      id,
      source: previous.source || (String(event.context || "").toLowerCase().includes("narration") ? "Story" : "Map / story"),
      topic: event.topic || previous.topic,
      kind: event.kind || previous.kind,
      instruction: event.instruction || previous.instruction,
      originalInstruction: event.original_instruction || previous.originalInstruction,
      input: event.input ?? previous.input,
      context: event.context || previous.context,
      provider: event.provider || previous.provider,
      providerModel: event.provider_model || event.model || previous.providerModel,
      seconds: event.seconds ?? previous.seconds,
      fileEdited: (Array.isArray(event.edited_files) ? event.edited_files.join(", ") : "")
        || event.applied_to || previous.fileEdited,
      fileEdits: Array.isArray(event.file_edits) ? event.file_edits : previous.fileEdits,
      output: event.text ?? event.output ?? previous.output,
      ok: event.ok ?? previous.ok,
      status: event.status || previous.status,
      error: event.error || previous.error,
      applyError: event.apply_error || previous.applyError,
      attempts: previous.attempts || [],
      toolCalls: Array.isArray(event.tool_calls) ? event.tool_calls : previous.toolCalls,
      toolResults: Array.isArray(event.tool_results) ? event.tool_results : previous.toolResults,
      files: Array.isArray(event.files) ? event.files : previous.files,
      live: false,
    };
    if (type === "subagent_task") {
      call.status = event.status || "started";
    } else if (type === "provider_attempt") {
      call.attempts = [...(previous.attempts || []), event];
      if (event.status === "answered") {
        call.provider = event.provider;
        call.providerModel = event.model;
      }
    } else if (type === "subagent_result") {
      call.output = event.text ?? event.output ?? "";
      call.ok = Boolean(event.ok);
      call.status = event.status || (event.ok ? "complete" : "failed");
      call.provider = event.provider || call.provider;
      call.providerModel = event.provider_model || call.providerModel;
      call.seconds = event.seconds ?? call.seconds;
    }
    calls.set(key, call);
  }
  return Array.from(calls.values());
}

function artifactCalls(groups: Array<{ name: string; data: any }>): SubagentCall[] {
  const calls = new Map<string, SubagentCall>();
  for (const group of groups) {
    if (!group.data || typeof group.data !== "object") continue;
    const source = group.name.startsWith("story_") ? "Story" : "Map";
    const context = String(group.data.context || "");
    const fileKey = `${source.toLowerCase()}:`;
    const tasks = Array.isArray(group.data.tasks) ? group.data.tasks : [];
    for (const task of tasks) {
      if (!task || typeof task !== "object") continue;
      const id = String(task.id || `task-${calls.size}`);
      const key = `${fileKey}${id}`;
      const previous = calls.get(key);
      calls.set(key, {
        key,
        id,
        source,
        topic: task.topic || previous?.topic,
        kind: task.kind || previous?.kind,
        instruction: task.instruction || previous?.instruction || "",
        input: task.input ?? previous?.input ?? "",
        context: context || previous?.context || "",
        status: previous?.status || "waiting",
        attempts: previous?.attempts || [],
      });
    }

    const results = Array.isArray(group.data.results) ? group.data.results : [];
    for (const result of results) {
      if (!result || typeof result !== "object") continue;
      const id = String(result.id || `task-${calls.size}`);
      const key = `${fileKey}${id}`;
      const previous = calls.get(key);
      const edits: FileEdit[] = Array.isArray(result.file_edits) ? result.file_edits : [];
      const paths = Array.isArray(result.edited_files) ? result.edited_files
        : edits.map((edit: FileEdit) => edit.path).filter(Boolean);
      const provider = result.provider || previous?.provider || "";
      calls.set(key, {
        key,
        id,
        source,
        topic: result.topic || previous?.topic,
        kind: result.kind || previous?.kind,
        instruction: result.instruction || previous?.instruction || "",
        originalInstruction: result.original_instruction,
        input: result.input ?? previous?.input ?? "",
        context: result.context || previous?.context || context,
        provider,
        providerModel: result.provider_model || result.model || previous?.providerModel,
        seconds: result.seconds,
        fileEdited: paths.join(", ") || result.applied_to || previous?.fileEdited,
        fileEdits: edits,
        output: result.text ?? result.output ?? previous?.output ?? "",
        ok: result.ok !== false,
        status: result.status || (result.ok === false ? "failed" : "complete"),
        error: result.error,
        applyError: result.apply_error,
        attempts: result.provider_attempts || previous?.attempts || [],
        toolCalls: result.tool_calls || [],
        toolResults: result.tool_results || [],
        live: false,
      });
    }
  }
  return Array.from(calls.values());
}

function DetailBlock({ title, children, tone = "text-zinc-300" }: {
  title: string;
  children: React.ReactNode;
  tone?: string;
}) {
  return (
    <section className="rounded-xl bg-zinc-950 border border-zinc-800 p-3">
      <div className="text-[10px] font-semibold tracking-widest text-zinc-500 uppercase">{title}</div>
      <pre className={`mt-2 whitespace-pre-wrap break-words text-xs font-mono leading-relaxed ${tone}`}>{children}</pre>
    </section>
  );
}

export function SubagentTimeline({ runId, kind, liveLog }: {
  runId: number | null;
  kind: "agent" | "rbx";
  liveLog?: string;
}) {
  const [calls, setCalls] = useState<SubagentCall[]>([]);
  const [liveCalls, setLiveCalls] = useState<SubagentCall[]>([]);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const parsedLive = useMemo(() => parseLiveLogForSubagent(liveLog || ""), [liveLog]);

  useEffect(() => {
    setLiveCalls(parsedLive);
  }, [parsedLive]);

  useEffect(() => {
    setCalls([]);
    setLiveCalls([]);
    setExpanded(null);
    if (!runId) return;
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      try {
        if (kind === "agent") {
          const response = await fetch(
            `/api/github/artifact?run=${runId}&name=nish-agent-${runId}&json=agent_tools.jsonl`,
            { cache: "no-store" },
          );
          const text = response.ok ? await response.text() : "";
          const parsed = text.split(/\r?\n/).flatMap((line) => {
            try { return line.trim() ? [JSON.parse(line)] : []; } catch { return []; }
          });
          const subs: SubagentCall[] = parsed.filter((item: any) => item?.tool === "subagent").map((item: any, index: number) => {
            const result = item.output || {};
            return {
              key: `agent:${item.input?.id || index}`,
              id: item.input?.id || `sub-${index + 1}`,
              topic: item.input?.topic,
              kind: item.input?.kind || "subagent",
              instruction: item.input?.instruction || item.input?.prompt || "",
              input: item.input?.input || "",
              provider: result.provider || "",
              providerModel: result.model || "",
              seconds: result.seconds,
              fileEdited: result.applied_to,
              output: result.text || result.output || "",
              ok: result.ok,
              status: result.ok === false ? "failed" : "complete",
              error: result.error,
              live: false,
            };
          });
          if (!cancelled) setCalls(subs);
        } else {
          const activityText = await readTextArtifact(
            runId, "Roblox-Story-Short-AI-Activity", "ai_activity.jsonl");
          let parsed = activityText ? parseActivityArtifact(activityText) : [];
          if (parsed.length === 0) {
            // Keep older runs readable if they only have the original task/result files.
            const names = [`story_subagent_tasks.json`, `story_subagent_results.json`,
                           `subagent_tasks.json`, `subagent_results.json`];
            const data = await Promise.all(names.map(async (name) => ({
              name,
              data: await readJsonArtifact(runId, name),
            })));
            parsed = artifactCalls(data);
          }
          if (!cancelled) setCalls(parsed);
        }
      } catch {
        if (!cancelled) setCalls([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    const interval = setInterval(load, 8000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [runId, kind]);

  const display = calls.length ? calls : liveCalls;

  if (!runId) {
    return (
      <div className="rounded-2xl border border-dashed border-zinc-800 bg-zinc-900/20 p-6 text-center">
        <div className="text-xs font-semibold tracking-widest text-zinc-600 uppercase">Subagent</div>
        <div className="text-sm text-zinc-500 mt-1">Select a run to inspect delegated tasks</div>
      </div>
    );
  }

  if (loading && display.length === 0) {
    return (
      <div className="rounded-2xl bg-zinc-900 border border-zinc-800 p-4 flex items-center gap-3">
        <span className="h-4 w-4 border-2 border-zinc-700 border-t-zinc-400 rounded-full animate-spin" />
        <span className="text-xs text-zinc-500">Loading complete subagent work…</span>
      </div>
    );
  }

  if (display.length === 0) {
    return (
      <div className="rounded-2xl bg-zinc-900 border border-zinc-800 p-4">
        <div className="text-xs font-semibold tracking-wide text-zinc-300">Subagent · no delegated tasks yet</div>
        <div className="text-xs text-zinc-600 mt-2 leading-relaxed">
          This view shows the exact task and input, provider attempts, full returned text, complete text-file edits, tool results and errors. It never truncates the saved answer.
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-2xl bg-zinc-900 border border-zinc-800 overflow-hidden shadow-soft">
      <div className="px-3.5 py-3 flex items-center gap-2 border-b border-zinc-800 bg-zinc-900">
        <span className="h-2 w-2 rounded-full bg-violet-400" />
        <span className="text-xs font-semibold tracking-wide text-zinc-200">Subagent work</span>
        <span className="text-[11px] px-2 py-0.5 rounded-full bg-violet-600 text-white font-medium">{display.length} {display.length === 1 ? "task" : "tasks"}</span>
        {display.some((item) => item.live) && <span className="text-[10px] text-amber-300">live preview</span>}
        <span className="ml-auto text-[10px] text-zinc-500 hidden sm:inline">Full instructions · outputs · edits · provider · timing · errors</span>
      </div>
      <div className="divide-y divide-zinc-800/60 max-h-[620px] overflow-auto">
        {display.map((call) => {
          const isOpen = expanded === call.key;
          const attemptList = call.attempts || [];
          const editList = call.fileEdits || [];
          const output = call.output || "";
          const editedFiles = call.fileEdited || editList.map((edit) => edit.path).join(", ");
          return (
            <article key={call.key} className="p-3.5 hover:bg-zinc-800/15">
              <button type="button" onClick={() => setExpanded(isOpen ? null : call.key)} className="w-full text-left flex items-start gap-3">
                <span className={`mt-0.5 h-6 w-6 rounded-lg grid place-items-center shrink-0 border text-xs font-bold ${
                  call.ok === false || call.status === "failed" ? "bg-red-950/30 border-red-900 text-red-300"
                    : call.live || call.status === "started" || call.status === "waiting"
                      ? "bg-amber-950/30 border-amber-900 text-amber-300"
                      : "bg-emerald-950/20 border-emerald-900/50 text-emerald-300"
                }`}>
                  {call.ok === false || call.status === "failed" ? "×"
                    : call.live || call.status === "started" || call.status === "waiting" ? "…" : "✓"}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    {call.source && <span className="text-[10px] text-zinc-500">{call.source}</span>}
                    <span className="text-xs font-semibold text-zinc-200">{call.id}</span>
                    <span className="px-1.5 py-0.5 rounded-full bg-zinc-800 border border-zinc-700 text-[10px] text-zinc-400">{call.topic || "general"} · {call.kind || "task"}</span>
                    {call.provider && <span className="px-1.5 py-0.5 rounded-full bg-zinc-950 border border-zinc-800 text-[10px] text-zinc-400">{providerName(call.provider, call.providerModel)}</span>}
                    {call.seconds !== undefined && <span className="text-[10px] text-zinc-500">{call.seconds}s</span>}
                    {call.status && <span className="text-[10px] uppercase tracking-wide text-zinc-600">{call.status}</span>}
                  </div>
                  <div className="mt-1 text-xs text-zinc-300 leading-relaxed line-clamp-2">{call.instruction || "Task instruction is in the activity artifact."}</div>
                  {editedFiles && <div className="mt-1 text-[11px] text-emerald-400">Edited: {editedFiles}</div>}
                  {output && <div className="mt-1 text-[11px] text-zinc-500 line-clamp-2">{output}</div>}
                  {!output && call.error && <div className="mt-1 text-[11px] text-red-300">{call.error}</div>}
                </div>
                <span className="text-zinc-600 text-xs">{isOpen ? "−" : "+"}</span>
              </button>

              {isOpen && (
                <div className="mt-3 pl-9 space-y-3">
                  {call.instruction && <DetailBlock title="Full task / instructions">{call.instruction}</DetailBlock>}
                  {call.originalInstruction && <DetailBlock title="Original instruction before size guard">{call.originalInstruction}</DetailBlock>}
                  {call.input && <DetailBlock title="Input supplied">{call.input}</DetailBlock>}
                  {call.context && <DetailBlock title="Run context">{call.context}</DetailBlock>}
                  {call.files && call.files.length > 0 && (
                    <DetailBlock title="File rules supplied">{call.files.join("\n")}</DetailBlock>
                  )}
                  {attemptList.length > 0 && (
                    <DetailBlock title="Provider attempts">
                      {attemptList.map((attempt, index) => {
                        const fallback = attempt.fallback_to ? ` → ${fallbackName(attempt)}` : "";
                        const reason = attempt.reason ? ` — ${attempt.reason}` : "";
                        return `${index + 1}. ${providerName(attempt.provider, attempt.model)}: ${attempt.status || "unknown"}${fallback}${reason}${attempt.seconds !== undefined ? ` (${attempt.seconds}s)` : ""}`;
                      }).join("\n")}
                    </DetailBlock>
                  )}
                  {output && <DetailBlock title="Complete subagent response">{output}</DetailBlock>}
                  {editList.map((edit, index) => (
                    <DetailBlock key={`${edit.path}-${index}`} title={`${edit.operation || "Edited"} file · ${edit.path}`}>
                      {edit.content ?? `Binary or large file · ${edit.bytes ?? "unknown"} bytes`}
                    </DetailBlock>
                  ))}
                  {call.toolCalls && call.toolCalls.length > 0 && (
                    <DetailBlock title="Subagent-authored tool calls">{JSON.stringify(call.toolCalls, null, 2)}</DetailBlock>
                  )}
                  {call.toolResults && call.toolResults.length > 0 && (
                    <DetailBlock title="Tool results">{JSON.stringify(call.toolResults, null, 2)}</DetailBlock>
                  )}
                  {(call.error || call.applyError) && (
                    <DetailBlock title="Error / result" tone="text-red-300">
                      {[call.error, call.applyError].filter(Boolean).join("\n")}
                    </DetailBlock>
                  )}
                  {call.live && <div className="text-[11px] text-amber-300">Full prompt and output appear when the artifact uploads.</div>}
                </div>
              )}
            </article>
          );
        })}
      </div>
    </div>
  );
}
