const ANSI_COLOR = /\x1b\[[0-9;]*m/g;
const PRIVATE_MARKERS = [
  "chain of thought", "chain-of-thought", "private reasoning", "hidden reasoning",
  "internal monologue", "scratchpad", "let me think step by step",
  "here is my reasoning", "here's my reasoning", "my thought process",
];

function safeConsoleText(value) {
  const text = String(value ?? "")
    .replace(/\bBearer\s+[A-Za-z0-9._~+/-]{12,}=?/gi, "Bearer [REDACTED]")
    .replace(/\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|AIza[0-9A-Za-z_-]{30,}|sk-[A-Za-z0-9_-]{20,}|(?:AKIA|ASIA)[A-Z0-9]{16})\b/g, "[REDACTED]")
    .replace(/(\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret)\b["']?\s*[:=]\s*["']?)[^\s,}"']+/gi, "$1[REDACTED]");
  const lowered = text.toLowerCase();
  if (text.length > 320 || PRIVATE_MARKERS.some((marker) => lowered.includes(marker))) return "";
  return text;
}

function markerBody(line, marker) {
  const index = line.indexOf(marker);
  if (index < 0) return null;
  const body = line.slice(index + marker.length).trim();
  const separator = body.indexOf("·");
  if (separator < 0) return null;
  return { id: body.slice(0, separator).trim(), detail: body.slice(separator + 1).trim() };
}

function answerChunk(line) {
  const framed = markerBody(line, "[subagent answer chunk]");
  if (!framed || !framed.id) return null;
  try {
    const text = JSON.parse(framed.detail);
    return typeof text === "string" ? { ...framed, text } : null;
  } catch {
    return null;
  }
}

function progressStatus(message) {
  const text = String(message || "");
  if (/\b(?:failed|skipped)\b/i.test(text)) return "failed";
  if (/\bcomplete\b/i.test(text)) return "complete";
  if (/\bstarted\b/i.test(text)) return "started";
  if (/still preparing|waiting for its next safe result segment/i.test(text)) return "working";
  return "streaming";
}

/**
 * Reconstruct safe sub-agent progress, tool activity and framed public answers
 * from human-readable, newline-terminated Actions console lines.
 *
 * @param {string} tail
 * @returns {Array<{key:string,id:string,status:string,publicStatus:string,output:string,live:boolean,attempts:Array,toolActivity:Array}>}
 */
export function parseLiveSubagentLog(tail) {
  const calls = [];
  const active = new Map();
  let sequence = 0;

  const ensure = (id, { restart = false } = {}) => {
    const previousIndex = active.get(id);
    const previous = previousIndex === undefined ? null : calls[previousIndex];
    if (previous && !(restart && ["complete", "failed"].includes(previous.status))) return previous;
    const call = {
      key: `live:${sequence++}:${id}`,
      id,
      status: "working",
      publicStatus: "",
      output: "",
      live: true,
      attempts: [],
      toolActivity: [],
    };
    calls.push(call);
    active.set(id, calls.length - 1);
    return call;
  };

  for (const rawLine of String(tail || "").split(/\r?\n/)) {
    const line = rawLine.replace(ANSI_COLOR, "");
    const progress = markerBody(line, "[subagent progress]");
    if (progress?.id) {
      const state = progressStatus(progress.detail);
      const call = ensure(progress.id, { restart: state === "started" });
      call.status = state;
      call.publicStatus = safeConsoleText(progress.detail);
      continue;
    }

    const tool = markerBody(line, "[subagent tool]");
    if (tool?.id) {
      const call = ensure(tool.id);
      const detail = safeConsoleText(tool.detail);
      const match = detail.match(/^([a-z0-9_-]+)\s+(started|succeeded|finished|failed)\b(.*)$/i);
      call.toolActivity.push({
        tool: match?.[1] || "sub-agent tool",
        status: match?.[2]?.toLowerCase() || "activity",
        publicStatus: detail,
      });
      if (detail) call.publicStatus = detail;
      continue;
    }

    const provider = markerBody(line, "[subagent provider]");
    if (provider?.id) {
      const call = ensure(provider.id);
      call.attempts.push({ provider: provider.detail, status: "updated" });
      call.publicStatus = safeConsoleText(provider.detail) || call.publicStatus;
      continue;
    }

    const header = markerBody(line, "[subagent answer]");
    if (header?.id && /public result \(streaming\):?$/i.test(header.detail)) {
      const call = ensure(header.id);
      call.status = "streaming";
      call.publicStatus = "Public result is streaming; internal reasoning is hidden.";
      continue;
    }

    const chunk = answerChunk(line);
    if (chunk) {
      const call = ensure(chunk.id);
      call.status = "streaming";
      call.publicStatus = "Public result is streaming; internal reasoning is hidden.";
      call.output += chunk.text;
    }
  }
  return calls;
}

/** @param {string} tail @returns {Array<Record<string, unknown>>} */
export function liveSubagentActivityEvents(tail) {
  const calls = parseLiveSubagentLog(tail);
  const events = [];
  for (const call of calls) {
    if (call.publicStatus) {
      events.push({
        type: "subagent_progress",
        stage: "subagent",
        tag: "[subagent progress]",
        task_id: call.id,
        status: call.status,
        public_status: call.publicStatus,
      });
    }
    for (const tool of call.toolActivity) {
      events.push({
        type: "subagent_tool",
        stage: "subagent",
        tag: "[subagent tool]",
        task_id: call.id,
        status: tool.status,
        public_status: tool.publicStatus,
      });
    }
    if (call.output) {
      events.push({
        type: "subagent_answer",
        stage: "subagent",
        tag: "[subagent answer]",
        task_id: call.id,
        status: call.status,
        text: call.output,
        public_status: "Public sub-agent result streaming",
      });
    }
    for (const attempt of call.attempts) {
      events.push({
        type: "provider_attempt",
        stage: "subagent",
        task_id: call.id,
        provider: attempt.provider,
        status: attempt.status,
      });
    }
  }
  return events;
}
