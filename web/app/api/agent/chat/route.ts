import { NextRequest, NextResponse } from "next/server";
import {
  MAX_CHAT_MESSAGE_CHARS,
  acknowledgeQueuedMessages,
  appendQueuedImage,
  appendQueuedMessage,
  authenticateChatSession,
  chatAuthVariableName,
  deleteChatMessages,
  deleteChatVariable,
  getAgentRun,
  readQueuedMessages,
  registerChatSession,
  verifyActionsOidcToken,
} from "@/lib/agentChat";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function bearer(req: NextRequest) {
  const value = req.headers.get("authorization") || "";
  const match = value.match(/^Bearer\s+(.+)$/i);
  return match?.[1]?.trim() || "";
}

function runIdFrom(req: NextRequest, body?: any) {
  return String(body?.runId ?? body?.run ?? new URL(req.url).searchParams.get("run") ?? "").trim();
}

function errorResponse(error: unknown) {
  const message = String((error as any)?.message || error);
  const status = /invalid chat session|chat session|already registered|unauthorized|authentication/i.test(message)
    ? 401
    : /no longer active|does not belong|invalid run/i.test(message)
      ? 409
      : /full|exceed|too long/i.test(message)
        ? 413
        : /GITHUB_TOKEN/i.test(message)
          ? 500
          : 502;
  return NextResponse.json({ ok: false, error: message }, {
    status,
    headers: { "Cache-Control": "no-store, max-age=0" },
  });
}

// The browser uses this endpoint to enqueue messages into the currently running
// NishAgent plan. Text is AES-GCM encrypted in a per-run GitHub Actions variable;
// the agent gets the corresponding one-time key through a masked workflow input.
export async function POST(req: NextRequest) {
  try {
    const body = await req.json().catch(() => ({}));
    const runId = runIdFrom(req, body);
    if (!/^\d{1,20}$/.test(runId)) {
      return NextResponse.json({ ok: false, error: "valid runId required" }, { status: 400 });
    }
    const token = bearer(req);
    if (!token) return NextResponse.json({ ok: false, error: "chat session token required" }, { status: 401 });
    const action = String(body.action || "message").toLowerCase();

    if (action === "register") {
      const oidcToken = req.headers.get("x-github-actions-oidc-token") || "";
      const claims = await verifyActionsOidcToken(oidcToken, runId);
      if (!claims) {
        return NextResponse.json({ ok: false, error: "registration requires a valid OIDC proof from this GitHub Actions run" }, {
          status: 401, headers: { "Cache-Control": "no-store, max-age=0" },
        });
      }
      await getAgentRun(runId);
      await registerChatSession(runId, token);
      return NextResponse.json({ ok: true, registered: true, runId }, {
        headers: { "Cache-Control": "no-store, max-age=0" },
      });
    }

    const authenticated = await authenticateChatSession(runId, token);
    if (!authenticated) return NextResponse.json({ ok: false, error: "invalid chat session token" }, { status: 401 });

    if (action === "cleanup") {
      const deletedMessages = await deleteChatMessages(runId);
      await deleteChatVariable(chatAuthVariableName(runId));
      return NextResponse.json({ ok: true, cleaned: true, deletedMessages }, {
        headers: { "Cache-Control": "no-store, max-age=0" },
      });
    }
    if (action === "ack") {
      const through = String(body.through || "");
      if (!through) return NextResponse.json({ ok: false, error: "through message id required" }, { status: 400 });
      const acknowledged = await acknowledgeQueuedMessages(runId, token, through);
      return NextResponse.json({ ok: true, acknowledged }, {
        headers: { "Cache-Control": "no-store, max-age=0" },
      });
    }
    if (action === "image") {
      await getAgentRun(runId);
      const queued = await appendQueuedImage(runId, token, String(body.imageData || ""),
        String(body.mimeType || ""), String(body.fileName || "face-reference.jpg"), String(body.clientId || ""));
      const { imageData: _discardedImage, ...publicMessage } = queued;
      return NextResponse.json({ ok: true, queued: true, runId, message: publicMessage }, {
        headers: { "Cache-Control": "no-store, max-age=0" },
      });
    }

    const message = String(body.message || "").trim();
    if (!message) return NextResponse.json({ ok: false, error: "message required" }, { status: 400 });
    if (message.length > MAX_CHAT_MESSAGE_CHARS) {
      return NextResponse.json({ ok: false, error: `message exceeds ${MAX_CHAT_MESSAGE_CHARS} characters` }, { status: 413 });
    }
    await getAgentRun(runId);
    const queued = await appendQueuedMessage(runId, token, message, String(body.clientId || ""));
    return NextResponse.json({ ok: true, queued: true, runId, message: queued }, {
      headers: { "Cache-Control": "no-store, max-age=0" },
    });
  } catch (error) {
    return errorResponse(error);
  }
}

// The running action polls this endpoint with its session token. The browser can
// use the same read-only path to show messages waiting in the current plan.
export async function GET(req: NextRequest) {
  try {
    const runId = runIdFrom(req);
    if (!/^\d{1,20}$/.test(runId)) {
      return NextResponse.json({ ok: false, error: "valid run id required" }, { status: 400 });
    }
    const token = bearer(req);
    if (!(await authenticateChatSession(runId, token))) {
      return NextResponse.json({ ok: false, error: "invalid chat session token" }, { status: 401 });
    }
    const after = new URL(req.url).searchParams.get("after") || "";
    const messages = await readQueuedMessages(runId, token, after);
    const previews = messages.map(({ imageData: _discardedImage, ...message }) => message);
    return NextResponse.json({ ok: true, messages: previews }, {
      headers: { "Cache-Control": "no-store, max-age=0" },
    });
  } catch (error) {
    return errorResponse(error);
  }
}
