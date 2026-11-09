import { NextRequest, NextResponse } from "next/server";
// Live file proxy via Cloudflare tunnel — real-time file showing.
// The runner's nish_agent.py exposes /__nish/files?path=. and /__nish/file?path=...
// This route fetches via the tunnel URL (discovered from logs or artifact) so FileExplorer
// can show files instantly as the AI creates them, not only at artifact upload end.
// Falls back to artifact hint if no tunnel.

const REPO = "Nishgamerrz/Ai-rant";
function tok() {
  const t = process.env.GITHUB_TOKEN || process.env.GH_TOKEN || "";
  if (!t) throw new Error("GITHUB_TOKEN missing");
  return t;
}

async function discoverTunnel(run: string): Promise<string | null> {
  const headers = { Authorization: `Bearer ${tok()}`, Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28" } as Record<string, string>;
  // try live log tail first (contains https://*.trycloudflare.com)
  try {
    const j = await fetch(`https://api.github.com/repos/${REPO}/actions/runs/${run}/jobs`, { headers, cache: "no-store" }).then(r => r.json()).catch(() => null);
    const jobs = j?.jobs || [];
    for (const job of jobs.slice(0, 2)) {
      try {
        const res = await fetch(`https://api.github.com/repos/${REPO}/actions/jobs/${job.id}/logs`, { headers, cache: "no-store" });
        if (!res.ok) continue;
        const txt = await res.text();
        const m = txt.match(/https:\/\/[a-zA-Z0-9-]+\.trycloudflare\.com[^\s"'<>]*/);
        if (m) return m[0].replace(/\/$/, "");
      } catch {}
    }
  } catch {}
  // fallback: try artifact zip (dist/tunnel_url.txt)
  try {
    const artRes = await fetch(`https://api.github.com/repos/${REPO}/actions/runs/${run}/artifacts`, { headers, cache: "no-store" });
    if (!artRes.ok) return null;
    const data = await artRes.json();
    const art = (data.artifacts || []).find((a: any) => String(a.name).startsWith("nish-agent"));
    if (!art) return null;
    const zipRes = await fetch(`https://api.github.com/repos/${REPO}/actions/artifacts/${art.id}/zip`, { headers, cache: "no-store" });
    if (!zipRes.ok) return null;
    const buf = Buffer.from(await zipRes.arrayBuffer());
    const JSZip = (await import("jszip")).default;
    const zip = await JSZip.loadAsync(buf);
    const cand = Object.keys(zip.files).find(k => k.endsWith("tunnel_url.txt"));
    if (!cand) return null;
    const txt = await zip.file(cand)!.async("string");
    const url = txt.trim().split(/\s+/)[0] || null;
    if (url && url.includes("trycloudflare.com")) return url.replace(/\/$/, "");
  } catch {}
  return null;
}

export async function GET(req: NextRequest) {
  try {
    const url = new URL(req.url);
    const run = url.searchParams.get("run") || url.searchParams.get("runId") || "";
    const relPath = url.searchParams.get("path") || ".";
    if (!run) return NextResponse.json({ error: "run required" }, { status: 400 });
    // discover tunnel (allow override via ?tunnel= for client that already knows)
    let tunnel = url.searchParams.get("tunnel") || "";
    if (!tunnel) {
      tunnel = (await discoverTunnel(run)) || "";
    }
    if (!tunnel) {
      return NextResponse.json({ ok: false, live: false, hint: "No live tunnel for this run — files will appear via artifact after upload. Enable tunnel for instant file streaming.", run }, { status: 200 });
    }
    let u: URL;
    try { u = new URL(tunnel); } catch { return NextResponse.json({ error: "bad tunnel_url" }, { status: 400 }); }
    if (!u.hostname.endsWith("trycloudflare.com")) return NextResponse.json({ error: "tunnel host must be *.trycloudflare.com" }, { status: 400 });

    // Decide if request is for file content or dir listing
    // If path contains a dot extension and not ending with /, try file first
    const isFileLike = relPath !== "." && !relPath.endsWith("/") && relPath.includes(".");
    // Try file first if file-like, else files
    if (isFileLike) {
      const fileUrl = `${u.origin}/__nish/file?path=${encodeURIComponent(relPath)}`;
      const r = await fetch(fileUrl, { cache: "no-store" });
      if (r.ok) {
        const ct = r.headers.get("content-type") || "";
        if (ct.includes("application/json")) {
          const j = await r.json().catch(() => null);
          if (j && j.ok === false) {
            // fallback to files listing
          } else {
            return new NextResponse(JSON.stringify(j ?? {}), { headers: { "Content-Type": ct } });
          }
        }
        const buf = Buffer.from(await r.arrayBuffer());
        // If response was JSON error with files list, handle
        const text = buf.toString("utf-8");
        if (text.startsWith('{"ok":false')) {
          // treat as not file, fallback to listing
        } else {
          return new NextResponse(buf, { headers: { "Content-Type": ct || "text/plain; charset=utf-8", "Cache-Control": "no-store" } });
        }
      }
    }
    // dir listing
    const listUrl = `${u.origin}/__nish/files?path=${encodeURIComponent(relPath)}`;
    const res = await fetch(listUrl, { cache: "no-store" });
    const text = await res.text();
    // Try JSON
    try {
      const j = JSON.parse(text);
      return NextResponse.json({ ok: true, live: true, tunnel, ...j });
    } catch {
      return new NextResponse(text, { headers: { "Content-Type": "text/plain; charset=utf-8" } });
    }
  } catch (e: any) {
    return NextResponse.json({ error: String(e?.message || e), live: false }, { status: 502 });
  }
}
