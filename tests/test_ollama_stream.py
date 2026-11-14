"""A thinking model must not lose its answer to the token ceiling.

A real run with the `hard` preset (qwen3:8b, thinking on) spent ~500 s reasoning,
hit the flat 1600-token num_predict ceiling and stopped mid-sentence:
`{"narration":"... 'You're a lifesaver,' he` — 395 chars, far below the words a
two-minute story needs. The wrapper now notices `done_reason: "length"` and asks
again with a bigger budget instead of handing a broken answer downstream.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from ollama_stream import (MAX_PREDICT_CEILING, next_token_budget,
                           public_output_parts)  # noqa: E402


class PublicOutputTests(unittest.TestCase):
    def test_only_allowlisted_public_fields_are_extracted_and_credentials_redacted(self):
        response = json.dumps({
            "public_rationale": "A small honest choice gives the ending meaning. bazaar-secret-value",
            "narration": "Maya returned the wallet to its owner.",
            "thinking": "private reasoning must not be shown",
            "chain_of_thought": "private chain-of-thought",
            "provider_debug": "raw provider JSON",
        })
        with patch.dict(os.environ, {"BAZAAR_LINK_API": "bazaar-secret-value"}):
            parts = public_output_parts(response)
        self.assertEqual([part[0] for part in parts], ["public rationale", "narration"])
        combined = " ".join(part[2] for part in parts)
        self.assertIn("[REDACTED]", combined)
        for forbidden in ("bazaar-secret-value", "private reasoning", "private chain-of-thought",
                          "raw provider JSON"):
            self.assertNotIn(forbidden, combined)

    def test_public_status_is_shown_but_thought_fields_are_never_public(self):
        response = json.dumps({
            "public_status": "I am checking the story hook and delegation requirements.",
            "thought": "private chain-of-thought must not be exposed",
            "answer": "The helper will create the camera plan.",
        })
        parts = public_output_parts(response)
        self.assertEqual([part[0] for part in parts], ["public status", "answer"])
        self.assertIn("checking the story hook", parts[0][2])
        self.assertNotIn("private chain-of-thought", json.dumps(parts))

    def test_unparsed_structured_output_is_not_downgraded_to_public_prose(self):
        malformed = '{"public_rationale":"safe", "narration":"Maya returned it"'
        self.assertEqual(public_output_parts(malformed), [])


class TokenBudgetTests(unittest.TestCase):
    def test_budget_grows_well_past_the_old_1600(self):
        self.assertGreaterEqual(next_token_budget(1600), 4096)
        self.assertEqual(next_token_budget(2800), 5600)
        self.assertEqual(next_token_budget(MAX_PREDICT_CEILING), MAX_PREDICT_CEILING)

    def test_workflow_scales_the_budget_with_the_story_length(self):
        workflow = (ROOT / ".github/workflows/main.yml").read_text(encoding="utf-8")
        self.assertIn("NARRATION_TOKENS=$((1200 + DURATION_SECONDS * 8))", workflow)
        self.assertNotIn("REPAIR_TOKENS", workflow)
        self.assertIn("num_predict:$tokens}}' > narration_request.json", workflow)
        self.assertNotIn("story + sub-agent answers", workflow)
        # Every request keeps the model loaded, which removes minute-long reloads.
        self.assertIn('keep_alive:"60m"', workflow)
        self.assertIn("num_ctx:$ctx", workflow)

    def test_workflow_uses_private_reasoning_only_for_a_safe_public_rationale(self):
        workflow = (ROOT / ".github/workflows/main.yml").read_text(encoding="utf-8")
        self.assertIn("THINK BRIEFLY and PRIVATELY", workflow)
        self.assertIn("PUBLIC RATIONALE", workflow)
        self.assertIn("private chain-of-thought", workflow)


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
            {"message": {"content": '{"public_rationale":"A small choice '}, "done": False},
            {"message": {"content": 'turns the hook into a hopeful ending.","narration":"Maya '}, "done": False},
            {"message": {"content": 'found it."}'}, "done": False},
            {"done": True, "done_reason": "stop", "eval_count": 42},
        ]
        for event in events:
            self.wfile.write((json.dumps(event) + "\n").encode())


class LiveStreamingTests(unittest.TestCase):
    def test_private_thoughts_and_raw_json_are_hidden_but_public_fields_are_shown(self):
        import tempfile

        server = HTTPServer(("127.0.0.1", 0), _PieceByPiece)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)

        with tempfile.TemporaryDirectory() as tmp:
            request_path = Path(tmp) / "request.json"
            output_path = Path(tmp) / "response.json"
            activity_path = Path(tmp) / "dist" / "ai_activity.jsonl"
            request_path.write_text(json.dumps({
                "model": "qwen3:8b",
                "messages": [{"role": "user", "content": "hi"}],
                "think": True,
                "stream": False,
                "options": {"num_predict": 4000},
            }), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(ROOT / "tools" / "ollama_stream.py"),
                 "--request", str(request_path), "--output", str(output_path),
                 "--label", "world plan", "--timeout", "30",
                 "--url", f"http://127.0.0.1:{server.server_port}/api/chat"],
                cwd=tmp, capture_output=True, text=True,
                env={**os.environ, "AI_COLOR": "1", "PYTHONUNBUFFERED": "1",
                     "GITHUB_ACTIONS": "true", "CI": "true"},
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr[-2000:])
            stdout = result.stdout
            stderr = result.stderr
            activity = [json.loads(line) for line in activity_path.read_text(encoding="utf-8").splitlines()]

        # Internal reasoning and provider JSON are withheld; a public rationale and
        # the validated narration field are still presented with distinct colors.
        self.assertIn("[world plan] reasoning is active; private model thoughts are hidden.", stdout)
        self.assertIn("[world plan] preparing the structured result; raw JSON is hidden.", stdout)
        self.assertIn("[world plan] public rationale \u25b8 A small choice turns the hook into a hopeful ending.", stdout)
        self.assertIn("[world plan] narration \u25b8 Maya found it.", stdout)
        self.assertNotIn("Thinking about the beats.", stdout)
        self.assertNotIn('{"public_rationale"', stdout)
        self.assertIn("[world plan] \u2713 done", stdout)
        self.assertNotIn("reasoning chars", stdout)
        self.assertIn("\u001b[37m", stdout)
        self.assertIn("\u001b[36m", stdout)
        self.assertNotIn("[ai-log]", stdout + stderr)
        model_event = next(event for event in activity if event.get("type") == "model_response")
        self.assertEqual(model_event["public_rationale"],
                         "A small choice turns the hook into a hopeful ending.")
        self.assertIn("Maya found it.", model_event["output"])
        self.assertNotIn('{"public_rationale"', model_event["output"])
        self.assertNotIn("Thinking about the beats.", json.dumps(model_event))
        artifact_progress = [event for event in activity if event.get("type") == "model_progress"]
        self.assertEqual({event.get("channel") for event in artifact_progress}, {"thinking", "answer"})
        thinking_previews = [event["preview"] for event in artifact_progress
                             if event["channel"] == "thinking"]
        answer_previews = [event["preview"] for event in artifact_progress
                           if event["channel"] == "answer"]
        self.assertEqual(thinking_previews[-1], "Private reasoning is hidden; phase progress only.")
        self.assertEqual(answer_previews[-1],
                         "Structured response is being prepared; fields are not shown until validation.")
        self.assertNotIn("Thinking about the beats.", json.dumps(artifact_progress))
        self.assertNotIn('{"public_rationale"', json.dumps(artifact_progress))
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
        # ONE context size for the whole run. num_ctx is a load-time option, so two
        # different values would make Ollama unload and reload the model between
        # steps: that is the "why did it reload again?" minutes.
        self.assertIn("AI_NUM_CTX=8192", self.workflow)
        self.assertIn('num_ctx:$ctx', self.workflow)
        self.assertNotIn("num_ctx:8192", self.workflow)
        self.assertNotIn("num_ctx:1024", self.workflow)
        # The warm-up must load with the same context size as the real prompts, or
        # the first prompt reloads the model it just loaded.
        warmup = self.workflow[self.workflow.index("/api/generate") - 500:self.workflow.index("/api/generate") + 500]
        self.assertIn("num_ctx:$ctx", warmup)
        self.assertIn('--argjson ctx "$AI_NUM_CTX"', warmup)

    def test_budgets_are_compact(self):
        self.assertIn("NARRATION_TOKENS=$((1200 + DURATION_SECONDS * 8))", self.workflow)
        self.assertNotIn("REPAIR_TOKENS", self.workflow)
        # The selected model emits only a compact orchestration envelope; the
        # delegated sub-agent writes the map and camera JSON.
        self.assertIn("MAP_ORCHESTRATION_TOKENS=1200", self.workflow)
        self.assertNotIn("MAP_TOKENS", self.workflow)
        self.assertIn("Orchestrate and review the delegated map", self.workflow)
        self.assertNotIn("num_predict:12000", self.workflow)
        # 120 s narration: 1200 + 960 = 2160 tokens: enough for a thinking model to
        # plan briefly AND write the story, so it never stalls on the ceiling.
        seconds, duration = 1200, 120
        self.assertEqual(seconds + duration * 8, 2160)

    def test_map_calls_have_hard_wall_clock_budgets_while_other_calls_keep_their_idle_guard(self):
        start = self.workflow.index("- name: Orchestrate and review the delegated map")
        end = self.workflow.index("- name: Re-view the AI world", start)
        map_step = self.workflow[start:end]
        self.assertIn("--max-seconds 600", map_step)
        self.assertIn("--max-seconds 300", map_step)
        self.assertIn("AI_STALL=900", self.workflow)
        self.assertIn('--stall-seconds "${AI_STALL:-900}"', self.workflow)
        presets = json.loads((ROOT / "web/lib/model_presets.json").read_text(encoding="utf-8"))["presets"]
        self.assertEqual(presets["smart_11b"]["timeout_seconds"], 9000)
        self.assertIn("MODEL_TIMEOUT_SECONDS: ${{ steps.model-preset.outputs.timeout_seconds }}", self.workflow)
        self.assertIn('AI_TIMEOUT="$MODEL_TIMEOUT_SECONDS"', self.workflow)
        self.assertNotIn("--max-seconds", self.workflow[:start])

    def test_map_research_and_reviews_do_not_reenter_a_full_plan_loop(self):
        start = self.workflow.index("- name: Orchestrate and review the delegated map")
        end = self.workflow.index("- name: Re-view the AI world", start)
        map_step = self.workflow[start:end]
        self.assertIn("map_orchestration.py queries", map_step)
        self.assertNotIn("for helper_round", map_step)
        self.assertNotIn("for delegation_retry", map_step)
        self.assertNotIn("map_repair_request.json", map_step)
        # The completed proofread is the canonical source; no later local rewrite can replace it.
        story = self.workflow[self.workflow.index("- name: Write a believable real-life story"):start]
        self.assertIn("prepare_narration.py --subagent story_subagent_results.json", story)
        self.assertNotIn("narration repair", story)
        self.assertNotIn("--truncate", story)

    def test_planning_requests_a_public_rationale_not_private_reasoning(self):
        self.assertIn("THINK BRIEFLY and PRIVATELY", self.workflow)
        self.assertIn("PUBLIC RATIONALE", self.workflow)
        self.assertIn("In your first response, author exactly two distinct tasks", self.workflow)
        self.assertIn("private chain-of-thought", self.workflow)
        self.assertNotIn("re-read your own blueprint three times", self.workflow)

    def test_thinking_stays_on_in_every_retry(self):
        helper = (ROOT / "tools" / "ollama_stream.py").read_text(encoding="utf-8")
        # Keep internal reasoning enabled, but show only safe summaries in public output.
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


class _Recorder:
    """A fake console that remembers every single write call."""

    def __init__(self):
        self.writes = []
        self.flushes = 0

    def write(self, text):
        self.writes.append(text)

    def flush(self):
        self.flushes += 1


class TypedConsoleTests(unittest.TestCase):
    """The console must fill in letter by letter, never in bursts of words."""

    def test_each_character_is_its_own_write_and_flush(self):
        sys.path.insert(0, str(ROOT / "tools"))
        from ollama_stream import TypedConsole

        recorder = _Recorder()
        console = TypedConsole(delay=0, budget=0, out=recorder)
        console.write("Maya counted the coins.")
        self.assertEqual("".join(recorder.writes), "Maya counted the coins.")
        self.assertEqual(len(recorder.writes), len("Maya counted the coins."))
        self.assertTrue(all(len(chunk) <= 1 for chunk in recorder.writes))
        # One flush per character: that is what pushes it to the log immediately.
        self.assertGreaterEqual(recorder.flushes, len("Maya counted the coins."))

    def test_a_big_chunk_arrives_one_letter_at_a_time(self):
        sys.path.insert(0, str(ROOT / "tools"))
        from ollama_stream import TypedConsole

        chunk = "x" * 900  # Ollama can hand over several sentences at once
        recorder = _Recorder()
        TypedConsole(delay=0, budget=0, out=recorder).write(chunk)
        self.assertEqual(len(recorder.writes), 900)

    def test_the_typing_pace_never_costs_more_than_its_budget(self):
        sys.path.insert(0, str(ROOT / "tools"))
        from ollama_stream import TypedConsole

        recorder = _Recorder()
        console = TypedConsole(delay=0.02, budget=0.05, out=recorder)
        started = time.time()
        console.write("a" * 200)
        elapsed = time.time() - started
        self.assertEqual(len(recorder.writes), 200)      # everything still typed out
        self.assertLess(elapsed, 0.5)                    # but the pace stopped early
        self.assertGreaterEqual(console.spent, 0.04)

    def test_a_heartbeat_says_the_model_is_still_working(self):
        sys.path.insert(0, str(ROOT / "tools"))
        from ollama_stream import Heartbeat, TypedConsole

        recorder = _Recorder()
        beat = Heartbeat("world plan", interval=2.0, console=TypedConsole(0, 0, out=recorder))
        beat.start()
        time.sleep(2.4)
        beat.stop()
        beat.join(timeout=2)
        text = "".join(recorder.writes)
        # With no /api/ps answer the note must not claim a load happened.
        self.assertIn("[world plan] no first token yet", text)
        self.assertNotIn("still loading the model", text)
        self.assertNotIn("\u2026", text)
        # The heartbeat only writes whole lines: it never reprints streamed text.
        self.assertTrue(all(chunk.count("\n") == 1 for chunk in recorder.writes if chunk.strip()))

    def test_a_resident_model_is_never_reported_as_loading(self):
        sys.path.insert(0, str(ROOT / "tools"))
        from ollama_stream import Heartbeat, TypedConsole

        recorder = _Recorder()
        beat = Heartbeat("world plan", interval=2.0,
                         console=TypedConsole(0, 0, out=recorder), resident=True,
                         prompt_chars=23456)
        beat.start()
        time.sleep(2.4)
        beat.stop()
        beat.join(timeout=2)
        text = "".join(recorder.writes)
        self.assertIn("already in memory, no reload", text)
        self.assertIn("23,456-character plan prompt", text)
        self.assertNotIn("loading the model", text)

    def test_a_genuine_load_says_so(self):
        sys.path.insert(0, str(ROOT / "tools"))
        from ollama_stream import Heartbeat, TypedConsole

        recorder = _Recorder()
        beat = Heartbeat("world plan", interval=2.0,
                         console=TypedConsole(0, 0, out=recorder), resident=False)
        beat.start()
        time.sleep(2.4)
        beat.stop()
        beat.join(timeout=2)
        self.assertIn("still loading the model into memory", "".join(recorder.writes))

    def test_the_waiting_note_repeats_at_most_three_times(self):
        sys.path.insert(0, str(ROOT / "tools"))
        from ollama_stream import HEARTBEAT_NOTES, Heartbeat, TypedConsole

        self.assertEqual(HEARTBEAT_NOTES, 3)
        recorder = _Recorder()
        beat = Heartbeat("world plan", interval=2.0, console=TypedConsole(0, 0, out=recorder))
        beat.start()
        time.sleep(6.6)
        beat.join(timeout=1)          # the thread stops itself once the cap is reached
        self.assertFalse(beat.is_alive())
        text = "".join(recorder.writes)
        self.assertEqual(text.count("no first token yet"), HEARTBEAT_NOTES)
        self.assertIn("(quiet note 3/3)", text)

    def test_the_waiting_note_is_the_grey_line(self):
        sys.path.insert(0, str(ROOT / "tools"))
        from console_style import CODES

        # 90 is "bright black": the grey the log viewer draws dimmest. The quiet
        # note and the box edge use it, so neither competes with the model's words.
        self.assertEqual(CODES["thought"], "\033[90m")
        self.assertEqual(CODES["frame"], "\033[90m")

    def test_every_colour_is_a_basic_ansi_code_the_log_viewer_can_draw(self):
        sys.path.insert(0, str(ROOT / "tools"))
        import re

        from console_style import CODES

        # GitHub's log viewer renders the 16 basic colours and drops 256-colour
        # codes; with "38;5;109" the whole run showed up white. Every code must be
        # a plain 30-37 or 90-97 foreground.
        for kind, code in CODES.items():
            self.assertRegex(code, r"^\033\[(3[0-7]|9[0-7])m$", kind)

    def test_the_kinds_are_told_apart(self):
        sys.path.insert(0, str(ROOT / "tools"))
        from console_style import CODES

        for a, b in (("thinking", "answer"), ("answer", "error"), ("success", "warning"),
                     ("label", "plan"), ("tool", "notice"), ("thinking", "thought")):
            self.assertNotEqual(CODES[a], CODES[b], f"{a} and {b} look identical")


class ThinkingBoxTests(unittest.TestCase):
    """The reasoning is framed so it reads as one block of machine thought."""

    def _console(self):
        sys.path.insert(0, str(ROOT / "tools"))
        from ollama_stream import TypedConsole

        recorder = _Recorder()
        return TypedConsole(0, 0, out=recorder), recorder

    def test_thinking_is_drawn_inside_a_frame(self):
        console, recorder = self._console()
        console.use("thinking")
        console.open_box("[story plan] thinking")
        console.write("first line\nsecond line\n")
        console.close_box()
        text = "".join(recorder.writes)
        self.assertIn("\u250c\u2500 [story plan] thinking", text)
        self.assertIn("\u2502 first line", text)
        self.assertIn("\u2502 second line", text)
        self.assertIn("\u2514", text)

    def test_every_boxed_line_starts_with_the_left_rule(self):
        console, recorder = self._console()
        console.use("thinking")
        console.open_box("thinking")
        console.write("alpha\nbeta\n")
        console.close_box()
        body = [line for line in "".join(recorder.writes).splitlines()
                if "alpha" in line or "beta" in line]
        self.assertEqual(len(body), 2)
        for line in body:
            self.assertIn("\u2502 ", line)

    def test_switching_to_the_answer_closes_the_frame(self):
        console, recorder = self._console()
        console.use("thinking")
        console.open_box("thinking")
        console.write("weighing two endings")
        console.use("answer")
        console.write(" answer text")
        text = "".join(recorder.writes)
        self.assertLess(text.index("\u2514"), text.index("answer text"))
        self.assertEqual(text.count("\u250c"), 1)

    def test_a_quiet_note_does_not_break_the_frame(self):
        console, recorder = self._console()
        console.use("thinking")
        console.open_box("thinking")
        console.write("half a thought")
        console.note("[story] quiet note (quiet note 1/3)")
        console.write(" the rest of it")
        console.close_box()
        text = "".join(recorder.writes)
        self.assertIn("half a thought", text)
        self.assertIn("the rest of it", text)
        self.assertEqual(text.count("\u250c"), 1)   # never reopened mid-stream
        starts = [line for line in text.splitlines() if "quiet note" in line]
        self.assertEqual(len(starts), 1)
        self.assertIn("\u2502 [story] quiet note", starts[0])

    def test_a_long_paragraph_is_broken_into_many_lines(self):
        sys.path.insert(0, str(ROOT / "tools"))
        from ollama_stream import BOX_LEFT, TypedConsole

        recorder = _Recorder()
        console = TypedConsole(0, 0, out=recorder)
        console.use("thinking")
        console.open_box("thinking")
        # One long run of text with no newlines of its own, the way a model streams.
        console.write("word " * 120)
        console.close_box()
        text = "".join(recorder.writes)
        body = [line for line in text.splitlines() if "word" in line]
        self.assertGreater(len(body), 5, "a long thought must not stay one line")
        for line in body:
            self.assertTrue(line.startswith(BOX_LEFT), line[:40])
            self.assertLessEqual(len(line), 74, line)

    def test_the_wrap_never_splits_a_word(self):
        sys.path.insert(0, str(ROOT / "tools"))
        from ollama_stream import TypedConsole

        recorder = _Recorder()
        console = TypedConsole(0, 0, out=recorder)
        console.use("thinking")
        console.open_box("thinking")
        console.write("antidisestablishmentarianism " * 30)
        console.close_box()
        text = "".join(recorder.writes)
        for line in text.splitlines():
            if "antidis" in line:
                self.assertIn("antidisestablishmentarianism", line)

    def test_plain_text_outside_the_box_is_not_rewrapped(self):
        sys.path.insert(0, str(ROOT / "tools"))
        from ollama_stream import TypedConsole

        recorder = _Recorder()
        console = TypedConsole(0, 0, out=recorder)
        console.use("answer")
        console.write("a" * 200)
        self.assertEqual("".join(recorder.writes).count("\n"), 0)

    def test_the_stream_hides_private_thoughts_and_raw_json(self):
        helper = (ROOT / "tools" / "ollama_stream.py").read_text(encoding="utf-8")
        self.assertIn("private model thoughts are hidden", helper)
        self.assertIn("public_output_parts(answer)", helper)
        self.assertIn("preparing the structured result; raw JSON is hidden", helper)
        self.assertNotIn("console.write(piece_thinking)", helper)
        self.assertNotIn("console.write(piece_content)", helper)


class _ModelCatalogHandler(BaseHTTPRequestHandler):
    """Supplies the resident-model probe and leaves request behavior to subclasses."""

    models: list[str] = []
    calls = 0

    def log_message(self, *args):
        pass

    def do_GET(self):
        body = json.dumps({"models": []}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _SilentPrimaryThenRetry(_ModelCatalogHandler):
    """The selected model stalls once, then answers when retried unchanged."""

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length))
        type(self).models.append(str(payload.get("model")))
        type(self).calls += 1
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        self.wfile.flush()
        if type(self).calls == 1:
            time.sleep(0.45)
            return
        events = [
            {"message": {"content": '{"ok":"same-model-retry"}'}, "done": False},
            {"done": True, "done_reason": "stop", "eval_count": 5},
        ]
        for event in events:
            try:
                self.wfile.write((json.dumps(event) + "\n").encode())
                self.wfile.flush()
            except BrokenPipeError:
                return


class _SlowProgressingPrimary(_ModelCatalogHandler):
    """Slow thought and answer chunks keep arriving, so the selected model finishes."""

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length))
        type(self).models.append(str(payload.get("model")))
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        self.wfile.flush()
        events = [
            {"message": {"thinking": "Reasoning"}, "done": False},
            {"message": {"thinking": " continues"}, "done": False},
            {"message": {"content": '{"ok":'}, "done": False},
            {"message": {"content": '"slow-but-progressing"}'}, "done": False},
            {"done": True, "done_reason": "stop", "eval_count": 24},
        ]
        for event in events:
            try:
                self.wfile.write((json.dumps(event) + "\n").encode())
                self.wfile.flush()
            except BrokenPipeError:
                return
            time.sleep(0.08)


class StallWatchdogTests(unittest.TestCase):
    """Only content stalls or explicit map deadlines can stop a selected model."""

    def _run_cli(self, base_handler, *, stall_seconds: float, max_seconds: float = 0.0):
        import tempfile

        handler = type("Handler", (base_handler,), {"models": [], "calls": 0})
        server = HTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)

        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            request_path = workdir / "request.json"
            request_path.write_text(json.dumps({
                "model": "qwen3:14b",
                "messages": [{"role": "user", "content": "hi"}],
                "think": True,
                "options": {"num_predict": 6000},
            }), encoding="utf-8")
            environment = {**os.environ, "AI_COLOR": "0", "AI_MIN_TPS": "100000",
                           "AI_TPS_WINDOW": "0", "AI_PROJECTED_SECONDS": "0.001"}
            environment.pop("GITHUB_ENV", None)
            command = [sys.executable, "tools/ollama_stream.py",
                       "--request", str(request_path), "--output", str(workdir / "out.json"),
                       "--label", "world plan", "--timeout", "2",
                       "--stall-seconds", str(stall_seconds),
                       "--heartbeat-seconds", "0", "--type-delay", "0"]
            if max_seconds:
                command.extend(("--max-seconds", str(max_seconds)))
            command.extend(("--url", f"http://127.0.0.1:{server.server_port}/api/chat"))
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                                    env=environment)
            output_path = workdir / "out.json"
            output = json.loads(output_path.read_text(encoding="utf-8")) if output_path.exists() else None
            return result, output, list(handler.models)

    def test_a_silent_primary_retries_the_same_selected_model(self):
        result, output, models = self._run_cli(_SilentPrimaryThenRetry, stall_seconds=0.16)
        self.assertEqual(result.returncode, 0, msg=result.stdout[-2000:] + result.stderr[-1000:])
        self.assertIn("no thinking or answer output", result.stdout)
        self.assertIn("retrying the selected model qwen3:14b once", result.stdout)
        self.assertEqual(models, ["qwen3:14b", "qwen3:14b"])
        self.assertEqual(output["model"], "qwen3:14b")
        self.assertIn("same-model-retry", output["response"])
        self.assertNotIn("fallback", result.stdout.lower())

    def test_slow_thinking_and_answer_progress_never_interrupts_the_selected_model(self):
        result, output, models = self._run_cli(_SlowProgressingPrimary, stall_seconds=0.25)
        self.assertEqual(result.returncode, 0, msg=result.stdout[-2000:] + result.stderr[-1000:])
        self.assertEqual(models, ["qwen3:14b"], "the selected model keeps the call while it emits content")
        self.assertEqual(output["model"], "qwen3:14b")
        self.assertIn("slow-but-progressing", output["response"])
        self.assertEqual(output["thinking"], "")
        self.assertNotIn("Reasoning continues", result.stdout)
        self.assertNotIn("Reasoning continues", json.dumps(output))

    def test_hard_deadline_stops_continuous_output_without_switching_models(self):
        result, output, models = self._run_cli(_SlowProgressingPrimary,
                                                stall_seconds=2, max_seconds=0.15)
        self.assertEqual(result.returncode, 1, msg=result.stdout[-2000:] + result.stderr[-1000:])
        self.assertIsNone(output)
        self.assertEqual(models, ["qwen3:14b"])
        self.assertIn("exceeded its wall-clock budget", result.stderr)
        self.assertIn("the selected model was not changed", result.stderr)
        self.assertIn("Selected Ollama model timed out", result.stderr)

    def test_workflow_calls_keep_the_selected_model_and_bound_only_map_requests(self):
        workflow = (ROOT / ".github" / "workflows" / "main.yml").read_text(encoding="utf-8")
        agent_workflow = (ROOT / ".github" / "workflows" / "agent.yml").read_text(encoding="utf-8")
        agent_helper = (ROOT / "tools" / "nish_agent.py").read_text(encoding="utf-8")
        helper = (ROOT / "tools" / "ollama_stream.py").read_text(encoding="utf-8")
        self.assertIn("AI_STALL=900", workflow)
        self.assertIn("AI_STALL: '900'", agent_workflow)
        self.assertIn('"--stall-seconds", os.environ.get("AI_STALL", "900")', agent_helper)
        calls = workflow.count("python tools/ollama_stream.py")
        self.assertGreater(calls, 0)
        self.assertEqual(calls, workflow.count("--stall-seconds"))
        map_start = workflow.index("- name: Orchestrate and review the delegated map")
        map_end = workflow.index("- name: Re-view the AI world", map_start)
        map_step = workflow[map_start:map_end]
        self.assertIn("--max-seconds 600", map_step)
        self.assertIn("--max-seconds 300", map_step)
        for path, text in (("main.yml", workflow), ("agent.yml", agent_workflow),
                           ("nish_agent.py", agent_helper), ("ollama_stream.py", helper)):
            self.assertNotIn("--fallback-model", text, path)
            self.assertNotIn("AI_FALLBACK_MODEL", text, path)


class BlueprintSizeTests(unittest.TestCase):
    def test_the_local_model_has_a_small_orchestration_budget_and_the_helper_builds_map(self):
        workflow = (ROOT / ".github" / "workflows" / "main.yml").read_text(encoding="utf-8")
        self.assertIn("MAP_ORCHESTRATION_TOKENS=1200", workflow)
        self.assertIn("sub-agent creates the actual map, camera storyboard", workflow)
        self.assertIn("at least 8 map-only prop anchors", workflow)
        self.assertNotIn("MAP_TOKENS", workflow)

    def test_the_plan_step_reports_its_preset(self):
        workflow = (ROOT / ".github" / "workflows" / "main.yml").read_text(encoding="utf-8")
        start = workflow.index("- name: Orchestrate and review the delegated map")
        block = workflow[start:start + 900]
        self.assertIn("MODEL_QUALITY: ${{ steps.model-preset.outputs.quality }}", block)
        self.assertIn("AI_MODEL: ${{ env.AI_MODEL }}", block)


class TypingCommandLineTests(unittest.TestCase):
    def setUp(self):
        self.workflow = (ROOT / ".github" / "workflows" / "main.yml").read_text(encoding="utf-8")

    def test_the_helper_exposes_the_typing_knobs(self):
        helper = (ROOT / "tools" / "ollama_stream.py").read_text(encoding="utf-8")
        for flag in ("--type-delay", "--type-budget", "--heartbeat-seconds"):
            self.assertIn(flag, helper)
        self.assertIn("AI_TYPE_DELAY", helper)
        self.assertIn("AI_TYPE_BUDGET", helper)

    def test_the_job_unbuffers_python_and_sets_the_pace(self):
        self.assertIn("PYTHONUNBUFFERED: '1'", self.workflow)
        self.assertIn("AI_TYPE_DELAY: '0.002'", self.workflow)
        self.assertIn("AI_TYPE_BUDGET: '120'", self.workflow)
        self.assertIn("AI_HEARTBEAT: '60'", self.workflow)

    def test_it_announces_safe_progress_before_waiting(self):
        helper = (ROOT / "tools" / "ollama_stream.py").read_text(encoding="utf-8")
        self.assertIn("streaming safe progress", helper)
        self.assertIn("private reasoning and raw JSON are hidden", helper)
        self.assertIn("Validated public rationale and result fields appear when ready", helper)

class ColourTests(unittest.TestCase):
    """Every kind of AI line gets its own colour, and typing never snaps."""

    def test_colour_is_on_for_actions_even_though_it_is_not_a_tty(self):
        sys.path.insert(0, str(ROOT / "tools"))
        from console_style import CODES, ansi, paint

        os.environ["AI_COLOR"] = "1"
        self.addCleanup(os.environ.pop, "AI_COLOR", None)
        self.assertTrue(ansi("thinking"))
        self.assertIn(CODES["thinking"], paint("thinking...", "thinking"))
        self.assertNotEqual(ansi("thinking"), ansi("answer"))
        self.assertNotEqual(ansi("answer"), ansi("error"))
        self.assertNotEqual(ansi("success"), ansi("warning"))
        self.assertNotEqual(ansi("tool"), ansi("subagent"))
        for kind in ("thinking", "answer", "label", "notice", "success",
                     "warning", "error", "tool", "subagent", "plan", "thought"):
            self.assertTrue(ansi(kind), f"{kind} has no colour")

    def test_no_colour_when_switched_off_or_piped(self):
        sys.path.insert(0, str(ROOT / "tools"))
        from console_style import paint, strip

        os.environ["AI_COLOR"] = "0"
        self.addCleanup(os.environ.pop, "AI_COLOR", None)
        self.assertEqual(paint("plain", "answer"), "plain")
        os.environ.pop("AI_COLOR")
        os.environ["NO_COLOR"] = "1"
        self.addCleanup(os.environ.pop, "NO_COLOR", None)
        self.assertEqual(paint("plain", "answer"), "plain")
        self.assertEqual(strip("\x1b[38;5;51mcyan\x1b[0m"), "cyan")

    def test_thinking_and_answer_are_painted_in_different_colours(self):
        sys.path.insert(0, str(ROOT / "tools"))
        from console_style import RESET, ansi, paint
        from ollama_stream import TypedConsole

        os.environ["AI_COLOR"] = "1"
        self.addCleanup(os.environ.pop, "AI_COLOR", None)
        recorder = _Recorder()
        console = TypedConsole(delay=0, budget=0, out=recorder)
        console.line(paint("[x] thinking \u25b8", "label", bold=True))
        console.use("thinking")
        console.write("grey words")
        console.newline()
        console.line(paint("[x] answer \u25b8", "label", bold=True))
        console.use("answer")
        console.write("bright words")
        console.newline()
        text = "".join(recorder.writes)
        self.assertIn(ansi("thinking") + "grey", text)
        self.assertIn(ansi("answer") + "bright", text)
        self.assertIn(RESET, text)

    def test_the_log_still_streams_character_by_character_with_colour_on(self):
        sys.path.insert(0, str(ROOT / "tools"))
        from ollama_stream import TypedConsole

        os.environ["AI_COLOR"] = "1"
        self.addCleanup(os.environ.pop, "AI_COLOR", None)
        recorder = _Recorder()
        console = TypedConsole(delay=0, budget=0, out=recorder)
        console.use("answer")
        console.write("abcde")
        sys.path.insert(0, str(ROOT / "tools"))
        from console_style import strip

        letters = [chunk for chunk in recorder.writes if chunk and chunk != "\x1b[0m"]
        self.assertEqual(strip("".join(letters)), "abcde")
        self.assertIn("\x1b[36m", "".join(recorder.writes))
        self.assertNotIn("38;5;", "".join(recorder.writes))

    def test_the_job_turns_colour_on_and_emits_a_real_actions_probe(self):
        workflow = (ROOT / ".github" / "workflows" / "main.yml").read_text(encoding="utf-8")
        self.assertIn("AI_COLOR: '1'", workflow)
        self.assertIn("Verify ANSI colours in the Actions console", workflow)
        self.assertIn("GITHUB_ACTIONS", workflow)
        self.assertIn("CODES[kind]", workflow)
        self.assertIn("sys.stdout.isatty()", workflow)

    def test_live_subagent_answer_stream_uses_its_own_colour(self):
        helper = (ROOT / "tools" / "gemini_subagent.py").read_text(encoding="utf-8")
        self.assertIn("from console_style import paint", helper)
        self.assertIn('print(paint(line, "subagent", stream=sys.stdout), flush=True)', helper)
        self.assertIn('"tool", stream=sys.stdout), flush=True)', helper)
        self.assertIn("[subagent progress]", helper)
        self.assertIn("[subagent tool]", helper)
        self.assertNotIn('paint(f"{tag} full response for', helper)


class _AlwaysAnswers(BaseHTTPRequestHandler):
    """Answers anything, so a call's model name can be inspected."""

    models: list[str] = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length))
        type(self).models.append(str(payload.get("model")))
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        self.wfile.write((json.dumps({"message": {"content": '{"ok":1}'}, "done": False}) + "\n").encode())
        self.wfile.write((json.dumps({"done": True, "done_reason": "stop", "eval_count": 3}) + "\n").encode())


class ModelResidencyTests(unittest.TestCase):
    """The selected model stays the request model for every step in the run."""

    def test_stale_sticky_state_cannot_replace_the_requested_selected_model(self):
        import tempfile

        handler = type("Handler", (_AlwaysAnswers,), {"models": []})
        server = HTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)

        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            (workdir / ".ai_model").write_text("qwen3:4b\n", encoding="utf-8")
            github_env = workdir / "github_env"
            github_env.touch()
            environment = {**os.environ, "GITHUB_ENV": str(github_env), "AI_COLOR": "0"}
            models = ["qwen3:14b", "qwen3:8b"]
            for index, selected in enumerate(models):
                request = workdir / f"request{index}.json"
                output = workdir / f"output{index}.json"
                request.write_text(json.dumps({
                    "model": selected,
                    "messages": [{"role": "user", "content": "plan the world"}],
                    "think": True, "stream": False,
                    "options": {"num_predict": 200},
                }), encoding="utf-8")
                result = subprocess.run(
                    [sys.executable, "tools/ollama_stream.py", "--request", str(request),
                     "--output", str(output), "--label", "world plan", "--timeout", "30",
                     "--url", f"http://127.0.0.1:{server.server_port}/api/chat"],
                    cwd=ROOT, capture_output=True, text=True, env=environment,
                )
                self.assertEqual(result.returncode, 0, msg=result.stderr[-2000:])
                self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["model"], selected)
            self.assertEqual(github_env.read_text(encoding="utf-8"), "")
        self.assertEqual(handler.models, models)

    def test_the_workflow_checks_that_the_selected_model_is_still_resident(self):
        workflow = (ROOT / ".github" / "workflows" / "main.yml").read_text(encoding="utf-8")
        for label in ('"model warm-up"', '"story"', '"world plan"', '"creation summary"'):
            self.assertIn(f'python tools/model_residency.py --check --model "$AI_MODEL" --label {label}'
                          if label != '"model warm-up"'
                          else 'python tools/model_residency.py --check --model "$SELECTED_MODEL" --label "model warm-up"',
                          workflow, label)
        self.assertIn("python tools/model_residency.py --summary", workflow)

    def test_the_summary_is_written_before_the_model_is_unloaded(self):
        workflow = (ROOT / ".github/workflows/main.yml").read_text(encoding="utf-8")
        summary = workflow.index("Write the AI creation summary while the model is still in memory")
        unload = workflow.index("Free model RAM for the physics renderer")
        render = workflow.index("Render the complete vertical MP4 without Roblox Studio or Blender")
        self.assertLess(summary, unload,
                        "the last AI call must happen while the model is still warm")
        self.assertLess(unload, render)
        self.assertNotIn("ollama_stream.py", workflow[unload:render])

    def test_the_model_is_warmed_once_on_purpose(self):
        workflow = (ROOT / ".github/workflows/main.yml").read_text(encoding="utf-8")
        self.assertIn("/api/generate", workflow)
        self.assertIn("is resident after", workflow)
        self.assertIn("OLLAMA_KEEP_ALIVE=60m", workflow)

    def test_the_residency_report_names_cold_loads(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "residency.log"
            log.write_text("\n".join([
                json.dumps({"label": "story", "model": "qwen3:8b", "resident": True, "loaded": ["qwen3:8b"]}),
                json.dumps({"label": "world plan", "model": "qwen3:8b", "resident": False, "loaded": []}),
            ]) + "\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "tools/model_residency.py", "--summary", "--log", str(log)],
                cwd=ROOT, capture_output=True, text=True,
                env={k: v for k, v in os.environ.items() if k != "GITHUB_STEP_SUMMARY"},
            )
        self.assertEqual(result.returncode, 1, "a cold load must be visible, not silent")
        self.assertIn("1 of 2 AI steps ran on weights already in RAM", result.stdout)
        self.assertIn("world plan: qwen3:8b -> COLD LOAD", result.stdout)


class SelectedModelFailureTests(unittest.TestCase):
    """An unusable selected model fails clearly instead of switching to another."""

    def _run(self, handler, extra_args=()):
        import tempfile

        server = HTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            request = workdir / "request.json"
            request.write_text(json.dumps({
                "model": "qwen3:8b",
                "messages": [{"role": "user", "content": "plan the world"}],
                "think": True, "stream": False,
                "options": {"num_predict": 200},
            }), encoding="utf-8")
            environment = {**os.environ, "AI_COLOR": "0"}
            result = subprocess.run(
                [sys.executable, "tools/ollama_stream.py",
                 "--request", str(request), "--output", str(workdir / "out.json"),
                 "--label", "world plan", "--timeout", "30",
                 "--url", f"http://127.0.0.1:{server.server_port}/api/chat", *extra_args],
                cwd=ROOT, capture_output=True, text=True, env=environment,
            )
            output = workdir / "out.json"
            return result, (output.read_text(encoding="utf-8") if output.is_file() else None), list(handler.models)

    def test_model_failure_retries_only_the_selected_model_and_reports_a_clear_error(self):
        class Handler(BaseHTTPRequestHandler):
            models: list[str] = []

            def log_message(self, *args):
                pass

            def do_GET(self):
                body = json.dumps({"models": []}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length))
                type(self).models.append(str(payload.get("model")))
                body = b'{"error":"selected model cannot run"}'
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        result, output, models = self._run(Handler)
        self.assertEqual(result.returncode, 1)
        self.assertIsNone(output)
        self.assertEqual(models, ["qwen3:8b", "qwen3:8b"])
        self.assertIn("retrying the selected model qwen3:8b once", result.stdout)
        self.assertIn("selected model qwen3:8b could not continue", result.stderr)
        self.assertIn("Selected Ollama model failed", result.stderr)
        self.assertNotIn("qwen3:4b", result.stdout + result.stderr)

    def test_a_404_is_reported_as_a_missing_selected_model(self):
        # Directly: a 404 from /api/chat must raise ModelMissing, not HTTPError.
        sys.path.insert(0, str(ROOT / "tools"))
        import ollama_stream

        class FakeResponse:
            def read(self):
                return b'{"error":"model \"qwen3:8b\" not found"}'

            def close(self):
                return None

        original = ollama_stream.urllib.request.urlopen

        def fake_urlopen(request, timeout=None):
            raise ollama_stream.urllib.error.HTTPError(
                "http://127.0.0.1:1/api/chat", 404, "Not Found", {}, FakeResponse())

        ollama_stream.urllib.request.urlopen = fake_urlopen
        try:
            with self.assertRaises(ollama_stream.ModelMissing):
                ollama_stream.stream({"model": "qwen3:8b", "messages": []},
                                     "http://127.0.0.1:1/api/chat", "test", 10, True)
        finally:
            ollama_stream.urllib.request.urlopen = original
