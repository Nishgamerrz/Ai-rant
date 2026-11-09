import { NextRequest, NextResponse } from "next/server";
import { AGENT_WORKFLOW, listRuns, SHORT_WORKFLOW } from "@/lib/github";

export async function GET(req: NextRequest) {
  try {
    const url = new URL(req.url);
    const kind = url.searchParams.get("kind") || "agent";
    const workflow = kind === "rbx" || kind === "short" ? SHORT_WORKFLOW : AGENT_WORKFLOW;
    const per = Number(url.searchParams.get("per_page") || "16");
    const runs = await listRuns(workflow, Math.min(30, Math.max(1, per)));
    // Trim to what the UI needs — keep it fast
    const slim = runs.map((r: any) => ({
      id: r.id,
      name: r.name,
      display_title: r.display_title,
      status: r.status,
      conclusion: r.conclusion,
      html_url: r.html_url,
      created_at: r.created_at,
      updated_at: r.updated_at,
      run_number: r.run_number,
      head_branch: r.head_branch,
      actor: r.actor ? { login: r.actor.login, avatar_url: r.actor.avatar_url } : null,
    }));
    return NextResponse.json({ workflow, runs: slim });
  } catch (e: any) {
    return NextResponse.json({ error: String(e?.message || e) }, { status: 502 });
  }
}
