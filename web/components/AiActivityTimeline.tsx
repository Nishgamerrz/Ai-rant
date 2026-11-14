"use client";

import { useEffect, useMemo, useState } from "react";
import { liveSubagentActivityEvents } from "@/lib/liveSubagentLog.mjs";

type ActivityEvent = {
  schema_version?: number;
  timestamp?: string;
  type?: string;
  stage?: string;
  channel?: string;
  activity_id?: string;
  tag?: string;
  label?: string;
  task_id?: string;
  id?: string;
  kind?: string;
  topic?: string;
  provider?: string;
  model?: string;
  provider_model?: string;
  status?: string;
  reason?: string;
  error?: string;
  seconds?: number;
  fallback_to?: string;
  preview?: string;
  characters?: number;
  prompt?: string;
  prompt_messages?: Array<{ role?: string; content?: string }>;
  public_rationale?: string;
  public_status?: string;
  input?: string;
  context?: string;
  original_instruction?: string;
  instruction?: string;
  output?: string;
  text?: string;
  cleaned_text?: string;
  provider_attempts?: ActivityEvent[];
  file_edits?: Array<{ path: string; operation?: string; bytes?: number; content?: string }>;
  edited_files?: string[];
  applied_to?: string;
  apply_error?: string;
  tool_calls?: unknown[];
  tool_results?: unknown[];
  files?: string[];
  [key: string]: unknown;
};

function parseJsonLines(text: string): ActivityEvent[] {
  return text.split(/\r?\n/).flatMap((line) => {
    if (!line.trim()) return [];
    try {
      const value = JSON.parse(line);
      return value && typeof value === "object" && !Array.isArray(value)
        ? [value as ActivityEvent]
        : [];
    } catch {
      return [];
    }
  });
}

function parseLiveLog(text: string): ActivityEvent[] {
  const marker = "[ai-log] ";
  const events: ActivityEvent[] = [];
  const progressIndexes = new Map<string, number>();
  for (const line of text.split(/\r?\n/)) {
    const index = line.indexOf(marker);
    if (index < 0) continue;
    try {
      const value = JSON.parse(line.slice(index + marker.length).trim());
      if (!value || typeof value !== "object" || Array.isArray(value)) continue;
      const event = value as ActivityEvent;
      if (event.type === "model_progress") {
        const key = `${event.activity_id || event.label || "model"}:${event.channel || "output"}`;
        const previous = progressIndexes.get(key);
        if (previous !== undefined) events[previous] = event;
        else {
          progressIndexes.set(key, events.length);
          events.push(event);
        }
      } else {
        events.push(event);
      }
    } catch {
      // Ignore runner lines and incomplete structured records.
    }
  }
  // The activity JSONL file is uploaded after later workflow steps. Until then,
  // expose the safe, newline-framed console stream instead of leaving the helper
  // at a static "working" row.
  events.push(...(liveSubagentActivityEvents(text) as ActivityEvent[]));
  return events;
}

function providerName(provider?: string, model?: string) {
  const key = String(provider || "").toLowerCase();
  const name = key === "bazaarlink" ? "BazaarLink" : key === "gemini" ? "Gemini"
    : key === "groq" ? "Groq" : key === "ollama" ? "Ollama" : provider || "AI";
  return model ? `${name} · ${model}` : name;
}

function fallbackName(attempt: Pick<ActivityEvent, "provider" | "fallback_to">) {
  const target = String(attempt.fallback_to || "");
  if (!target) return "";
  if (["bazaarlink", "gemini", "groq"].includes(target.toLowerCase())) return providerName(target);
  return String(attempt.provider || "").toLowerCase() === "groq"
    ? providerName("groq", target) : target;
}

function eventTitle(event: ActivityEvent) {
  const type = String(event.type || "AI activity");
  const label = event.label || event.task_id || event.id || event.stage || "AI";
  if (type === "provider_attempt") {
    const state = event.status === "answered" ? "answered"
      : event.status === "fallback" ? `failed${event.fallback_to ? ` · falling back to ${fallbackName(event)}` : " · no fallback available"}`
      : event.status === "skipped" ? "skipped" : "failed";
    return `${providerName(event.provider, event.model)} ${state}`;
  }
  if (type === "topic_cleanup") return `${label} · ${event.status === "cleaned" ? "cleaned" : "kept as typed"}`;
  if (type === "narration_finalized") return `Narration source · ${event.status || "complete"}`;
  if (type === "subagent_tool") return `Sub-agent tool · ${event.public_status || event.status || "activity"}`;
  if (type === "subagent_progress") return `Subagent task ${event.task_id || event.id || ""} · ${event.status || "working"}`;
  if (type === "subagent_task") return `Subagent task ${event.task_id || event.id || ""} · ${event.status || "started"}`;
  if (type === "subagent_result") return `Subagent task ${event.task_id || event.id || ""} · ${event.status || (event.ok ? "complete" : "failed")}`;
  if (type === "subagent_answer") return `Sub-agent ${event.task_id || ""} · public result streaming`;
  if (type === "model_progress") return `${label} · ${event.channel === "thinking" ? "private processing active" : "answer progress"}`;
  if (type === "model_response") return `${label} · completed`;
  if (type === "model_error") return `${label} · failed`;
  if (type === "subagent_guidance") return `${label} · file rules supplied`;
  return `${label} · ${type.replaceAll("_", " ")}`;
}

function eventKey(event: ActivityEvent, index: number) {
  return [event.timestamp, event.type, event.task_id || event.id, event.provider, event.status, index]
    .filter((part) => part !== undefined && part !== "").join(":");
}

function TextSection({ title, children, tone = "text-zinc-300" }: {
  title: string;
  children: React.ReactNode;
  tone?: string;
}) {
  return (
    <section className="rounded-xl bg-zinc-950 border border-zinc-800 p-3">
      <div className="text-[10px] font-semibold tracking-widest text-zinc-500 uppercase">{title}</div>
      <div className={`mt-2 whitespace-pre-wrap break-words text-xs font-mono leading-relaxed ${tone}`}>{children}</div>
    </section>
  );
}

export function AiActivityTimeline({ runId, liveLog, runStatus }: {
  runId: number | null;
  liveLog?: string;
  runStatus?: string;
}) {
  const [artifactEvents, setArtifactEvents] = useState<ActivityEvent[]>([]);
  const [artifactReady, setArtifactReady] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const liveEvents = useMemo(() => parseLiveLog(liveLog || ""), [liveLog]);

  useEffect(() => {
    setArtifactEvents([]);
    setArtifactReady(false);
    setExpanded(null);
    if (!runId) return;
    let cancelled = false;
    const load = async () => {
      try {
        const response = await fetch(
          `/api/github/artifact?run=${runId}&name=Roblox-Story-Short-AI-Activity&json=ai_activity.jsonl`,
          { cache: "no-store" },
        );
        if (!response.ok) return;
        const text = await response.text();
        const parsed = parseJsonLines(text);
        if (!cancelled && parsed.length) {
          setArtifactEvents(parsed);
          setArtifactReady(true);
        }
      } catch {
        // The activity artifact does not exist until the Short output bundle uploads.
      }
    };
    load();
    const interval = setInterval(load, 8000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [runId]);

  const events = artifactEvents.length ? artifactEvents : liveEvents;
  const liveOnly = !artifactReady && liveEvents.length > 0;

  if (!runId) {
    return (
      <div className="rounded-2xl border border-dashed border-zinc-800 bg-zinc-900/20 p-6 text-center">
        <div className="text-sm font-medium text-zinc-300">Select a run to inspect AI activity</div>
      </div>
    );
  }

  return (
    <div className="rounded-2xl bg-zinc-900 border border-zinc-800 overflow-hidden shadow-soft">
      <div className="px-4 py-3 flex items-center gap-2.5 border-b border-zinc-800 bg-zinc-900">
        <span className={`h-2 w-2 rounded-full ${runStatus?.includes("in_progress") ? "bg-amber-400 animate-pulse" : "bg-violet-400"}`} />
        <div>
          <div className="text-xs font-semibold tracking-wide text-zinc-200">AI activity</div>
          <div className="text-[11px] text-zinc-500 mt-0.5">
            {events.length} event{events.length === 1 ? "" : "s"}
            {liveOnly ? " · live previews" : artifactReady ? " · full artifact" : " · waiting for AI output"}
          </div>
        </div>
        <span className="ml-auto text-[10px] text-zinc-600">Provider attempts · prompts · answers · edits</span>
      </div>
      <div className="px-4 py-2.5 border-b border-zinc-800/70 bg-zinc-950/60 text-[11px] text-zinc-500">
        Only AI activity is shown here. Runner commands, installation output and curl/network chatter are hidden.
        Complete prompts and responses load from the run artifact when it uploads.
      </div>

      {events.length ? (
        <div className="divide-y divide-zinc-800/60 max-h-[720px] overflow-auto">
          {events.map((event, index) => {
            const key = eventKey(event, index);
            const isOpen = expanded === key;
            const output = typeof event.output === "string" ? event.output
              : typeof event.text === "string" ? event.text
                : typeof event.cleaned_text === "string" ? event.cleaned_text : "";
            const promptMessages = Array.isArray(event.prompt_messages) ? event.prompt_messages : [];
            const attempts = Array.isArray(event.provider_attempts) ? event.provider_attempts : [];
            const fileEdits = Array.isArray(event.file_edits) ? event.file_edits : [];
            const hasDetails = Boolean(event.instruction || event.input || event.context || event.prompt
              || event.preview || output || event.public_rationale || event.public_status || event.reason || event.error || fileEdits.length || attempts.length
              || promptMessages.length || event.tool_calls?.length || event.tool_results?.length);
            return (
              <article key={key} className="p-3.5 hover:bg-zinc-800/15">
                <button
                  type="button"
                  onClick={() => setExpanded(isOpen ? null : key)}
                  className="w-full flex items-start gap-3 text-left"
                >
                  <span className={`mt-0.5 h-6 min-w-6 px-1 rounded-lg grid place-items-center border text-[10px] font-bold ${
                    event.status === "failed" || event.status === "kept_input"
                      ? "bg-red-950/30 border-red-900/60 text-red-300"
                      : event.status === "fallback" || event.status === "started" || event.status === "streaming"
                        ? "bg-amber-950/30 border-amber-900/60 text-amber-300"
                        : "bg-violet-950/30 border-violet-900/50 text-violet-300"
                  }`}>
                    {event.status === "failed" || event.status === "kept_input" ? "!"
                      : event.status === "fallback" || event.status === "started" || event.status === "streaming" ? "…" : "AI"}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-xs font-semibold text-zinc-200">{event.tag || eventTitle(event)}</span>
                      {event.tag && <span className="text-[11px] font-medium text-zinc-300">{eventTitle(event)}</span>}
                      {event.provider && <span className="px-1.5 py-0.5 rounded-full border border-zinc-700 bg-zinc-950 text-[10px] text-zinc-400">{providerName(event.provider, event.model || event.provider_model)}</span>}
                      {event.seconds !== undefined && <span className="text-[10px] text-zinc-500">{event.seconds}s</span>}
                      {event.timestamp && <time className="text-[10px] text-zinc-600">{new Date(event.timestamp).toLocaleTimeString()}</time>}
                    </div>
                    {(event.preview || event.public_status || event.reason || event.error) && (
                      <div className={`mt-1.5 text-xs leading-relaxed break-words ${event.reason || event.error ? "text-amber-200" : "text-zinc-400"}`}>
                        {event.preview || event.public_status || event.reason || event.error}
                        {event.fallback_to && <span className="text-amber-300"> · fallback: {fallbackName(event)}</span>}
                        {event.characters !== undefined && <span className="ml-2 text-[10px] text-zinc-600">{event.characters.toLocaleString()} chars</span>}
                      </div>
                    )}
                  </div>
                  {hasDetails && <span className="text-zinc-600 text-xs">{isOpen ? "−" : "+"}</span>}
                </button>

                {isOpen && hasDetails && (
                  <div className="mt-3 pl-9 space-y-3">
                    {event.instruction && <TextSection title="Task / instructions">{event.instruction}</TextSection>}
                    {event.original_instruction && <TextSection title="Original task instructions">{event.original_instruction}</TextSection>}
                    {event.input && <TextSection title="Input supplied to the AI">{event.input}</TextSection>}
                    {event.context && <TextSection title="Task context">{event.context}</TextSection>}
                    {event.prompt && <TextSection title="Prompt sent">{event.prompt}</TextSection>}
                    {promptMessages.map((message, messageIndex) => (
                      <TextSection key={messageIndex} title={`Prompt · ${message.role || "message"}`}>
                        {message.content || ""}
                      </TextSection>
                    ))}
                    {output && <TextSection title={event.type === "topic_cleanup" ? "Provider response"
                      : event.type === "narration_finalized" ? "Final narration used downstream"
                        : "Complete AI response"}>{output}</TextSection>}
                    {event.public_rationale && <TextSection title="Public rationale">{event.public_rationale}</TextSection>}
                    {event.public_status && <TextSection title="Safe sub-agent progress">{event.public_status}</TextSection>}
                    {event.cleaned_text && event.cleaned_text !== output && (
                      <TextSection title="Cleaned prompt passed to the workflow">{event.cleaned_text}</TextSection>
                    )}
                    {fileEdits.map((edit, editIndex) => (
                      <TextSection key={`${edit.path}-${editIndex}`} title={`${edit.operation || "Edited"} file · ${edit.path}`}>
                        {edit.content ?? `Binary or large file · ${edit.bytes ?? "unknown"} bytes`}
                      </TextSection>
                    ))}
                    {event.files && <TextSection title="File rules supplied">{event.files.join("\n")}</TextSection>}
                    {attempts.length > 0 && (
                      <TextSection title="Provider attempts">
                        {attempts.map((attempt, attemptIndex) => {
                          const suffix = attempt.reason ? ` — ${attempt.reason}` : "";
                          const fallback = attempt.fallback_to ? ` → ${fallbackName(attempt)}` : "";
                          return `${attemptIndex + 1}. ${providerName(attempt.provider, attempt.model)}: ${attempt.status || "unknown"}${fallback}${suffix}`;
                        }).join("\n")}
                      </TextSection>
                    )}
                    {event.tool_calls && event.tool_calls.length > 0 && (
                      <TextSection title="Subagent-authored tool calls">{JSON.stringify(event.tool_calls, null, 2)}</TextSection>
                    )}
                    {event.tool_results && event.tool_results.length > 0 && (
                      <TextSection title="Tool results">{JSON.stringify(event.tool_results, null, 2)}</TextSection>
                    )}
                    {(event.reason || event.error || event.apply_error) && (
                      <TextSection title="Result / error" tone="text-amber-200">
                        {[event.reason, event.error, event.apply_error].filter(Boolean).join("\n")}
                      </TextSection>
                    )}
                  </div>
                )}
              </article>
            );
          })}
        </div>
      ) : (
        <div className="px-6 py-10 text-center">
          <div className="text-sm font-medium text-zinc-300">No AI output recorded yet</div>
          <div className="mt-1 text-xs leading-relaxed text-zinc-600">
            As soon as a provider or model responds, its AI-tagged activity appears here. Setup and runner command output stay hidden.
          </div>
        </div>
      )}
    </div>
  );
}
