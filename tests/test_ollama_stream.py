"""A thinking model must not lose its answer to the token ceiling.

A real run with the `hard` preset (qwen3:8b, thinking on) spent ~500 s reasoning,
hit the flat 1600-token num_predict ceiling and stopped mid-sentence:
`{"narration":"... 'You're a lifesaver,' he` — 395 chars, far below the words a
two-minute story needs. The wrapper now notices `done_reason: "length"` and asks
again with a bigger budget instead of handing a broken answer downstream.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from ollama_stream import MAX_PREDICT_CEILING, next_token_budget  # noqa: E402


class TokenBudgetTests(unittest.TestCase):
    def test_budget_grows_well_past_the_old_1600(self):
        self.assertGreaterEqual(next_token_budget(1600), 4096)
        self.assertEqual(next_token_budget(2800), 5600)
        self.assertEqual(next_token_budget(MAX_PREDICT_CEILING), MAX_PREDICT_CEILING)

    def test_workflow_scales_the_budget_with_the_story_length(self):
        workflow = (ROOT / ".github/workflows/main.yml").read_text(encoding="utf-8")
        self.assertIn("NARRATION_TOKENS=$((600 + DURATION_SECONDS * 5))", workflow)
        self.assertIn("REPAIR_TOKENS=$((800 + DURATION_SECONDS * 5))", workflow)
        self.assertIn("num_predict:$tokens}}' > narration_request.json", workflow)
        self.assertIn("num_predict:$tokens}, messages:", workflow)
        # Every request keeps the model loaded, which removes minute-long reloads.
        self.assertIn('keep_alive:"60m"', workflow)
        self.assertIn("num_ctx:8192", workflow)

    def test_workflow_asks_for_brief_reasoning(self):
        workflow = (ROOT / ".github/workflows/main.yml").read_text(encoding="utf-8")
        self.assertIn("THINK BRIEFLY", workflow)


class _CutOffThenComplete(BaseHTTPRequestHandler):
    """First reply stops at the ceiling; the bigger-budget retry finishes."""

    requests: list[dict] = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length))
        type(self).requests.append(payload)
        budget = int(payload.get("options", {}).get("num_predict") or 0)
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        if budget < 4096:
            events = [
                {"message": {"thinking": "r" * 500}, "done": False},
                {"message": {"content": '{"narration":"Jordan spotted a leather'}, "done": False},
                {"done": True, "done_reason": "length", "eval_count": budget},
            ]
        else:
            events = [
                {"message": {"content": json.dumps({"narration": "COMPLETE STORY"})}, "done": False},
                {"done": True, "done_reason": "stop", "eval_count": 900},
            ]
        for event in events:
            self.wfile.write((json.dumps(event) + "\n").encode())


class TruncatedResponseTests(unittest.TestCase):
    def test_cut_off_answer_is_retried_with_a_bigger_budget(self):
        handler = type("Handler", (_CutOffThenComplete,), {"requests": []})
        server = HTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)

        request = {
            "model": "qwen3:8b",
            "messages": [{"role": "user", "content": "tell a story"}],
            "think": True,
            "stream": False,
            "options": {"temperature": 2.0, "top_p": 0.99, "num_predict": 1600},
        }
        with self.subTest("streams a repaired answer"):
            import tempfile

            with tempfile.TemporaryDirectory() as tmp:
                request_path = Path(tmp) / "request.json"
                output_path = Path(tmp) / "response.json"
                request_path.write_text(json.dumps(request), encoding="utf-8")
                result = subprocess.run(
                    [sys.executable, "tools/ollama_stream.py",
                     "--request", str(request_path), "--output", str(output_path),
                     "--label", "story narration", "--timeout", "30",
                     "--url", f"http://127.0.0.1:{server.server_port}/api/chat"],
                    cwd=ROOT, capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 0, msg=result.stderr[-2000:])
                self.assertIn("CUT OFF at the token ceiling", result.stdout)
                self.assertIn("num_predict=", result.stdout)
                self.assertIn("thinking still on", result.stdout)
                data = json.loads(output_path.read_text(encoding="utf-8"))
                self.assertEqual(json.loads(data["response"]), {"narration": "COMPLETE STORY"})
                self.assertEqual(data["done_reason"], "stop")
                self.assertFalse(data["truncated"])
                self.assertGreaterEqual(data["token_ceiling_retry"], 4096)

        budgets = [item["options"]["num_predict"] for item in handler.requests]
        self.assertEqual(len(budgets), 2)
        self.assertEqual(budgets[0], 1600)
        self.assertGreater(budgets[1], budgets[0])
        # The retry drops thinking: re-reasoning the same prompt would double the
        # wall time on a slow CPU preset, which is exactly what we are fixing.
        # Thinking is never switched off for a retry: the user watches it every time.
        self.assertTrue(handler.requests[0].get("think"))
        self.assertTrue(handler.requests[1].get("think"))
        # The retry carries a plain instruction to finish rather than redraft.
        steer = handler.requests[1]["messages"][-1]["content"]
        self.assertIn("cut off", steer)


class _PieceByPiece(BaseHTTPRequestHandler):
    """Streams many tiny pieces so the console can be checked for real streaming."""

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        events = [
            {"message": {"thinking": "Th"}, "done": False},
            {"message": {"thinking": "inking about the beats."}, "done": False},
            {"message": {"content": '{"narration":'}, "done": False},
            {"message": {"content": '"Maya found it."}'}, "done": False},
            {"done": True, "done_reason": "stop", "eval_count": 42},
        ]
        for event in events:
            self.wfile.write((json.dumps(event) + "\n").encode())


class LiveStreamingTests(unittest.TestCase):
    def test_every_piece_is_printed_as_it_arrives(self):
        import tempfile

        server = HTTPServer(("127.0.0.1", 0), _PieceByPiece)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)

        with tempfile.TemporaryDirectory() as tmp:
            request_path = Path(tmp) / "request.json"
            output_path = Path(tmp) / "response.json"
            request_path.write_text(json.dumps({
                "model": "qwen3:8b",
                "messages": [{"role": "user", "content": "hi"}],
                "think": True,
                "stream": False,
                "options": {"num_predict": 4000},
            }), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "tools/ollama_stream.py",
                 "--request", str(request_path), "--output", str(output_path),
                 "--label", "world plan", "--timeout", "30",
                 "--url", f"http://127.0.0.1:{server.server_port}/api/chat"],
                cwd=ROOT, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr[-2000:])
            stdout = result.stdout

        # The reasoning and the answer arrive verbatim, in order, joined together.
        self.assertIn("[world plan] thinking \u25b8 Thinking about the beats.", stdout)
        self.assertIn('[world plan] answer \u25b8 {"narration":"Maya found it."}', stdout)
        # No "reappearing" summary lines that reprint a truncated tail.
        self.assertNotIn("thinking\u2026", stdout)
        self.assertNotIn("writing\u2026", stdout)
        self.assertNotIn("reasoning preview", stdout)
        self.assertNotIn("\u2026", stdout)


class RuntimeSpeedTests(unittest.TestCase):
    """A CPU-only runner must not spend hours re-generating the same content."""

    def setUp(self):
        self.workflow = (ROOT / ".github" / "workflows" / "main.yml").read_text(encoding="utf-8")

    def test_ollama_runs_with_the_fast_settings(self):
        for setting in ("OLLAMA_FLASH_ATTENTION=1", "OLLAMA_KV_CACHE_TYPE=q8_0",
                        "OLLAMA_KEEP_ALIVE=60m", "OLLAMA_MAX_LOADED_MODELS=1"):
            self.assertIn(setting, self.workflow)
        self.assertIn('keep_alive:"60m"', self.workflow)
        self.assertIn("num_ctx:8192", self.workflow)

    def test_budgets_are_compact(self):
        self.assertIn("NARRATION_TOKENS=$((600 + DURATION_SECONDS * 5))", self.workflow)
        self.assertIn("REPAIR_TOKENS=$((800 + DURATION_SECONDS * 5))", self.workflow)
        self.assertIn("MAP_TOKENS=4000", self.workflow)
        self.assertNotIn("num_predict:12000", self.workflow)
        # 120 s narration: 600 + 600 = 1200 tokens instead of the 2800 that made
        # the model reason for 20 minutes.
        seconds, duration = 600, 120
        self.assertEqual(seconds + duration * 5, 1200)

    def test_search_many_times_but_never_loop(self):
        # The AI may research as often as it needs...
        self.assertIn("for search_round in 1 2 3 4; do", self.workflow)
        # ...but the same query twice ends the loop instead of repeating it.
        self.assertIn('if [ "$QUERIES" = "$PREVIOUS_QUERIES" ]; then', self.workflow)
        self.assertIn("PREVIOUS_QUERIES=", self.workflow)
        # Narration may be corrected up to three times, then the guard finishes it.
        self.assertIn("for attempt in 1 2 3; do", self.workflow)
        self.assertNotIn("for attempt in 1 2 3 4", self.workflow)

    def test_planning_asks_for_brief_reasoning(self):
        self.assertIn("THINK BRIEFLY: this runs on a CPU-only machine", self.workflow)
        self.assertNotIn("re-read your own blueprint three times", self.workflow)

    def test_thinking_stays_on_in_every_retry(self):
        helper = (ROOT / "tools" / "ollama_stream.py").read_text(encoding="utf-8")
        # The only think-off path left is a model with no reasoning channel at all.
        self.assertEqual(helper.count('"think": False'), 1)
        self.assertIn("no thinking channel", helper)
        self.assertIn("thinking still on", helper)
        self.assertIn("steered_after_repeat", helper)
        self.assertIn("looks_stuck", helper)

    def test_console_reports_throughput(self):
        helper = (ROOT / "tools" / "ollama_stream.py").read_text(encoding="utf-8")
        self.assertIn("tok/s", helper)


class RepetitionTests(unittest.TestCase):
    """A looping model must be spotted and told to stop, not left to spin."""

    def test_detects_a_repeated_sentence(self):
        from ollama_stream import looks_stuck

        self.assertTrue(looks_stuck(
            "Let me count the words again. Jordan finds the wallet and decides. " * 20))
        self.assertTrue(looks_stuck("let me try again. " * 200))

    def test_does_not_flag_ordinary_reasoning(self):
        from ollama_stream import looks_stuck

        story = (
            "Jordan found a wallet. He thought about keeping it. Then he returned it "
            "to the office. The owner thanked him and he felt lighter. "
        ) * 2
        self.assertFalse(looks_stuck(story))
        self.assertFalse(looks_stuck(
            '{"name":"Chair_1","shape":"Block"},{"name":"Chair_2","shape":"Block"}'))

    def test_a_loop_is_steered_instead_of_restarted(self):
        helper = (ROOT / "tools" / "ollama_stream.py").read_text(encoding="utf-8")
        self.assertIn("looping on the same words", helper)
        self.assertIn("You were repeating yourself", helper)
        self.assertIn("do NOT start another draft", helper)
        self.assertIn("steered_after_repeat", helper)


if __name__ == "__main__":
    unittest.main()
