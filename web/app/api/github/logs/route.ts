import { NextRequest, NextResponse } from "next/server";
// Logs + artifacts proxy — keeps GITHUB_TOKEN server-side.
// The UI polls this while a workflow is running so colours, plan next/previous
// badges and the AI's thinking appear live.
// Now also supports ?logs=1 to return the live job-log tail through GitHub.

const REPO = "Nishgamerrz/Ai-rant";

function token() {
  const t = process.env.GITHUB_TOKEN || process.env.GH_TOKEN || "";
  if (!t) throw new Error("GITHUB_TOKEN missing");
  return t;
}

async function fetchJobLogTail(jobId: number, tok: string, maxChars = 48000): Promise<string | null> {
  try {
    const headers = { Authorization: `Bearer ${tok}`, Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28" } as Record<string, string>;
    // This endpoint 302s to an Azure blob (productionresultssa.../job-logs.txt).
    // In Vercel we can follow, but handle manual redirect for robustness (sandbox blocks Azure).
    const res = await fetch(`https://api.github.com/repos/${REPO}/actions/jobs/${jobId}/logs`, {
      headers,
      cache: "no-store",
      redirect: "manual",
    });
    let text: string | null = null;
    if (res.status === 302 || res.status === 301) {
      const loc = res.headers.get("location");
      if (!loc) return null;
      try {
        const r2 = await fetch(loc, { cache: "no-store" });
        if (!r2.ok) return null;
        text = await r2.text();
      } catch {
        return null;
      }
    } else if (res.ok) {
      text = await res.text();
    } else {
      return null;
    }
    if (!text) return null;
    if (text.length <= maxChars) return text;
    return text.slice(-maxChars);
  } catch {
    return null;
  }
}

export async function GET(req: NextRequest) {
  try {
    const url = new URL(req.url);
    const runId = url.searchParams.get("run") || url.searchParams.get("run_id") || "";
    if (!runId) return NextResponse.json({ error: "run id required" }, { status: 400 });
    const wantLogs = url.searchParams.get("logs") === "1" || url.searchParams.get("include_logs") === "1";
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

    // 3) optional live log tail (heavy - only when ?logs=1)
    let logTail: string | null = null;
    if (wantLogs && jobs.jobs?.length) {
      // Prefer the in_progress or most recent job
      const targetJobs = (jobs.jobs as any[])
        .slice()
        .sort((a, b) => {
          const rank = (s: string) => (s === "in_progress" ? 0 : s === "queued" ? 1 : 2);
          return rank(a.status) - rank(b.status);
        })
        .slice(0, 2); // fetch up to 2 jobs (usually 1)
      for (const j of targetJobs) {
        const tail = await fetchJobLogTail(j.id, tok);
        if (tail) {
          logTail = tail;
          break;
        }
      }
    }

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
      logTail: logTail || undefined,
      hint: "Poll this endpoint while the workflow runs. Fetch artifacts via /api/github/artifact?id=...; add ?logs=1 for the live GitHub job-log tail.",
    });
  } catch (e: any) {
    return NextResponse.json({ error: String(e?.message || e) }, { status: 502 });
  }
}
