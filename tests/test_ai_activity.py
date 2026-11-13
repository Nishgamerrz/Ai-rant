from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from ai_activity import (SecretStreamRedactor, append_activity, parse_live_records,
                         redact_secrets, sanitize_data)  # noqa: E402


class ActivityLogTests(unittest.TestCase):
    def test_artifact_keeps_complete_text_while_live_record_is_compact(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
                os.environ, {"BAZAAR_LINK_API": "bazaar-secret-value"}):
            path = Path(tmp) / "dist" / "ai_activity.jsonl"
            output = "A complete generated answer that should be preserved. " * 30
            thinking = "The complete model-authored thinking belongs in the artifact."
            prompt_messages = [{"role": "user", "content": "Full request content."}]
            with patch("sys.stdout") as stdout:
                append_activity({"type": "model_response", "stage": "ollama",
                                 "provider": "ollama", "output": output,
                                 "thinking": thinking, "prompt_messages": prompt_messages},
                                path=path)
            row = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(row["output"], output)
            self.assertEqual(row["thinking"], thinking)
            self.assertEqual(row["prompt_messages"], prompt_messages)
            live = stdout.write.call_args_list
            live_text = "".join(str(call.args[0]) for call in live)
            self.assertIn("[ai-log]", live_text)
            self.assertNotIn(output, live_text)
            self.assertNotIn(thinking, live_text)
            self.assertNotIn("Full request content", live_text)

    def test_live_progress_can_stream_without_repeating_large_artifact_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ai_activity.jsonl"
            preview = "The model is still writing the next beat."
            with patch("sys.stdout") as stdout, patch("sys.stderr") as stderr:
                append_activity({"type": "model_progress", "stage": "ollama",
                                 "status": "streaming", "channel": "thinking",
                                 "preview": preview, "characters": 800},
                                path=path, persist=False, live_stream=sys.stderr)
            self.assertFalse(path.exists())
            self.assertFalse(stdout.write.called, "progress telemetry must not share model stdout")
            live_text = "".join(str(call.args[0]) for call in stderr.write.call_args_list)
            self.assertIn(preview, live_text)
            self.assertIn("model_progress", live_text)
            self.assertEqual(len(parse_live_records(live_text)), 1)

    def test_explicit_falsey_live_stream_is_not_replaced_by_stdout(self):
        class FalseyStream(io.StringIO):
            def __bool__(self):
                return False

        sink = FalseyStream()
        with patch("sys.stdout") as stdout:
            append_activity({"type": "diagnostic", "stage": "test", "status": "ok"},
                            persist=False, live_stream=sink)
        self.assertIn("[ai-log]", sink.getvalue())
        self.assertFalse(stdout.write.called)

    def test_known_provider_secrets_and_bearer_tokens_are_redacted(self):
        with patch.dict(os.environ, {
            "BAZAAR_LINK_API": "bazaar-secret-value",
            "BAZAARLINK_API_KEY": "bazaar-request-secret",
            "GEMINI_API_KEY": "gemini-secret-value",
            "GROQ_API_KEY": "groq-secret-value",
        }):
            safe = redact_secrets(
                "bazaar-secret-value bazaar-request-secret gemini-secret-value groq-secret-value "
                "Authorization: Bearer abcdefghijklmnopqrstuvwxyz1234"
            )
        self.assertNotIn("bazaar-secret-value", safe)
        self.assertNotIn("bazaar-request-secret", safe)
        self.assertNotIn("gemini-secret-value", safe)
        self.assertNotIn("groq-secret-value", safe)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz1234", safe)
        self.assertEqual(safe.count("[REDACTED]"), 5)

    def test_streaming_redaction_handles_credentials_split_across_chunks(self):
        with patch.dict(os.environ, {"BAZAAR_LINK_API": "bazaar-secret-value"}):
            redactor = SecretStreamRedactor()
            visible = redactor.feed("This is an answer long enough to stream before the key: ")
            visible += redactor.feed("bazaar-secret-")
            visible += redactor.feed("value, and this sentence continues after the key.")
            visible += redactor.flush()

        self.assertIn("This is an answer", visible)
        self.assertIn("[REDACTED]", visible)
        self.assertNotIn("bazaar-secret-value", visible)

    def test_secret_field_names_and_json_style_credentials_are_redacted(self):
        raw = '{"BAZAAR_LINK_API":"bazaar-json-secret","api_key":"generic-api-secret"}'
        safe = redact_secrets(raw)
        self.assertNotIn("bazaar-json-secret", safe)
        self.assertNotIn("generic-api-secret", safe)
        structured = sanitize_data({"GEMINI_API_KEY": "another-gemini-secret",
                                    "nested": {"authorization": "Bearer token-value"}})
        self.assertEqual(structured["GEMINI_API_KEY"], "[REDACTED]")
        self.assertEqual(structured["nested"]["authorization"], "[REDACTED]")

    def test_dashboard_activity_artifact_is_uploaded_even_after_failure(self):
        workflow = (ROOT / ".github" / "workflows" / "main.yml").read_text(encoding="utf-8")
        start = workflow.index("- name: Upload structured AI activity for the dashboard")
        block = workflow[start:workflow.index("- name: Bundle the final deliverables", start)]
        self.assertIn("if: always()", block)
        self.assertIn("name: Roblox-Story-Short-AI-Activity", block)
        self.assertIn("dist/ai_activity.jsonl", block)
        self.assertIn("story_subagent_results.json", block)

    def test_live_records_are_parsed_and_non_ai_lines_are_ignored(self):
        line = '[ai-log] {"type":"provider_attempt","provider":"bazaarlink","status":"fallback"}'
        self.assertEqual(parse_live_records("Run sudo apt-get update\n" + line), [
            {"type": "provider_attempt", "provider": "bazaarlink", "status": "fallback"}
        ])


if __name__ == "__main__":
    unittest.main()
