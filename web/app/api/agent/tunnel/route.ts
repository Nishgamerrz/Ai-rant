import { NextRequest, NextResponse } from "next/server";

// Direct API mode — no tunnel. Kept for backwards-compatibility.
export async function GET(req: NextRequest) {
  const run = new URL(req.url).searchParams.get("run");
  if (!run) return NextResponse.json({ error: "run required" }, { status: 400 });
  return NextResponse.json({ tunnel_url: null, mode: "direct", hint: "Direct API mode — no Cloudflare tunnel. Live log tail via /api/github/logs?logs=1." });
}
