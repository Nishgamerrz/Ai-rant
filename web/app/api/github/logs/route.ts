import { NextRequest, NextResponse } from "next/server";
// Logs + artifacts proxy — keeps GITHUB_TOKEN server-side.
// The UI polls this while a workflow is running so colours, "plan next/previous"
// badges and the AI's thinking appear live.

const REPO = "Nishgamerrz/Ai-rant";

function token() {
  const t = process.env.GITHUB_TOKEN || process.env.GH_TOKEN || "";
  if (!t) throw new Error("GITHUB_TOKEN missing");
  return t;
}

export async function GET(req: NextRequest) {
  try {
    const url = new URL(req.url);
    const runId = url.searchParams.get("run") || url.searchParams.get("run_id") || "";
    if (!runId) return NextResponse.json({ error: "run id required" }, { status: 400 });
    const tok = token();
    const headers = { Authorization: `Bearer ${tok}`, Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28" } as Record<string, string>;

    // 1) run + jobs to get step states & timing
    const [runRes, jobsRes] = await Promise.all([
      fetch(`https://api.github.com/repos/${REPO}/actions/runs/${runId}`, { headers, cache: "no-store" }),
      fetch(`https://api.github.com/repos/${REPO}/actions/runs/${runId}/jobs`, { headers, cache: "no-store" }),
    ]);
    if (!runRes.ok) return NextResponse.json({ error: `run ${runRes.status} ${await runRes.text()}` }, { status: 502 });
    if (!jobsRes.ok) return NextResponse.json({ error: `jobs ${jobsRes.status} ${await jobsRes.text()}` }, { status: 502 });
    const run = await runRes.json();
    const jobs = await jobsRes.json();

    // Flatten steps with colour-friendly model load markers
    const steps = (jobs.jobs || []).flatMap((j: any) =>
      (j.steps || []).map((s: any) => ({
        name: s.name,
        status: s.status,
        conclusion: s.conclusion,
        started_at: s.started_at,
        completed_at: s.completed_at,
        number: s.number,
        job: j.name,
      }))
    );

    // 2) artifacts (chat, tools, workspace, previews)
    const artRes = await fetch(`https://api.github.com/repos/${REPO}/actions/runs/${runId}/artifacts`, { headers, cache: "no-store" });
    const artifacts = artRes.ok ? await artRes.json() : { artifacts: [] };

    // 3) try to fetch a tiny log snippet via the check runs (no raw log zip needed)
    // Raw logs need a zip download which is heavy to proxy on every poll; we use jobs/steps + artifacts.
    // If the UI needs full logs, it can fetch via /api/github/run/[id]/logs.zip separately.
    return NextResponse.json({
      run: {
        id: run.id,
        status: run.status,
        conclusion: run.conclusion,
        html_url: run.html_url,
        created_at: run.created_at,
        updated_at: run.updated_at,
        head_branch: run.head_branch,
      },
      steps,
      artifacts: (artifacts.artifacts || []).map((a: any) => ({
        id: a.id,
        name: a.name,
        size_in_bytes: a.size_in_bytes,
        expired: a.expired,
        archive_download_url: a.archive_download_url,
      })),
      // For the chat UI: if the agent already uploaded agent_chat.json, the UI can fetch it via artifact download
      // (proxied through /api/github/artifact/[id]).
      hint: "Poll this endpoint every 4s while status is not completed. Fetch artifact zip via /api/github/artifact?id=...",
    });
  } catch (e: any) {
    return NextResponse.json({ error: String(e?.message || e) }, { status: 502 });
  }
}
