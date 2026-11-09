import { NextRequest, NextResponse } from "next/server";

// Direct API mode — no Cloudflare tunnel. Chat is now via single persistent plan streaming through GitHub logs.
// This endpoint is kept for backwards-compatibility but always reports direct mode.
export async function POST(req: NextRequest) {
  try {
    const body = await req.json().catch(() => ({}));
    const message = String(body.message || "").trim();
    if (!message) return NextResponse.json({ error: "message required" }, { status: 400 });
    return NextResponse.json({
      ok: false,
      mode: "direct",
      hint: "Direct API mode — no tunnel. Start a New workflow with your prompt. The AI then works in one persistent plan until the workflow dies, streaming thinking, tools, and files via GitHub API polling (every 3.5s). The message you sent is not delivered mid-run; create a new run for a new prompt.",
      received: message.slice(0, 400),
    });
  } catch (e: any) {
    return NextResponse.json({ error: String(e?.message || e) }, { status: 502 });
  }
}
