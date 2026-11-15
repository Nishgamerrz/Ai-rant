const ANSI_RE = /\x1b\[[0-9;]*m/g;
const SAFE_PROGRESS_RE = /\[[^\]]+\]\s+(reasoning is active; private model thoughts are hidden\.|preparing the structured result; raw JSON is hidden\.)/i;

/** Map framed Ollama console markers to fixed, public-only chat activity. */
export function safeOllamaProgressStatus(line) {
  const match = String(line || "").replace(ANSI_RE, "").match(SAFE_PROGRESS_RE);
  if (!match) return "";
  return match[1].startsWith("reasoning is active")
    ? "Local Ollama is processing the plan; only safe progress is shown."
    : "Local Ollama is preparing its structured plan; raw JSON stays hidden until validation.";
}
