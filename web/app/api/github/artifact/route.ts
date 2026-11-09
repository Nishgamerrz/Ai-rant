import { NextRequest, NextResponse } from "next/server";

// Proxies a single artifact zip download so the browser never sees GITHUB_TOKEN.
// Query: ?id=ARTIFACT_ID  or ?run=RUN_ID&name=artifact-name
// If `json` param is set (e.g. json=agent_chat.json) we unzip and return that file as JSON instead of the zip.

const REPO = "Nishgamerrz/Ai-rant";

function tok() {
  const t = process.env.GITHUB_TOKEN || process.env.GH_TOKEN || "";
  if (!t) throw new Error("GITHUB_TOKEN missing");
  return t;
}

export async function GET(req: NextRequest) {
  try {
    const url = new URL(req.url);
    const id = url.searchParams.get("id");
    const run = url.searchParams.get("run");
    const name = url.searchParams.get("name");
    const wantJson = url.searchParams.get("json") || "";
    const headers = { Authorization: `Bearer ${tok()}`, Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28" } as Record<string, string>;

    let artifactId = id;
    if (!artifactId && run && name) {
      const res = await fetch(`https://api.github.com/repos/${REPO}/actions/runs/${run}/artifacts`, { headers, cache: "no-store" });
      if (!res.ok) return NextResponse.json({ error: await res.text() }, { status: 502 });
      const data = await res.json();
      const found = (data.artifacts || []).find((a: any) => a.name === name);
      if (!found) return NextResponse.json({ error: `no artifact named ${name}` }, { status: 404 });
      artifactId = String(found.id);
    }
    if (!artifactId) return NextResponse.json({ error: "provide ?id= or ?run=&name=" }, { status: 400 });

    // Download zip as buffer
    const zipRes = await fetch(`https://api.github.com/repos/${REPO}/actions/artifacts/${artifactId}/zip`, {
      headers: { ...headers, Accept: "application/vnd.github+json" },
      cache: "no-store",
    });
    if (!zipRes.ok) return NextResponse.json({ error: `artifact zip ${zipRes.status} ${await zipRes.text()}` }, { status: 502 });
    const buf = Buffer.from(await zipRes.arrayBuffer());

    if (!wantJson) {
      return new NextResponse(buf, {
        headers: {
          "Content-Type": "application/zip",
          "Content-Disposition": `attachment; filename="artifact-${artifactId}.zip"`,
          "Cache-Control": "no-store",
        },
      });
    }

    // Extract one file from zip without writing to disk — JSZip
    const JSZip = (await import("jszip")).default;
    const zip = await JSZip.loadAsync(buf);
    // find file matching wantJson (exact or suffix)
    let file: any = zip.file(wantJson);
    if (!file) {
      // search by suffix
      const all = Object.keys(zip.files);
      const cand = all.find((k) => k.endsWith(wantJson) || k.endsWith("/" + wantJson));
      if (cand) file = zip.file(cand);
    }
    if (!file) {
      const names = Object.keys(zip.files).slice(0, 20).join(", ");
      return NextResponse.json({ error: `${wantJson} not in zip. files: ${names}` }, { status: 404 });
    }
    const text = await file.async("string");
    // try json parse, else return text
    try {
      const data = JSON.parse(text);
      return NextResponse.json(data);
    } catch {
      return new NextResponse(text, { headers: { "Content-Type": "text/plain; charset=utf-8" } });
    }
  } catch (e: any) {
    return NextResponse.json({ error: String(e?.message || e) }, { status: 502 });
  }
}
