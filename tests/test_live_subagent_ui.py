from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class LiveSubagentUiTests(unittest.TestCase):
    def test_live_chat_parses_safe_progress_streamed_answers_and_tools(self):
        source = (ROOT / "web" / "components" / "ChatWindow.tsx").read_text(encoding="utf-8")
        self.assertIn("export function parseLiveLogTail", source)
        self.assertIn(r"replace(/\x1b\[[0-9;]*m/g", source)
        self.assertIn("[subagent progress]", source)
        self.assertIn("[subagent answer]", source)
        self.assertIn("public result \\(streaming\\)", source)
        self.assertIn("[subagent tool]", source)
        self.assertIn("const toolEvent = plain.match", source)
        self.assertIn("event_id: eventId", source)
        self.assertIn("source: \"subagent\"", source)
        self.assertIn("mergeLiveMessages(messages, liveMsgs)", source)
        self.assertIn("export function mergeLiveTools", source)
        self.assertIn("const displayTools = mergeLiveTools(tools, liveTools)", source)
        self.assertIn("safePublicStatus(publicStatus)", source)
        self.assertIn("reasoning is active; private model thoughts are hidden", source)
        self.assertIn("quietModelProgress", source)
        self.assertIn("Selected model is processing the plan; private reasoning is hidden.", source)
        self.assertIn("public_status:", source)
        self.assertNotIn("liveLog.slice(", source, "raw workflow logs must never render in chat")
        self.assertIn("Subagent-authored tool calls", (ROOT / "web" / "components" / "AiActivityTimeline.tsx").read_text(encoding="utf-8"))

    def test_chat_ui_never_renders_legacy_private_thought_fields(self):
        chat = (ROOT / "web" / "components" / "ChatWindow.tsx").read_text(encoding="utf-8")
        timeline = (ROOT / "web" / "components" / "AiActivityTimeline.tsx").read_text(encoding="utf-8")
        self.assertNotIn("m.thought", chat)
        self.assertNotIn("event.thinking", timeline)
        self.assertIn("Safe sub-agent progress", timeline)
        self.assertIn("Public progress", chat)


if __name__ == "__main__":
    unittest.main()
