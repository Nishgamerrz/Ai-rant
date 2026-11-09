import { NextRequest, NextResponse } from "next/server";

const REPO = "Nishgamerrz/Ai-rant";

function tok() {
  const t = process.env.GITHUB_TOKEN || process.env.GH_TOKEN || "";
  if (!t) throw new Error("GITHUB_TOKEN missing — add it in Vercel → Settings → Environment Variables");
  return t;
}

export async function DELETE(req: NextRequest) {
  try {
    const url = new URL(req.url);
    const runId = url.searchParams.get("run") || url.searchParams.get("run_id") || url.searchParams.get("id");
    if (!runId) return NextResponse.json({ error: "run id required (?run=123)" }, { status: 400 });
    const headers = {
      Authorization: `Bearer ${tok()}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
    } as Record<string, string>;
    const res = await fetch(`https://api.github.com/repos/${REPO}/actions/runs/${runId}`, {
      method: "DELETE",
      headers,
    });
    if (res.status === 204) return NextResponse.json({ ok: true, deleted: runId });
    const txt = await res.text();
    // GitHub returns 403 if token lacks Actions write, 404 if not found
    return NextResponse.json({ error: txt, status: res.status }, { status: 502 });
  } catch (e: any) {
    return NextResponse.json({ error: String(e?.message || e) }, { status: 502 });
  }
}

export async function POST(req: NextRequest) {
  // alias for DELETE via POST for clients that can't send DELETE
  return DELETE(req);
}
