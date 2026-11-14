from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import nish_agent  # noqa: E402


class NishAgentSubagentStreamTests(unittest.TestCase):
    def test_child_stdout_is_forwarded_before_the_subagent_process_exits(self):
        output = io.StringIO()
        result_box = []
        source = (
            "import sys,time; "
            "print('[subagent progress] live · narration task started', flush=True); "
            "time.sleep(0.45); "
            "print('[subagent answer] live · public result (streaming):', flush=True)"
        )
        with tempfile.TemporaryDirectory() as tmp:
            worker = threading.Thread(target=lambda: result_box.append(
                nish_agent._run_live_subprocess(
                    [sys.executable, "-u", "-c", source], cwd=tmp, timeout=3)))
            with redirect_stdout(output):
                worker.start()
                try:
                    deadline = time.monotonic() + 2
                    while "[subagent progress] live" not in output.getvalue() and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertIn("[subagent progress] live", output.getvalue())
                    self.assertTrue(worker.is_alive(), "the child should still be running after its first live line")
                finally:
                    worker.join(timeout=4)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result_box, [(0, "[subagent progress] live · narration task started\n"
                                       "[subagent answer] live · public result (streaming):\n", False)])
        self.assertIn("[subagent answer] live", output.getvalue())

    def test_tool_activity_is_live_but_console_and_artifacts_hide_raw_data(self):
        secret = "AIzaSyD" + "x" * 34
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "agent_tools.jsonl"
            tool_output = {"ok": True, "path": "docs/sample.md", "bytes": 64,
                           "content": f"private file contents {secret}"}
            with patch.object(nish_agent, "TOOLS", {"read_file": lambda _call: tool_output}), \
                    patch.object(nish_agent, "TOOLS_LOG", log_path), \
                    patch.dict(os.environ, {"GEMINI_API_KEY": secret, "AI_COLOR": "1"}), \
                    redirect_stdout(output):
                results = nish_agent.execute_agent_tools(
                    [{"tool": "read_file", "path": "docs/sample.md"}], "test")

            live = output.getvalue()
            event = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
            public_log = json.dumps(event)
            self.assertIn("[tool read_file] started · path=docs/sample.md · event=", live)
            self.assertIn("[tool read_file] succeeded", live)
            self.assertIn("\x1b[35m", live, "live tool activity should use the distinct magenta console color")
            event_id = event.get("event_id")
            self.assertTrue(event_id)
            self.assertIn(f"event={event_id}", live)
            self.assertNotIn(secret, live + public_log)
            self.assertNotIn("private file contents", live + public_log)
            self.assertNotIn("content", event["output"])
            self.assertEqual(results[0]["output"]["path"], "docs/sample.md")
            self.assertIn("[REDACTED]", results[0]["output"]["content"])

    def test_chat_artifact_hides_shell_commands_and_provider_output(self):
        secret = "ghp_" + "a" * 36
        with tempfile.TemporaryDirectory() as tmp:
            chat_path = Path(tmp) / "agent_chat.json"
            history = [
                {"role": "assistant", "content": "", "tool_calls": [
                    {"tool": "run_cmd", "cmd": f"curl -H 'Authorization: {secret}' https://example.test"}]},
                {"role": "tool", "tool": "run_cmd", "output": {
                    "ok": True, "code": 0, "cmd": f"curl {secret}",
                    "output": f"raw provider JSON contains {secret}"}},
            ]
            with patch.object(nish_agent, "CHAT_LOG", chat_path):
                nish_agent.save_chat(history)
            saved = chat_path.read_text(encoding="utf-8")
            parsed = json.loads(saved)
        self.assertNotIn(secret, saved)
        self.assertNotIn("raw provider JSON", saved)
        self.assertNotIn("curl", saved)
        self.assertEqual(parsed[1]["output"]["note"],
                         "Shell command and output are hidden from the activity artifact.")


if __name__ == "__main__":
    unittest.main()
