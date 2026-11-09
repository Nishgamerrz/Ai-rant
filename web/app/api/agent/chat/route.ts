import { NextRequest, NextResponse } from "next/server";

// Live proxy to the Cloudflare tunnel the agent workflow may have opened.
// The workflow writes the tunnel URL to dist/tunnel_url.txt and exposes it
// via the artifact/logs API. The Vercel app polls /api/github/logs?run=… to
// learn the URL, then POSTs user messages here. This endpoint forwards them
// to the tunnel so the running GitHub runner can answer live.
//
// If no tunnel is open, it returns a friendly message so the UI can fall back
// to polling the batch artifact (dist/agent_chat.json).

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const message = String(body.message || "").trim();
    const tunnel = String(body.tunnel_url || body.tunnel || "").trim();
    if (!message) return NextResponse.json({ error: "message required" }, { status: 400 });
    if (!tunnel) {
      return NextResponse.json({
        ok: false,
        mode: "batch",
        hint: "No live tunnel for this run. The workflow will answer in batch and you can watch the chat file at dist/agent_chat.json via the Artifacts tab. Start a new chat with Enable tunnel ✓ for live replies.",
      });
    }
    // Basic allowlist: only trycloudflare.com
    let u: URL;
    try {
      u = new URL(tunnel);
    } catch {
      return NextResponse.json({ error: "bad tunnel_url" }, { status: 400 });
    }
    if (!u.hostname.endsWith("trycloudflare.com")) {
      return NextResponse.json({ error: "tunnel host must be *.trycloudflare.com" }, { status: 400 });
    }
    const target = `${u.origin.replace(/\/$/, "")}/chat`;
    const res = await fetch(target, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
      cache: "no-store",
    });
    const text = await res.text();
    // return as-is, but wrap so UI can render colours
    return NextResponse.json({ ok: res.ok, status: res.status, reply: text.slice(0, 8000) });
  } catch (e: any) {
    return NextResponse.json({ error: String(e?.message || e) }, { status: 502 });
  }
}
