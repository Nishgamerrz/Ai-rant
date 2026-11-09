import { NextRequest, NextResponse } from "next/server";

// Direct API mode — no Cloudflare tunnel. Files are shown via artifact polling (direct GitHub API), not via tunnel.
// This endpoint is kept for backwards-compatibility; it now just reports direct mode.
export async function GET(req: NextRequest) {
  const url = new URL(req.url);
  const run = url.searchParams.get("run") || url.searchParams.get("runId") || "";
  if (!run) return NextResponse.json({ error: "run required" }, { status: 400 });
  return NextResponse.json({
    ok: false,
    live: false,
    mode: "direct",
    hint: "Direct API mode — no tunnel. Files stream via artifact polling every 8s (GitHub API). The persistent plan stays as one box until workflow dies.",
    run,
  });
}
