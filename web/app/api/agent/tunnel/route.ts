import { NextRequest, NextResponse } from "next/server";

// Helper: given a run id, try to retrieve the Cloudflare tunnel URL the workflow
// wrote to dist/tunnel_url.txt (via the artifact). The UI calls this to obtain
// the live URL without having to download the whole zip on every poll.
const REPO = "Nishgamerrz/Ai-rant";
function tok() {
  const t = process.env.GITHUB_TOKEN || process.env.GH_TOKEN || "";
  if (!t) throw new Error("GITHUB_TOKEN missing");
  return t;
}
export async function GET(req: NextRequest) {
  try {
    const run = new URL(req.url).searchParams.get("run");
    if (!run) return NextResponse.json({ error: "run required" }, { status: 400 });
    const headers = { Authorization: `Bearer ${tok()}`, Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28" } as Record<string, string>;
    // First try live log (instant, before artifact upload) — handle 302 redirect
    try {
      const jRes = await fetch(`https://api.github.com/repos/${REPO}/actions/runs/${run}/jobs`, { headers, cache: "no-store" });
      if (jRes.ok) {
        const j = await jRes.json();
        for (const job of (j.jobs || []).slice(0,2)) {
          try {
            const res = await fetch(`https://api.github.com/repos/${REPO}/actions/jobs/${job.id}/logs`, { headers, cache: "no-store", redirect: "manual" });
            let txt: string | null = null;
            if (res.status === 302 || res.status === 301) {
              const loc = res.headers.get("location");
              if (loc) {
                const r2 = await fetch(loc, { cache: "no-store" });
                if (r2.ok) txt = await r2.text();
              }
            } else if (res.ok) txt = await res.text();
            if (txt) {
              const m = txt.match(/https:\/\/[a-zA-Z0-9-]+\.trycloudflare\.com[^\s"'<>]*/);
              if (m) return NextResponse.json({ tunnel_url: m[0].replace(/\/$/, ""), source: "live-log" });
            }
          } catch {}
        }
      }
    } catch {}
    const res = await fetch(`https://api.github.com/repos/${REPO}/actions/runs/${run}/artifacts`, { headers, cache: "no-store" });
    if (!res.ok) return NextResponse.json({ error: await res.text() }, { status: 502 });
    const data = await res.json();
    const art = (data.artifacts || []).find((a: any) => String(a.name).startsWith("nish-agent"));
    if (!art) return NextResponse.json({ tunnel_url: null });
    // Download and extract tunnel_url.txt — reuse artifact route logic inline to stay fast
    const zipRes = await fetch(`https://api.github.com/repos/${REPO}/actions/artifacts/${art.id}/zip`, { headers, cache: "no-store" });
    if (!zipRes.ok) return NextResponse.json({ tunnel_url: null });
    const buf = Buffer.from(await zipRes.arrayBuffer());
    const JSZip = (await import("jszip")).default;
    const zip = await JSZip.loadAsync(buf);
    const cand = Object.keys(zip.files).find((k) => k.endsWith("tunnel_url.txt"));
    if (!cand) return NextResponse.json({ tunnel_url: null });
    const txt = await zip.file(cand)!.async("string");
    const url = txt.trim().split(/\s+/)[0] || null;
    return NextResponse.json({ tunnel_url: url });
  } catch (e: any) {
    return NextResponse.json({ error: String(e?.message || e) }, { status: 502 });
  }
}
