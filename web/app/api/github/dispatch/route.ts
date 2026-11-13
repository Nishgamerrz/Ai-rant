import { NextRequest, NextResponse } from "next/server";
import { AGENT_WORKFLOW, SHORT_WORKFLOW, dispatchWorkflow } from "@/lib/github";
import { makeChatToken, makeDispatchId } from "@/lib/agentChat";

// POST { kind: "agent"|"rbx", model, prompt, story_topic, character_usernames, duration_seconds, map_detail, voice_style, world_theme }
export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const kind = (body.kind || "agent") as string;
    if (kind === "rbx" || kind === "short" || body.story_topic) {
      // RBX short — mirrors main.yml inputs exactly
      const inputs: Record<string, string> = {
        story_topic: String(body.story_topic || body.prompt || "").slice(0, 600),
        character_usernames: String(body.character_usernames || ""),
        duration_seconds: String(body.duration_seconds || "150"),
        map_detail: String(body.map_detail || "dense"),
        model_quality: String(body.model_quality || body.model || "hard"),
        voice_style: String(body.voice_style || "thin_male"),
        world_theme: String(body.world_theme || ""),
      };
      if (!inputs.story_topic) return NextResponse.json({ error: "story_topic required" }, { status: 400 });
      await dispatchWorkflow(SHORT_WORKFLOW, inputs);
      return NextResponse.json({ ok: true, workflow: SHORT_WORKFLOW, inputs });
    }
    // Direct GitHub API only: the run-scoped token is masked in Actions and lets
    // the website exchange encrypted messages with this same persistent plan.
    const prompt = String(body.prompt || body.story_topic || "").trim();
    if (!prompt) return NextResponse.json({ error: "prompt required" }, { status: 400 });
    if (prompt.length > 4_000) return NextResponse.json({ error: "prompt exceeds 4000 characters" }, { status: 413 });
    const model = String(body.model_quality || body.model || "hard");
    const chatToken = makeChatToken();
    const dispatchId = makeDispatchId();
    await dispatchWorkflow(AGENT_WORKFLOW, {
      prompt,
      model_quality: model,
      agent_chat_key: chatToken,
      chat_dispatch_id: dispatchId,
    });
    return NextResponse.json({ ok: true, workflow: AGENT_WORKFLOW, prompt,
      model_quality: model, chatToken, dispatchId });
  } catch (e: any) {
    const msg = String(e?.message || e);
    if (msg.includes("409") || msg.toLowerCase().includes("already")) {
      return NextResponse.json({ error: "Workflow already dispatching — GitHub rate-limits to one dispatch per ~20s. Please wait and the new run will appear in the sidebar.", details: msg }, { status: 409 });
    }
    const status = msg.includes("GITHUB_TOKEN") ? 500 : 502;
    return NextResponse.json({ error: msg }, { status });
  }
}
