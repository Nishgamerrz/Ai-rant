// Server-only helpers — GITHUB_TOKEN never leaves the server.
// Vercel env var: GITHUB_TOKEN (create in Vercel dashboard → Settings → Environment Variables)
export const REPO = "Nishgamerrz/Ai-rant";
export const AGENT_WORKFLOW = "agent.yml";
export const SHORT_WORKFLOW = "main.yml";

function token(): string {
  const t = process.env.GITHUB_TOKEN || process.env.GH_TOKEN || "";
  if (!t) throw new Error("GITHUB_TOKEN is not set in Vercel. Add it in Vercel → Settings → Environment Variables → GITHUB_TOKEN (a fine-grained PAT with Actions: read/write, Contents: read).");
  return t;
}

function ghHeaders() {
  return {
    Authorization: `Bearer ${token()}`,
    Accept: "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "Content-Type": "application/json",
  } as Record<string, string>;
}

export async function dispatchWorkflow(workflow: string, inputs: Record<string, string | boolean>) {
  const res = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${workflow}/dispatches`, {
    method: "POST",
    headers: ghHeaders(),
    body: JSON.stringify({ ref: "main", inputs: Object.fromEntries(Object.entries(inputs).map(([k, v]) => [k, String(v)])) }),
  });
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`dispatch ${workflow} failed ${res.status}: ${txt}`);
  }
  return { ok: true };
}

export async function listRuns(workflow: string, per_page = 12) {
  const res = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${workflow}/runs?per_page=${per_page}`, {
    headers: ghHeaders(),
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`listRuns ${res.status}: ${await res.text()}`);
  const data = await res.json();
  return data.workflow_runs as any[];
}

export async function getRun(runId: string) {
  const res = await fetch(`https://api.github.com/repos/${REPO}/actions/runs/${runId}`, { headers: ghHeaders(), cache: "no-store" });
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return res.json();
}

export async function getJobs(runId: string) {
  const res = await fetch(`https://api.github.com/repos/${REPO}/actions/runs/${runId}/jobs`, { headers: ghHeaders(), cache: "no-store" });
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return res.json();
}

export async function getArtifacts(runId: string) {
  const res = await fetch(`https://api.github.com/repos/${REPO}/actions/runs/${runId}/artifacts`, { headers: ghHeaders(), cache: "no-store" });
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return res.json();
}

// Ansi stripping is *not* done server-side — we keep colours and let the client render them.
export function ghAuthOk() {
  return Boolean(process.env.GITHUB_TOKEN || process.env.GH_TOKEN);
}
