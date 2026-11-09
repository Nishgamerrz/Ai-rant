import { NextRequest, NextResponse } from "next/server";
import { AGENT_WORKFLOW, SHORT_WORKFLOW, dispatchWorkflow } from "@/lib/github";

// POST { kind: "agent"|"rbx", model, prompt, story_topic, character_usernames, duration_seconds, map_detail, voice_style, world_theme, enable_tunnel }
export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const kind = (body.kind || "agent") as string;
    if (kind === "rbx" || kind === "short" || body.story_topic) {
      // RBX short — mirrors main.yml inputs exactly
      const inputs: Record<string, string> = {
        story_topic: String(body.story_topic || body.prompt || "").slice(0, 600),
        character_usernames: String(body.character_usernames || ""),
        duration_seconds: String(body.duration_seconds || "120"),
        map_detail: String(body.map_detail || "dense"),
        model_quality: String(body.model_quality || body.model || "hard"),
        voice_style: String(body.voice_style || "male"),
        world_theme: String(body.world_theme || ""),
      };
      if (!inputs.story_topic) return NextResponse.json({ error: "story_topic required" }, { status: 400 });
      await dispatchWorkflow(SHORT_WORKFLOW, inputs);
      return NextResponse.json({ ok: true, workflow: SHORT_WORKFLOW, inputs });
    }
    // Agent
    const prompt = String(body.prompt || body.story_topic || "").trim();
    if (!prompt) return NextResponse.json({ error: "prompt required" }, { status: 400 });
    const model = String(body.model_quality || body.model || "hard");
    const enable_tunnel = String(body.enable_tunnel ?? body.enableTunnel ?? "false");
    await dispatchWorkflow(AGENT_WORKFLOW, {
      prompt,
      model_quality: model,
      enable_tunnel: enable_tunnel === "true" ? "true" : "false",
      task_hint: String(body.task_hint || kind || ""),
    });
    return NextResponse.json({ ok: true, workflow: AGENT_WORKFLOW, prompt, model_quality: model });
  } catch (e: any) {
    const msg = String(e?.message || e);
    if (msg.includes("409") || msg.toLowerCase().includes("already")) {
      return NextResponse.json({ error: "Workflow already dispatching — GitHub rate-limits to one dispatch per ~20s. Please wait and the new run will appear in the sidebar.", details: msg }, { status: 409 });
    }
    const status = msg.includes("GITHUB_TOKEN") ? 500 : 502;
    return NextResponse.json({ error: msg }, { status });
  }
}
