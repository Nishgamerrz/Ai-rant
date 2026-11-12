"""The live browser bridge is run-bound, encrypted, and tunnel-free."""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ChatBridgeSecurityTests(unittest.TestCase):
    def test_registration_requires_a_signed_actions_oidc_token(self):
        route = (ROOT / "web/app/api/agent/chat/route.ts").read_text(encoding="utf-8")
        library = (ROOT / "web/lib/agentChat.ts").read_text(encoding="utf-8")
        self.assertIn("verifyActionsOidcToken(oidcToken, runId)", route)
        self.assertIn('req.headers.get("x-github-actions-oidc-token")', route)
        for requirement in ("ACTIONS_OIDC_ISSUER", "ACTIONS_OIDC_AUDIENCE", "claims.run_id",
                            "claims.repository", "claims.event_name", "workflow_ref"):
            self.assertIn(requirement, library)
        self.assertIn("verifySignature(\"RSA-SHA256\"", library)

    def test_browser_never_claims_or_replaces_a_chat_session(self):
        modal = (ROOT / "web/components/NewChatModal.tsx").read_text(encoding="utf-8")
        page = (ROOT / "web/app/page.tsx").read_text(encoding="utf-8")
        route = (ROOT / "web/app/api/agent/chat/route.ts").read_text(encoding="utf-8")
        self.assertNotIn('action: "register"', modal)
        self.assertNotIn('action: "register"', page)
        self.assertIn("registerChatSession(runId, token)", route)
        self.assertNotIn("body.chatToken", route)

    def test_workflow_mints_oidc_proof_and_keeps_chat_setup_optional(self):
        workflow = (ROOT / ".github/workflows/agent.yml").read_text(encoding="utf-8")
        self.assertIn("id-token: write", workflow)
        self.assertIn("actions: read", workflow)
        self.assertIn("X-GitHub-Actions-OIDC-Token", workflow)
        self.assertIn("audience=nishagent-chat", workflow)
        self.assertIn("continue-on-error: true", workflow)
        self.assertIn("AGENT_CHAT_REGISTERED: ${{ steps.chat-session.outputs.registered }}", workflow)
        self.assertIn("run-name: NishAgent run ${{ inputs.chat_dispatch_id || github.run_number }}", workflow)
        self.assertLess(workflow.index("Register same-run chat session"),
                        workflow.index("python3 tools/nish_agent.py"))
        self.assertNotIn("cloudflared", workflow.lower())

    def test_messages_are_individually_encrypted_and_image_bytes_are_bounded(self):
        library = (ROOT / "web/lib/agentChat.ts").read_text(encoding="utf-8")
        route = (ROOT / "web/app/api/agent/chat/route.ts").read_text(encoding="utf-8")
        runner = (ROOT / "tools/nish_agent.py").read_text(encoding="utf-8")
        self.assertIn("createCipheriv(\"aes-256-gcm\"", library)
        self.assertIn("MAX_CHAT_IMAGE_BYTES = 24_000", library)
        self.assertIn('action === "image"', route)
        self.assertIn("stage_reference_image(item)", runner)
        self.assertIn("AGENT_CHAT_REGISTERED", runner)


if __name__ == "__main__":
    unittest.main()
