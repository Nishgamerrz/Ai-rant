const ANSI_RE = /\x1b\[[0-9;]*m/g;
const PRIVATE_MARKERS = [
  "chain of thought", "chain-of-thought", "private reasoning", "hidden reasoning",
  "internal monologue", "scratchpad", "let me think step by step",
  "here is my reasoning", "here's my reasoning", "my thought process",
];

function safePublicText(value, limit) {
  let text = String(value || "").replace(/\s+/g, " ").trim();
  text = text
    .replace(/\bBearer\s+[A-Za-z0-9._~+/-]{12,}=?/gi, "Bearer [REDACTED]")
    .replace(/\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|AIza[0-9A-Za-z_-]{30,}|sk-[A-Za-z0-9_-]{20,}|ya29\.[A-Za-z0-9_-]{20,}|(?:AKIA|ASIA)[A-Z0-9]{16})\b/g, "[REDACTED]")
    .replace(/(\b(?:api[_-]?key|[A-Z0-9_-]*_API|access[_-]?token|refresh[_-]?token|password|secret)\b["']?\s*[:=]\s*["']?)[^\s,}"']+/gi, "$1[REDACTED]");
  const lowered = text.toLowerCase();
  if (!text || text.length > limit || /^(?:\{|\[)/.test(text)
      || PRIVATE_MARKERS.some((marker) => lowered.includes(marker))) return "";
  return text;
}

function stripLogPrefix(line) {
  return String(line || "").replace(ANSI_RE, "")
    .replace(/^\d{4}-\d\d-\d\dT[^\s]+\s+/, "").trimEnd();
}

/**
 * Read only the model-authored public status/rationale/answer fields already
 * allowlisted by ollama_stream.py. The private Ollama `thinking` channel is never parsed.
 */
export function parseLiveModelActivity(logTail) {
  let summary = "";
  let summaryKind = "";
  const updateSummary = (value, kind) => {
    const candidate = safePublicText(value, 320);
    if (candidate) {
      summary = candidate;
      summaryKind = kind;
    }
  };
  let inSummaryBox = false;
  const summaryLines = [];
  const answers = new Map();
  let activeAnswer = null;

  const publishAnswer = (complete) => {
    if (!activeAnswer) return;
    const text = safePublicText(activeAnswer.text, 4000);
    if (text) answers.set(activeAnswer.label, {
      label: activeAnswer.label,
      text,
      streaming: !complete,
    });
    activeAnswer = null;
  };

  for (const rawLine of String(logTail || "").split("\n")) {
    const line = stripLogPrefix(rawLine);
    if (!line) continue;

    if (/MODEL REASONING\s*[—–-]\s*PUBLIC SUMMARY/i.test(line)) {
      publishAnswer(false);
      inSummaryBox = true;
      summaryLines.length = 0;
      continue;
    }

    if (inSummaryBox) {
      if (/^\s*└/.test(line)) {
        updateSummary(summaryLines.join(" "), "rationale");
        inSummaryBox = false;
        summaryLines.length = 0;
        continue;
      }
      const framed = line.match(/^\s*│\s?(.*)$/);
      if (framed) {
        if (framed[1]) summaryLines.push(framed[1]);
        updateSummary(summaryLines.join(" "), "rationale");
        continue;
      }
      // A fresh console frame means the summary box ended without its final border.
      inSummaryBox = false;
      summaryLines.length = 0;
    }

    const framedLine = line.match(/^\s*│\s?(.*)$/);
    const body = framedLine ? framedLine[1] : line;
    const answerStart = body.match(/^\[(nish-agent[^\]]*)\]\s+answer\s+▸\s*(.*)$/i);
    if (answerStart) {
      publishAnswer(false);
      activeAnswer = { label: answerStart[1].trim(), text: answerStart[2] || "",
        framed: Boolean(framedLine) };
      if (!activeAnswer.framed) publishAnswer(true);
      else {
        const text = safePublicText(activeAnswer.text, 4000);
        if (text) answers.set(activeAnswer.label, {
          label: activeAnswer.label, text, streaming: true,
        });
      }
      continue;
    }

    if (activeAnswer) {
      if (/^\s*└/.test(line)) {
        publishAnswer(true);
        continue;
      }
      if (framedLine) {
        // The console wraps long public answers onto additional │-framed lines.
        activeAnswer.text += `${activeAnswer.text ? " " : ""}${framedLine[1]}`;
        const text = safePublicText(activeAnswer.text, 4000);
        if (text) answers.set(activeAnswer.label, {
          label: activeAnswer.label, text, streaming: true,
        });
        continue;
      }
      publishAnswer(true);
    }

    const agentProgress = line.match(/\[agent progress\]\s*(.+)$/i);
    const publicField = body.match(/\b(public status|public rationale)\s*▸\s*(.+)$/i);
    if (agentProgress) {
      updateSummary(agentProgress[1], "status");
    } else if (publicField) {
      updateSummary(publicField[2],
        publicField[1].toLowerCase() === "public rationale" ? "rationale" : "status");
    }
  }

  if (activeAnswer) publishAnswer(false);
  if (inSummaryBox) updateSummary(summaryLines.join(" "), "rationale");

  return { summary, summaryKind, answers: [...answers.values()] };
}
