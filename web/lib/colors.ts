// Shared with the workflow's console_style.py palette — logs are rendered with
// the same hues the workflow prints so "AI thinking" looks the same in Vercel.
// We also parse ANSI SGR codes if the raw log is fetched (logs endpoint strips
// them, but job step logs contain them).

export type LineKind = "thinking" | "answer" | "label" | "notice" | "success" | "warning" | "error" | "tool" | "plan" | "thought" | "frame" | "aka" | "muted";

const ANSI_MAP: Record<string, LineKind> = {
  "37": "thinking",
  "36": "answer",
  "94": "label",
  "33": "notice",
  "32": "success",
  "93": "warning",
  "91": "error",
  "35": "tool",
  "34": "plan",
  "90": "thought",
};

export function kindForLine(line: string): LineKind {
  const t = line.trimStart();
  if (t.startsWith("┌─") || t.startsWith("└") || t.startsWith("│")) return "frame";
  if (t.includes(" thinking") || t.includes("[thinking]")) return "thinking";
  if (t.startsWith("[agent]") || t.includes(" answer ▸")) return "answer";
  if (t.startsWith("[nish-agent]") || t.includes("NishAgent")) return "label";
  if (t.includes("✓") || t.includes("finished in")) return "success";
  if (t.includes("warning") || t.includes("still")) return "warning";
  if (t.includes("error") || t.includes("failed") || t.includes("blocked")) return "error";
  if (t.startsWith("[tool") || t.includes("search_web") || t.includes("create_file")) return "tool";
  if (t.startsWith("[web search]") || t.includes("plan:")) return "plan";
  return "muted";
}

// Very small ANSI → span converter for raw logs that contain \x1b[...m
export function ansiToHtml(raw: string): string {
  // escape
  let s = raw.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  // \x1b[0m resets, \x1b[33m etc.
  s = s.replace(/\x1b\[0m/g, "</span>");
  s = s.replace(/\x1b\[1m/g, "<span class='font-bold'>");
  for (const [code, kind] of Object.entries(ANSI_MAP)) {
    const cls = `log-${kind}`;
    s = s.replaceAll(`\x1b[${code}m`, `<span class="${cls}">`);
  }
  // any remaining SGR
  s = s.replace(/\x1b\[[0-9;]*m/g, "<span>");
  return s;
}

export function stripAnsi(s: string): string {
  return s.replace(/\x1b\[[0-9;]*m/g, "");
}
