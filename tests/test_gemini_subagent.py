"""The local model delegates text tasks through BazaarLink, Gemini and Groq.

The workflow supplies ``BAZAAR_LINK_API`` first, then ``GEMINI_API_KEY`` and
``GROQ_API_KEY`` as fallbacks. If no provider key is set, tasks are skipped.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import threading
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import gemini_subagent  # noqa: E402
from gemini_subagent import (  # noqa: E402
    build_prompt,
    normalize_request,
    parse_agent_turn,
    run_tasks,
    run_tool_agent,
    safe_target,
)

WORKFLOW = ROOT / ".github" / "workflows" / "main.yml"

# The suite must not care what the run has already written into dist/: a real
# 429 in an earlier workflow step leaves dist/gemini_quota_exhausted behind, and
# every stub-API test here would then short-circuit before reaching its server.
# Point the marker at a private temp path for the whole module.
_MODULE_MARKER_DIR = tempfile.mkdtemp(prefix="quota-marker-")
os.environ["GEMINI_QUOTA_MARKER"] = str(Path(_MODULE_MARKER_DIR) / "gemini_quota_exhausted")
# Tests always use local stubs; never let a developer's shell secret trigger a real call.
for _credential in ("BAZAAR_LINK_API", "GEMINI_API_KEY", "GROQ_API_KEY"):
    os.environ.pop(_credential, None)


class _StubGemini(BaseHTTPRequestHandler):
    calls: list[dict] = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length))
        type(self).calls.append({"key": self.headers.get("x-goog-api-key"), "payload": payload})
        prompt = payload["contents"][0]["parts"][0]["text"]
        text = "EDITED TEXT" if "Task kind: edit" in prompt else "Paris"
        body = json.dumps({"candidates": [{"content": {"parts": [{"text": text}]}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class RequestTests(unittest.TestCase):
    def test_accepts_an_envelope_or_a_bare_list(self):
        envelope = normalize_request({"context": "ctx", "tasks": [
            {"kind": "answer", "instruction": "Name a teacher"}]})
        self.assertEqual(envelope["context"], "ctx")
        self.assertEqual(envelope["tasks"][0]["kind"], "answer")

        bare = normalize_request([{"kind": "verify", "instruction": "Check this"}])
        self.assertEqual(bare["context"], "")
        self.assertEqual(bare["tasks"][0]["kind"], "verify")

    def test_unknown_kinds_fall_back_to_answer_and_empty_tasks_are_dropped(self):
        request = normalize_request({"tasks": [
            {"kind": "teleport", "instruction": "do it"},
            {"kind": "answer", "instruction": "   "},
            "not a task",
        ]})
        self.assertEqual(len(request["tasks"]), 1)
        self.assertEqual(request["tasks"][0]["kind"], "answer")

    def test_at_most_three_tasks(self):
        request = normalize_request({"tasks": [
            {"kind": "answer", "instruction": f"task {index}"} for index in range(9)]})
        self.assertEqual(len(request["tasks"]), 3)

    def test_prompt_carries_the_finished_text_rule(self):
        prompt = build_prompt({"kind": "edit", "instruction": "Cut to 200 words",
                               "input": "long draft"})
        self.assertIn("Task kind: edit", prompt)
        self.assertIn("Return only the edited text.", prompt)
        self.assertIn("long draft", prompt)

    def test_tool_enabled_subagent_gets_the_shared_visual_and_file_tools(self):
        task = normalize_request({"tasks": [{"kind": "agent", "instruction": "Inspect a supplied face photo",
                                               "topic": "faces", "input": "references/face.jpg"}]})["tasks"][0]
        prompt = build_prompt(task)
        self.assertIn("search_assets", prompt)
        self.assertIn("inspect_image", prompt)
        self.assertIn("edit_image", prompt)
        self.assertIn("YOU must author its call", prompt)
        self.assertIn("never invent or inject", prompt)
        self.assertIn("references/face.jpg", prompt)

    def test_agent_json_parser_does_not_fabricate_missing_calls(self):
        parsed = parse_agent_turn('```json\\n{"answer":"ok","tool_calls":[{"tool":"inspect_image","path":"face.jpg"}]}\\n```')
        self.assertEqual(parsed["tool_calls"], [{"tool": "inspect_image", "path": "face.jpg"}])
        plain = parse_agent_turn("No tool call was authored.")
        self.assertEqual(plain["tool_calls"], [])

    def test_subagent_executes_only_tool_calls_present_in_its_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "reference.txt").write_text("bold dark brows", encoding="utf-8")
            first = json.dumps({"answer": "I will inspect the supplied reference.",
                                "tool_calls": [{"tool": "read_file", "path": "reference.txt"}]})
            final = json.dumps({"answer": "The reference has bold dark brows.", "tool_calls": []})
            with patch("gemini_subagent.call_any", side_effect=[(first, "gemini"), (final, "groq")]) as mocked:
                result = run_tool_agent(
                    {"kind": "agent", "instruction": "Inspect the supplied reference", "input": "reference.txt"},
                    "", model="gemini-2.5-flash", api_key="key", groq_key="key",
                    groq_model_name="", root=root, timeout=1)
            self.assertEqual(mocked.call_count, 2)
            self.assertEqual(result["text"], "The reference has bold dark brows.")
            self.assertEqual([call["tool"] for call in result["tool_calls"]], ["read_file"])
            self.assertEqual(result["tool_results"][0]["result"]["content"], "bold dark brows")

    def test_subagent_reprompts_until_it_authors_the_supplied_image_inspection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "references").mkdir()
            (root / "references" / "face.jpg").write_bytes(b"fixture")
            no_call = json.dumps({"answer": "I inspected the face.", "tool_calls": []})
            inspect = json.dumps({"answer": "I will inspect the face now.", "tool_calls": [
                {"tool": "inspect_image", "arguments": {"path": "references/face.jpg"}}]})
            final = json.dumps({"answer": "The reference has bold dark eyebrows.", "tool_calls": []})
            with patch("gemini_subagent.call_any", side_effect=[(no_call, "gemini"),
                                                                (inspect, "groq"),
                                                                (final, "gemini")]) as mocked, \
                    patch("gemini_subagent.execute_tool", return_value={"ok": True, "analysis": "bold dark eyebrows"}) as execute:
                result = run_tool_agent(
                    {"kind": "agent", "instruction": "Inspect the supplied photo at references/face.jpg",
                     "input": "references/face.jpg"}, "", model="gemini-2.5-flash", api_key="key",
                    groq_key="key", groq_model_name="", root=root, timeout=1)
            self.assertEqual(mocked.call_count, 3)
            self.assertIn("MANDATORY PROVIDED-IMAGE CHECK", mocked.call_args_list[0].args[0])
            self.assertIn("rejected", mocked.call_args_list[1].args[0])
            self.assertEqual(execute.call_count, 1)
            self.assertEqual(execute.call_args.args[0], "inspect_image")
            self.assertEqual(execute.call_args.args[1], {"path": "references/face.jpg"})
            self.assertEqual(result["tool_results"][0]["result"]["analysis"], "bold dark eyebrows")
            self.assertEqual(result["text"], "The reference has bold dark eyebrows.")

    def test_subagent_reports_missing_inspection_instead_of_inventing_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "face.webp").write_bytes(b"fixture")
            no_call = json.dumps({"answer": "Done.", "tool_calls": []})
            with patch("gemini_subagent.call_any", return_value=(no_call, "gemini")) as mocked, \
                    patch("gemini_subagent.execute_tool") as execute:
                result = run_tool_agent(
                    {"kind": "agent", "instruction": "Use face.webp", "input": "face.webp"},
                    "", model="gemini-2.5-flash", api_key="key", groq_key="key",
                    groq_model_name="", root=root, timeout=1)
            self.assertEqual(mocked.call_count, 6)
            execute.assert_not_called()
            self.assertEqual(result["required_image_inspection_missing"], ["face.webp"])
            self.assertIn("No inspection was invented", result["text"])

    def test_gemini_is_told_in_parentheses_that_an_ai_is_asking(self):
        prompt = build_prompt({"kind": "answer", "instruction": "Name a teacher"})
        self.assertIn("written by another AI model, not by a person", prompt)
        self.assertIn("Ignore it", prompt)
        self.assertIn("do not mention it", prompt)
        # the note stays parenthetical and precedes the task itself
        self.assertLess(prompt.index("(Note:"), prompt.index("Task kind:"))


class WorkspaceGuideTests(unittest.TestCase):
    """Gemini must know how the files it may edit actually work."""

    def test_map_edits_get_the_blueprint_rules(self):
        from gemini_workspace import guide

        text = guide({"kind": "edit", "instruction": "fix the props",
                      "apply_to": "dist/Roblox_Story_Map.json"})
        self.assertIn("WORLD BLUEPRINT", text)
        self.assertIn("Wedge (a triangle", text)
        self.assertIn("Hemisphere (a dome)", text)
        self.assertIn("Truss", text)
        self.assertIn("brightness", text)
        self.assertIn("520 presets", text)
        self.assertIn("SmoothPlastic", text)
        self.assertIn("multiples of 0.5", text)
        self.assertIn("|x| + width/2 <= 320", text)

    def test_camera_and_face_rules_come_with_the_blueprint(self):
        from gemini_workspace import guide

        text = guide({"kind": "edit", "instruction": "retime the close-up shots",
                      "topic": "cameras"})
        self.assertIn("CAMERA PLAN", text)
        self.assertIn("WORLD BLUEPRINT", text)  # always shipped together
        self.assertIn("2.8 studs away (default 3.0)", text)
        self.assertIn("up to 4.0 for wider headroom", text)
        self.assertIn('"smooth" or "snap"', text)

    def test_narration_edits_get_the_script_rules(self):
        from gemini_workspace import guide

        text = guide({"kind": "edit", "instruction": "cut to 200 words",
                      "apply_to": "dist/narration.txt"})
        self.assertIn("NARRATION TEXT", text)
        self.assertIn("half sentence", text)

    def test_code_and_model_rules(self):
        from gemini_workspace import guide

        code = guide({"kind": "code", "instruction": "write a tool to count props",
                      "topic": "code"})
        self.assertIn("Python 3.11", code)
        self.assertIn("if __name__", code)
        models = guide({"kind": "answer", "instruction": "what mesh format is users/normal.obj",
                        "topic": "models"})
        self.assertIn("AVATAR MODELS", models)
        self.assertIn("never invent a mesh", models)

    def test_every_file_task_is_told_to_return_the_whole_file(self):
        from gemini_workspace import guide

        text = guide({"kind": "edit", "instruction": "tidy the animation",
                      "apply_to": "dist/animation.json"})
        self.assertIn("HOW TO CHANGE FILES", text)
        self.assertIn("Return the complete file, never a diff", text)
        self.assertIn("R15 ANIMATION TRACK", text)

    def test_a_path_does_not_drag_in_unrelated_rules(self):
        from gemini_workspace import topics_for

        # "Story" is in the file name, but a camera edit must not get the narration
        # rules, and a narration edit must not get the camera rules.
        self.assertEqual(
            topics_for({"kind": "edit", "instruction": "retime the face beats",
                        "apply_to": "dist/Roblox_Story_Map.json"}),
            ["map", "cameras", "faces"])
        self.assertEqual(
            topics_for({"kind": "edit", "instruction": "cut to 200 words",
                        "apply_to": "dist/narration.txt"}), ["narration"])

    def test_the_console_says_which_rules_were_attached(self):
        helper = (ROOT / "tools" / "gemini_subagent.py").read_text(encoding="utf-8")
        self.assertIn("giving it the file rules", helper)

    def test_a_plain_question_gets_no_file_manual(self):
        from gemini_workspace import guide

        self.assertEqual(guide({"kind": "answer", "instruction": "capital of France?"}), "")

    def test_the_prompt_carries_the_manual_and_names_the_file(self):
        prompt = build_prompt({"kind": "edit", "instruction": "fix the camera shots",
                               "apply_to": "dist/Roblox_Story_Map.json"})
        self.assertIn("REFERENCE FOR THE FILES IN THIS REPOSITORY", prompt)
        self.assertIn("This answer replaces the file dist/Roblox_Story_Map.json.", prompt)
        self.assertIn("complete new file contents", prompt)

    def test_the_local_ai_can_name_the_topic(self):
        from gemini_subagent import normalize_request

        task = normalize_request({"tasks": [
            {"kind": "edit", "instruction": "x", "topic": "Cameras"}]})["tasks"][0]
        self.assertEqual(task["topic"], "cameras")


class SafetyTests(unittest.TestCase):
    def test_only_writes_inside_the_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertIsNone(safe_target("/etc/passwd", root))
            self.assertIsNone(safe_target("../outside.txt", root))
            self.assertEqual(safe_target("dist/narration.txt", root),
                             (root / "dist" / "narration.txt").resolve())


class StubApiTests(unittest.TestCase):
    def setUp(self):
        handler = type("Handler", (_StubGemini,), {"calls": []})
        self.server = HTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)
        self.addCleanup(self.server.server_close)
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1beta/models/x:generateContent"
        self.handler = handler

    def test_edit_is_applied_and_answer_is_returned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "dist").mkdir()
            (root / "dist" / "narration.txt").write_text("too long\n", encoding="utf-8")
            result = run_tasks({"context": "story", "tasks": [
                {"id": "e1", "kind": "edit", "instruction": "Cut it down",
                 "input": "draft", "apply_to": "dist/narration.txt"},
                {"id": "q1", "kind": "answer", "instruction": "Capital of France?"},
            ]}, api_key="k-test", model="gemini-2.5-flash", root=root, url=self.url)
            self.assertFalse(result["skipped"])
            self.assertEqual([entry["ok"] for entry in result["results"]], [True, True])
            self.assertEqual(result["results"][0]["applied_to"], "dist/narration.txt")
            self.assertEqual((root / "dist" / "narration.txt").read_text(encoding="utf-8").strip(),
                             "EDITED TEXT")
            self.assertEqual(result["results"][1]["text"], "Paris")

    def test_the_key_is_sent_as_a_header_not_in_the_url(self):
        run_tasks({"tasks": [{"kind": "answer", "instruction": "hi"}]},
                  api_key="secret-key", model="m", root=Path("."), url=self.url)
        self.assertEqual(self.handler.calls[0]["key"], "secret-key")
        self.assertNotIn("secret-key", self.url)

    def test_missing_key_skips_everything_without_failing(self):
        result = run_tasks({"tasks": [{"kind": "answer", "instruction": "hi"}]},
                           api_key="", model="m", root=Path("."), url=self.url)
        self.assertTrue(result["skipped"])
        self.assertFalse(result["results"][0]["ok"])
        self.assertEqual(self.handler.calls, [])


class CommandLineTests(unittest.TestCase):
    def _run(self, request, env=None, tmp=None):
        tmp = Path(tmp)
        (tmp / "request.json").write_text(json.dumps(request), encoding="utf-8")
        base_env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PYTHONPATH": str(ROOT)}
        base_env.update(env or {})
        return subprocess.run(
            [sys.executable, str(ROOT / "tools" / "gemini_subagent.py"),
             "--request", "request.json", "--output", "results.json"],
            cwd=tmp, capture_output=True, text=True, env=base_env,
        )

    def test_no_key_is_a_clean_no_op(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run({"tasks": [{"kind": "answer", "instruction": "hi"}]},
                               env={}, tmp=tmp)
            self.assertEqual(result.returncode, 0, msg=result.stderr[-1500:])
            data = json.loads((Path(tmp) / "results.json").read_text(encoding="utf-8"))
            self.assertTrue(data["skipped"])
            self.assertIn("none of BAZAAR_LINK_API, GEMINI_API_KEY or GROQ_API_KEY is configured",
                          result.stdout)

    def test_empty_task_list_is_fine(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run({"tasks": []}, env={}, tmp=tmp)
            self.assertEqual(result.returncode, 0)
            data = json.loads((Path(tmp) / "results.json").read_text(encoding="utf-8"))
            self.assertEqual(data["results"], [])


class WorkflowWiringTests(unittest.TestCase):
    def setUp(self):
        self.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_secret_and_variable_are_documented_names(self):
        self.assertIn("BAZAAR_LINK_API: ${{ secrets.BAZAAR_LINK_API }}", self.workflow)
        self.assertIn("GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}", self.workflow)
        self.assertIn("GEMINI_MODEL: ${{ vars.GEMINI_MODEL }}", self.workflow)
        self.assertIn("Text provider order: BazaarLink auto:free, Gemini, then Groq.",
                      self.workflow)

    def test_local_ai_can_delegate_in_the_story_and_the_plan(self):
        self.assertIn("YOU HAVE A GEMINI SUB-AGENT", self.workflow)
        self.assertIn("subagent_tasks", self.workflow)
        self.assertGreaterEqual(self.workflow.count("tools/gemini_subagent.py"), 2)

    def test_answers_are_fed_back_and_help_rounds_are_capped(self):
        self.assertIn("Answers the Gemini sub-agent returned for the tasks you delegated", self.workflow)
        self.assertIn("for helper_round in 1 2 3 4; do", self.workflow)
        self.assertIn('if [ "$HELP_SIG" = "$PREVIOUS_HELP" ]; then', self.workflow)

    def test_local_ai_is_told_to_use_it_at_least_once_or_twice(self):
        self.assertIn("YOU SHOULD ACTUALLY USE IT", self.workflow)
        self.assertIn("USE IT AT LEAST ONCE OR TWICE", self.workflow)
        self.assertIn("put the task(s) in your first response", self.workflow)

    def test_bazaar_replies_are_quiet_while_fallbacks_remain_visible(self):
        helper = (ROOT / "tools" / "gemini_subagent.py").read_text(encoding="utf-8")
        self.assertIn("reply to {task['id']}", helper)
        self.assertIn("full answer for {entry['id']}", helper)
        self.assertIn('entry.get("provider") != "bazaarlink"', helper)
        self.assertIn('entry.get("provider") == "bazaarlink"', helper)
        self.assertIn("GITHUB_STEP_SUMMARY", helper)

    def test_gemini_can_edit_the_narration_to_length(self):
        self.assertIn("narration_edit_tasks.json", self.workflow)
        self.assertIn("'kind': 'edit'", self.workflow)
        self.assertIn("'apply_to': 'dist/narration.txt'", self.workflow)
        self.assertIn("edited the narration to the right length", self.workflow)

    def test_plan_schema_allows_delegation(self):
        from plan_schema import build_schema

        schema = build_schema(["normal"])
        self.assertIn("subagent_tasks", schema["properties"])
        kinds = schema["properties"]["subagent_tasks"]["items"]["properties"]["kind"]["enum"]
        self.assertEqual(kinds, ["edit", "answer", "verify", "code", "name"])


if __name__ == "__main__":
    unittest.main()


class _TruncatingGemini(BaseHTTPRequestHandler):
    """Hands back a half-finished reply the first time, like the real cut-off did."""

    calls: list[dict] = []
    plan: list[str] = []          # finishReason per call, e.g. ["MAX_TOKENS", "STOP"]

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length))
        type(self).calls.append(payload)
        index = len(type(self).calls) - 1
        plan = type(self).plan or ["STOP"]
        reason = plan[index] if index < len(plan) else plan[-1]
        text = "First half of the story, then it stops mid-sentence" if reason == "MAX_TOKENS" \
            else "The complete narration, every word of it."
        body = json.dumps({"candidates": [{"content": {"parts": [{"text": text}]},
                                           "finishReason": reason}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class TruncationTests(unittest.TestCase):
    """A half-written edit must never be written over the narration."""

    def _server(self, plan):
        handler = type("Handler", (_TruncatingGemini,), {"calls": [], "plan": plan})
        server = HTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        return handler, f"http://127.0.0.1:{server.server_port}/v1beta/models/x:generateContent"

    def test_a_cut_off_reply_is_retried_with_a_bigger_ceiling(self):
        handler, url = self._server(["MAX_TOKENS", "STOP"])
        result = run_tasks({"tasks": [{"kind": "answer", "instruction": "write it"}]},
                           api_key="k", model="gemini-2.5-flash", root=Path("."), url=url)
        self.assertTrue(result["results"][0]["ok"])
        self.assertEqual(result["results"][0]["text"], "The complete narration, every word of it.")
        first, second = handler.calls[0]["generationConfig"], handler.calls[1]["generationConfig"]
        self.assertGreater(second["maxOutputTokens"], first["maxOutputTokens"])

    def test_a_reply_that_never_stops_is_reported_not_applied(self):
        handler, url = self._server(["MAX_TOKENS"])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "dist").mkdir()
            narration = root / "dist" / "narration.txt"
            narration.write_text("a complete draft that works\n", encoding="utf-8")
            result = run_tasks({"tasks": [{"kind": "edit", "instruction": "shorten",
                                           "input": "draft",
                                           "apply_to": "dist/narration.txt"}]},
                               api_key="k", model="gemini-2.5-flash", root=root, url=url)
            self.assertFalse(result["results"][0]["ok"])
            self.assertIn("cut off", result["results"][0]["error"])
            self.assertEqual(narration.read_text(encoding="utf-8"),
                             "a complete draft that works\n")

    def test_thinking_is_switched_off_so_the_budget_goes_on_the_words(self):
        handler, url = self._server(["STOP"])
        run_tasks({"tasks": [{"kind": "edit", "instruction": "shorten"}]},
                  api_key="k", model="gemini-2.5-flash", root=Path("."), url=url)
        config = handler.calls[0]["generationConfig"]
        self.assertEqual(config["thinkingConfig"], {"thinkingBudget": 0})
        self.assertGreaterEqual(config["maxOutputTokens"], 4096)

    def test_a_model_without_thinking_control_is_not_sent_the_setting(self):
        handler, url = self._server(["STOP"])
        run_tasks({"tasks": [{"kind": "answer", "instruction": "hi"}]},
                  api_key="k", model="gemini-1.5-flash", root=Path("."), url=url)
        self.assertNotIn("thinkingConfig", handler.calls[0]["generationConfig"])


class WorkflowWiringTests(unittest.TestCase):
    def setUp(self):
        self.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_the_delegation_block_can_actually_run(self):
        # It used os.environ without importing os, so the task file was never
        # written and every delegated task was silently dropped.
        start = self.workflow.index("python - <<'PYD' || true")
        block = self.workflow[start:self.workflow.index("\n          PYD", start)]
        self.assertIn("import os", block)
        self.assertIn("story_subagent_tasks.json", block)

    def test_the_gemini_edit_cannot_overwrite_a_good_draft(self):
        self.assertIn("'apply_to': 'dist/narration_gemini.txt'", self.workflow)
        # dist/narration.txt is only replaced after the word-count gate passes.
        gate = self.workflow.index("Gemini edit result")
        move = self.workflow.index("mv dist/narration_gemini.txt dist/narration.txt")
        self.assertLess(gate, move)


class SubAgentIsOptionalTests(unittest.TestCase):
    """The sub-agent is a helper the AI can reach for, not a chore per run."""

    def setUp(self):
        self.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_the_narration_prompt_is_an_offer_not_an_order(self):
        self.assertIn("YOU HAVE A GEMINI SUB-AGENT AND YOU CAN USE IT ONE OR TWO TIMES", self.workflow)
        self.assertIn("There is no quota and no rule that you must ask", self.workflow)
        self.assertIn('if you can write the story yourself, just write it and return '
                      '"subagent_tasks":[]', self.workflow)

    def test_it_says_when_asking_helps(self):
        self.assertIn("beyond you or you are unsure", self.workflow)
        self.assertIn("cutting a draft down to the exact word count", self.workflow)
        self.assertIn("expanding one that came out short", self.workflow)

    def test_no_mandate_is_left_in_either_prompt(self):
        self.assertNotIn("NEVER RETURN AN EMPTY", self.workflow)
        self.assertNotIn("YOU MUST USE THE GEMINI SUB-AGENT", self.workflow)

    def test_the_schema_does_not_force_a_task_list(self):
        self.assertEqual(self.workflow.count('required:["narration","subagent_tasks"]'), 0)

    def test_a_model_that_asks_for_nothing_gets_no_invented_task(self):
        start = self.workflow.index("python - <<'PYD' || true")
        block = self.workflow[start:self.workflow.index("\n          PYD", start)]
        script = "\n".join(line[10:] for line in block.splitlines()[1:])
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            (work / "narration_response.json").write_text(json.dumps({
                "message": {"content": json.dumps({"narration": "Max slept in.",
                                                   "subagent_tasks": []})},
            }), encoding="utf-8")
            result = subprocess.run([sys.executable, "-"], input=script, text=True,
                                    capture_output=True, cwd=work,
                                    env={**os.environ, "DURATION_SECONDS": "133"})
            self.assertEqual(result.returncode, 0, result.stderr)
            written = json.loads((work / "story_subagent_tasks.json").read_text(encoding="utf-8"))
            self.assertEqual(written["tasks"], [])
            self.assertIn("did not need the sub-agent", result.stdout)

    def test_a_model_that_asks_for_help_is_obeyed(self):
        start = self.workflow.index("python - <<'PYD' || true")
        block = self.workflow[start:self.workflow.index("\n          PYD", start)]
        script = "\n".join(line[10:] for line in block.splitlines()[1:])
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            (work / "narration_response.json").write_text(json.dumps({
                "message": {"content": json.dumps({
                    "narration": "Max slept in.",
                    "subagent_tasks": [{"id": "t1", "kind": "name",
                                        "instruction": "Does Max sound real?"}]})},
            }), encoding="utf-8")
            subprocess.run([sys.executable, "-"], input=script, text=True, capture_output=True,
                           cwd=work, env={**os.environ, "DURATION_SECONDS": "133"})
            written = json.loads((work / "story_subagent_tasks.json").read_text(encoding="utf-8"))
            self.assertEqual([task["id"] for task in written["tasks"]], ["t1"])


_QUOTA_MARKER_ENV = "GEMINI_QUOTA_MARKER"


class _QuotaGemini(BaseHTTPRequestHandler):
    """Refuses every call the way a free key out of quota does."""

    calls: list[dict] = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        type(self).calls.append({"at": time.monotonic()})
        body = json.dumps({"error": {"code": 429, "status": "RESOURCE_EXHAUSTED",
                                     "message": "You exceeded your current quota"}}).encode()
        self.send_response(429)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class QuotaTests(unittest.TestCase):
    """A 429 must cost one request, not a retry storm, and never fail the run."""

    def setUp(self):
        # The marker goes to a temp path: a stray dist/gemini_quota_exhausted in the
        # repository would make every later test believe the quota was already gone.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.marker = Path(tmp.name) / "gemini_quota_exhausted"
        previous = os.environ.get(_QUOTA_MARKER_ENV)
        os.environ[_QUOTA_MARKER_ENV] = str(self.marker)
        self.addCleanup(lambda: os.environ.pop(_QUOTA_MARKER_ENV, None) if previous is None
                        else os.environ.__setitem__(_QUOTA_MARKER_ENV, previous))
        handler = type("Handler", (_QuotaGemini,), {"calls": []})
        self.server = HTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)
        self.addCleanup(self.server.server_close)
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1beta/models/x:generateContent"
        self.handler = handler

    def test_a_429_stops_at_once_and_leaves_a_marker(self):
        started = time.monotonic()
        result = run_tasks({"tasks": [
            {"id": "t1", "kind": "answer", "instruction": "one"},
            {"id": "t2", "kind": "answer", "instruction": "two"},
        ]}, api_key="k", model="m", root=Path("."), url=self.url)
        self.assertLess(time.monotonic() - started, 20, "429 must not be retried with sleeps")
        self.assertEqual(len(self.handler.calls), 1, "only the first task may hit the API")
        self.assertTrue(result["quota_exhausted"])
        self.assertEqual([entry["ok"] for entry in result["results"]], [False, False])
        self.assertIn("quota", result["results"][0]["error"])
        self.assertTrue(self.marker.is_file())

    def test_later_requests_do_not_touch_the_network(self):
        run_tasks({"tasks": [{"kind": "answer", "instruction": "one"}]},
                  api_key="k", model="m", root=Path("."), url=self.url)
        self.assertEqual(len(self.handler.calls), 1)
        again = run_tasks({"tasks": [{"kind": "answer", "instruction": "two"}]},
                          api_key="k", model="m", root=Path("."), url=self.url)
        self.assertEqual(len(self.handler.calls), 1, "the marker must short-circuit it")
        self.assertTrue(again["quota_exhausted"])

    def test_the_command_line_still_exits_zero(self):
        request = self.marker.parent / "request.json"
        request.write_text(json.dumps({"tasks": [{"kind": "answer", "instruction": "x"}]}),
                           encoding="utf-8")
        output = self.marker.parent / "out.json"
        proc = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "gemini_subagent.py"),
             "--request", str(request), "--output", str(output), "--url", self.url],
            cwd=self.marker.parent, env={**os.environ, "GEMINI_API_KEY": "k"},
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr[-800:])
        self.assertIn("quota", proc.stdout.lower())
        self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["quota_exhausted"], True)


class QuotaWorkflowTests(unittest.TestCase):
    def test_the_workflow_fails_if_no_fallback_can_run_required_ai_authored_tasks(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("Path('dist/gemini_quota_exhausted').is_file()", text)
        self.assertIn("cannot execute the AI-authored mandatory map sub-agent calls", text)
        self.assertIn("Neither BazaarLink, Gemini nor the Groq fallback edited the narration", text)
        self.assertNotIn("skipped and the plan you already wrote stands", text)


class StaleMarkerTests(unittest.TestCase):
    """A marker from yesterday must not switch the sub-agent off today."""

    def test_an_old_marker_is_ignored_and_removed(self):
        import gemini_subagent
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "m"
            marker.write_text("old", encoding="utf-8")
            old = time.time() - (gemini_subagent.QUOTA_MARKER_HOURS + 1) * 3600
            os.utime(marker, (old, old))
            previous = os.environ.get(_QUOTA_MARKER_ENV)
            os.environ[_QUOTA_MARKER_ENV] = str(marker)
            try:
                self.assertFalse(gemini_subagent.quota_is_exhausted())
                self.assertFalse(marker.exists())
            finally:
                if previous is None:
                    os.environ.pop(_QUOTA_MARKER_ENV, None)
                else:
                    os.environ[_QUOTA_MARKER_ENV] = previous


class _GroqStub(BaseHTTPRequestHandler):
    """An OpenAI-compatible Groq endpoint with per-model failure/length controls."""

    calls: list[dict] = []
    text = "GROQ ANSWER"
    status = 200
    status_by_model: dict[str, int] = {}
    text_by_model: dict[str, str] = {}
    finish_by_model: dict[str, str] = {}

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length))
        model = payload.get("model")
        type(self).calls.append({"model": model,
                                 "auth": self.headers.get("Authorization"),
                                 "prompt": payload["messages"][0]["content"],
                                 "max_tokens": payload.get("max_tokens")})
        status = type(self).status_by_model.get(model, type(self).status)
        if status != 200:
            message = "rate limit reached" if status == 429 else "model_not_found"
            body = json.dumps({"error": {"message": message}}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        text = type(self).text_by_model.get(model, type(self).text)
        finish = type(self).finish_by_model.get(model, "stop")
        body = json.dumps({"choices": [{"message": {"content": text},
                                        "finish_reason": finish}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _BazaarStub(BaseHTTPRequestHandler):
    """Quiet OpenAI-compatible endpoint with controllable errors and finish reasons."""

    calls: list[dict] = []
    status = 200
    text = "BAZAAR ANSWER"
    finish_reason = "stop"
    error_message = "upstream unavailable"
    status_by_call: dict[int, int] = {}
    text_by_call: dict[int, str | None] = {}
    finish_by_call: dict[int, str] = {}

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length))
        index = len(type(self).calls)
        type(self).calls.append({
            "auth": self.headers.get("Authorization"),
            "path": self.path,
            "model": payload.get("model"),
            "prompt": payload.get("messages", [{}])[0].get("content"),
            "max_tokens": payload.get("max_tokens"),
            "stream": payload.get("stream"),
        })
        status = type(self).status_by_call.get(index, type(self).status)
        if status != 200:
            body = json.dumps({"error": {"message": type(self).error_message}}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        text = type(self).text_by_call.get(index, type(self).text)
        finish = type(self).finish_by_call.get(index, type(self).finish_reason)
        body = json.dumps({"choices": [{"message": {"content": text},
                                        "finish_reason": finish}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class BazaarLinkFallbackTests(unittest.TestCase):
    """BazaarLink is the quiet primary, with Gemini and Groq as ordered fallbacks."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.marker = Path(tmp.name) / "gemini_quota_exhausted"
        previous = os.environ.get(_QUOTA_MARKER_ENV)
        os.environ[_QUOTA_MARKER_ENV] = str(self.marker)
        self.addCleanup(lambda: os.environ.pop(_QUOTA_MARKER_ENV, None) if previous is None
                        else os.environ.__setitem__(_QUOTA_MARKER_ENV, previous))

        self.bazaar = type("B", (_BazaarStub,), {"calls": []})
        self.bazaar_server = HTTPServer(("127.0.0.1", 0), self.bazaar)
        threading.Thread(target=self.bazaar_server.serve_forever, daemon=True).start()
        self.addCleanup(self.bazaar_server.shutdown)
        self.addCleanup(self.bazaar_server.server_close)
        self.bazaar_url = f"http://127.0.0.1:{self.bazaar_server.server_port}/v1/chat/completions"

        self.gemini = type("G", (_StubGemini,), {"calls": []})
        self.gemini_server = HTTPServer(("127.0.0.1", 0), self.gemini)
        threading.Thread(target=self.gemini_server.serve_forever, daemon=True).start()
        self.addCleanup(self.gemini_server.shutdown)
        self.addCleanup(self.gemini_server.server_close)
        self.gemini_url = f"http://127.0.0.1:{self.gemini_server.server_port}/x"

        self.quota_gemini = type("Q", (_QuotaGemini,), {"calls": []})
        self.quota_server = HTTPServer(("127.0.0.1", 0), self.quota_gemini)
        threading.Thread(target=self.quota_server.serve_forever, daemon=True).start()
        self.addCleanup(self.quota_server.shutdown)
        self.addCleanup(self.quota_server.server_close)
        self.quota_url = f"http://127.0.0.1:{self.quota_server.server_port}/x"

        self.groq = type("R", (_GroqStub,), {"calls": [], "status": 200,
                                             "text": "GROQ ANSWER"})
        self.groq_server = HTTPServer(("127.0.0.1", 0), self.groq)
        threading.Thread(target=self.groq_server.serve_forever, daemon=True).start()
        self.addCleanup(self.groq_server.shutdown)
        self.addCleanup(self.groq_server.server_close)
        self.groq_url = f"http://127.0.0.1:{self.groq_server.server_port}/chat"

    def _run(self, *, bazaar_key="bazaar-secret", api_key="gemini-secret", groq_key="",
             **overrides):
        kwargs = {
            "bazaar_key": bazaar_key,
            "bazaar_url": self.bazaar_url,
            "api_key": api_key,
            "model": "m",
            "root": Path("."),
            "url": self.gemini_url,
            "groq_key": groq_key,
            "groq_url": self.groq_url,
        }
        kwargs.update(overrides)
        return run_tasks({"tasks": [{"id": "t1", "kind": "answer",
                                     "instruction": "Answer the question completely."}]},
                         **kwargs)

    def test_bazaarlink_is_first_and_uses_the_requested_openai_route(self):
        result = self._run(api_key="gemini-secret", groq_key="groq-secret")
        self.assertEqual(gemini_subagent.BAZAAR_LINK_ENDPOINT,
                         "https://api.bazaarlink.ai/v1/chat/completions")
        self.assertEqual(gemini_subagent.BAZAAR_LINK_MODEL, "auto:free")
        self.assertEqual(result["providers"], ["bazaarlink"])
        self.assertEqual(result["results"][0]["text"], "BAZAAR ANSWER")
        self.assertEqual(self.bazaar.calls[0]["auth"], "Bearer bazaar-secret")
        self.assertEqual(self.bazaar.calls[0]["model"], "auto:free")
        self.assertEqual(self.bazaar.calls[0]["path"], "/v1/chat/completions")
        self.assertEqual(self.bazaar.calls[0]["stream"], False)
        self.assertEqual(self.gemini.calls, [])
        self.assertEqual(self.groq.calls, [])

    def test_legacy_groq_preference_cannot_change_the_provider_order(self):
        text, provider = gemini_subagent.call_any(
            "quiet test", bazaar_key="bazaar-secret", bazaar_url=self.bazaar_url,
            gemini_key="gemini-secret", groq_key="groq-secret",
            groq_url=self.groq_url, prefer="groq")
        self.assertEqual((text, provider), ("BAZAAR ANSWER", "bazaarlink"))
        self.assertEqual(self.gemini.calls, [])
        self.assertEqual(self.groq.calls, [])

    def test_missing_bazaar_credentials_fall_through_to_gemini(self):
        result = self._run(bazaar_key="")
        self.assertEqual(result["providers"], ["gemini"])
        self.assertEqual(result["results"][0]["text"], "Paris")
        self.assertEqual(self.bazaar.calls, [])
        self.assertEqual(len(self.gemini.calls), 1)

    def test_provider_error_falls_through_without_logging_the_error_body(self):
        self.bazaar.status = 503
        self.bazaar.error_message = "must-not-appear-in-logs"
        result = self._run()
        self.assertEqual(result["providers"], ["gemini"])
        self.assertEqual(result["results"][0]["text"], "Paris")
        self.assertEqual(len(self.bazaar.calls), 1)
        self.assertEqual(len(self.gemini.calls), 1)

    def test_empty_response_falls_through_to_gemini(self):
        self.bazaar.text_by_call = {0: "   "}
        result = self._run()
        self.assertEqual(result["providers"], ["gemini"])
        self.assertEqual(result["results"][0]["text"], "Paris")
        self.assertEqual(len(self.bazaar.calls), 1)
        self.assertEqual(len(self.gemini.calls), 1)

    def test_truncated_response_falls_through_without_returning_partial_text(self):
        self.bazaar.text = "PARTIAL BAZAAR ANSWER"
        self.bazaar.finish_reason = "length"
        result = self._run()
        self.assertEqual(result["providers"], ["gemini"])
        self.assertEqual(result["results"][0]["text"], "Paris")
        self.assertEqual(len(self.bazaar.calls), 1)
        self.assertEqual(self.bazaar.calls[0]["max_tokens"], 8192)

    def test_gemini_error_after_bazaar_falls_through_to_groq(self):
        self.bazaar.status = 503
        result = self._run(url=self.quota_url, groq_key="groq-secret")
        self.assertEqual(result["providers"], ["groq"])
        self.assertEqual(result["results"][0]["text"], "GROQ ANSWER")
        self.assertEqual(len(self.bazaar.calls), 1)
        self.assertEqual(len(self.quota_gemini.calls), 1)
        self.assertEqual(len(self.groq.calls), 1)

    def test_bazaar_credentials_are_read_from_the_named_environment_secret(self):
        with patch.dict(os.environ, {"BAZAAR_LINK_API": "environment-secret",
                                     "GROQ_API_KEY": ""}):
            result = run_tasks({"tasks": [{"kind": "answer", "instruction": "hi"}]},
                               api_key="", model="m", root=Path("."),
                               bazaar_url=self.bazaar_url)
        self.assertEqual(result["providers"], ["bazaarlink"])
        self.assertEqual(self.bazaar.calls[0]["auth"], "Bearer environment-secret")
        self.assertNotIn("environment-secret", self.bazaar.calls[0]["path"])

    def test_cli_returns_bazaar_text_to_the_caller_but_omits_it_from_logs_and_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request = root / "request.json"
            output = root / "results.json"
            summary = root / "step-summary.md"
            request.write_text(json.dumps({"tasks": [{"kind": "answer",
                                                        "instruction": "Answer quietly."}]}),
                               encoding="utf-8")
            env = {**os.environ, "BAZAAR_LINK_API": "bazaar-secret",
                   "GITHUB_STEP_SUMMARY": str(summary), "PYTHONPATH": str(ROOT)}
            env.pop("GEMINI_API_KEY", None)
            env.pop("GROQ_API_KEY", None)
            proc = subprocess.run(
                [sys.executable, str(ROOT / "tools" / "gemini_subagent.py"),
                 "--request", str(request), "--output", str(output), "--stdout",
                 "--bazaar-url", self.bazaar_url],
                cwd=root, capture_output=True, text=True, env=env)
            self.assertEqual(proc.returncode, 0, msg=proc.stderr[-1000:])
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result["results"][0]["text"], "BAZAAR ANSWER")
            self.assertEqual(result["results"][0]["provider"], "bazaarlink")
            visible = proc.stdout + proc.stderr + summary.read_text(encoding="utf-8")
            self.assertNotIn("BAZAAR ANSWER", visible)
            self.assertNotIn("bazaar-secret", visible)


class GroqFallbackTests(unittest.TestCase):
    """When BazaarLink and Gemini fail, Groq does the job."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.marker = Path(tmp.name) / "gemini_quota_exhausted"
        previous = os.environ.get(_QUOTA_MARKER_ENV)
        os.environ[_QUOTA_MARKER_ENV] = str(self.marker)
        self.addCleanup(lambda: os.environ.pop(_QUOTA_MARKER_ENV, None) if previous is None
                        else os.environ.__setitem__(_QUOTA_MARKER_ENV, previous))
        self.gemini = type("G", (_QuotaGemini,), {"calls": []})
        self.server = HTTPServer(("127.0.0.1", 0), self.gemini)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)
        self.addCleanup(self.server.server_close)
        self.groq = type("R", (_GroqStub,), {"calls": [], "status": 200,
                                             "text": "GROQ ANSWER"})
        self.groq_server = HTTPServer(("127.0.0.1", 0), self.groq)
        threading.Thread(target=self.groq_server.serve_forever, daemon=True).start()
        self.addCleanup(self.groq_server.shutdown)
        self.addCleanup(self.groq_server.server_close)
        self.url = f"http://127.0.0.1:{self.server.server_port}/x"
        self.groq_url = f"http://127.0.0.1:{self.groq_server.server_port}/chat"

    def _run(self, tasks, **kwargs):
        return run_tasks({"tasks": tasks}, api_key="g", model="m", root=Path("."),
                         url=self.url, groq_key="groq-secret", groq_url=self.groq_url,
                         **kwargs)

    def test_a_quota_wall_hands_the_task_to_groq(self):
        result = self._run([{"id": "t1", "kind": "answer", "instruction": "design a lamp"}])
        self.assertEqual(result["providers"], ["groq"])
        self.assertTrue(result["fallback_used"])
        self.assertEqual(result["results"][0]["text"], "GROQ ANSWER")
        self.assertEqual(len(self.gemini.calls), 1)
        self.assertEqual(self.groq.calls[0]["auth"], "Bearer groq-secret")

    def test_groq_prefers_llama_then_gpt_oss_120b(self):
        self.assertEqual(gemini_subagent.DEFAULT_GROQ_MODEL, "llama-3.3-70b-versatile")
        self.assertEqual(gemini_subagent.GROQ_MODEL_CHOICES[:2],
                         ("llama-3.3-70b-versatile", "openai/gpt-oss-120b"))
        self.marker.write_text("quota", encoding="utf-8")
        self.groq.status_by_model = {"llama-3.3-70b-versatile": 404}
        result = self._run([{"kind": "answer", "instruction": "design a lamp"}],
                           groq_model_name="llama-3.3-70b-versatile")
        self.assertTrue(result["results"][0]["ok"])
        self.assertEqual(result["results"][0]["text"], "GROQ ANSWER")
        self.assertEqual([call["model"] for call in self.groq.calls],
                         ["llama-3.3-70b-versatile", "openai/gpt-oss-120b"])

    def test_a_rate_limited_llama_hands_off_to_gpt_oss_120b(self):
        self.marker.write_text("quota", encoding="utf-8")
        self.groq.status_by_model = {"llama-3.3-70b-versatile": 429}
        self.groq.text_by_model = {"openai/gpt-oss-120b": "BACKUP COMPLETE"}
        result = self._run([{"kind": "answer", "instruction": "write a short answer"}],
                           groq_model_name="llama-3.3-70b-versatile")
        self.assertEqual(result["results"][0]["text"], "BACKUP COMPLETE")
        self.assertEqual([call["model"] for call in self.groq.calls],
                         ["llama-3.3-70b-versatile", "openai/gpt-oss-120b"])

    def test_a_still_truncated_llama_reply_uses_gpt_oss_not_the_partial_text(self):
        self.marker.write_text("quota", encoding="utf-8")
        self.groq.finish_by_model = {"llama-3.3-70b-versatile": "length"}
        self.groq.text_by_model = {"llama-3.3-70b-versatile": "PARTIAL ANSWER",
                                   "openai/gpt-oss-120b": "COMPLETE BACKUP ANSWER"}
        result = self._run([{"kind": "answer", "instruction": "write it fully"}],
                           groq_model_name="llama-3.3-70b-versatile")
        self.assertEqual(result["results"][0]["text"], "COMPLETE BACKUP ANSWER")
        self.assertEqual([call["model"] for call in self.groq.calls],
                         ["llama-3.3-70b-versatile", "llama-3.3-70b-versatile",
                          "openai/gpt-oss-120b"])
        self.assertEqual([call["max_tokens"] for call in self.groq.calls], [8192, 16384, 8192])

    def test_the_next_call_asks_gemini_again_without_waiting(self):
        self._run([{"id": "t1", "kind": "answer", "instruction": "one"}])
        self.assertEqual(len(self.gemini.calls), 1)
        # Simulate the retry window passing: Gemini must be tried first again.
        old = time.time() - (gemini_subagent.QUOTA_RETRY_MINUTES + 1) * 60
        os.utime(self.marker, (old, old))
        result = self._run([{"id": "t2", "kind": "answer", "instruction": "two"}])
        self.assertEqual(len(self.gemini.calls), 2, "Gemini must be asked again")
        self.assertEqual(result["providers"], ["groq"])

    def test_a_dead_groq_model_moves_to_the_next_free_one(self):
        # The first Gemini call is the 429 wall; after that the marker holds, and
        # every configured Groq model name is tried once, in order.
        self.groq.status = 404
        self.marker.write_text("x")
        result = self._run([{"id": "t1", "kind": "answer", "instruction": "one"}])
        self.assertFalse(result["results"][0]["ok"], "a dead fallback must be reported")
        self.assertIn("Groq", result["results"][0]["error"])
        tried = [call["model"] for call in self.groq.calls]
        self.assertGreaterEqual(len(tried), 2, "a retired model must fall through")
        self.assertEqual(len(set(tried)), len(tried))

    def test_the_groq_key_is_sent_as_a_bearer_header_not_in_the_url(self):
        self._run([{"id": "t1", "kind": "answer", "instruction": "one"}])
        self.assertNotIn("groq-secret", self.groq_url)
        self.assertEqual(self.groq.calls[0]["auth"], "Bearer groq-secret")

    def test_groq_alone_is_enough_when_there_is_no_gemini_key(self):
        result = run_tasks({"tasks": [{"kind": "answer", "instruction": "hi"}]},
                           api_key="", model="m", root=Path("."), groq_key="k",
                           groq_url=self.groq_url)
        self.assertFalse(result["skipped"])
        self.assertEqual(result["results"][0]["text"], "GROQ ANSWER")

    def test_no_keys_at_all_still_skips_quietly(self):
        result = run_tasks({"tasks": [{"kind": "answer", "instruction": "hi"}]},
                           api_key="", model="m", root=Path("."), groq_key="",
                           groq_url=self.groq_url)
        self.assertTrue(result["skipped"])


class BazaarLinkWorkflowTests(unittest.TestCase):
    def test_the_workflows_wire_bazaar_link_only_from_the_repository_secret(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertEqual(text.count("BAZAAR_LINK_API: ${{ secrets.BAZAAR_LINK_API }}"), 3)
        self.assertIn("and not os.environ.get('BAZAAR_LINK_API', '').strip()", text)
        self.assertIn('[ -n "${BAZAAR_LINK_API:-}" ]', text)
        agent = (ROOT / ".github" / "workflows" / "agent.yml").read_text(encoding="utf-8")
        self.assertIn("BAZAAR_LINK_API: ${{ secrets.BAZAAR_LINK_API }}", agent)


class GroqWorkflowTests(unittest.TestCase):
    def test_the_workflow_passes_the_groq_secret_to_every_ai_step(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertEqual(text.count("GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}"), 3)
        self.assertEqual(text.count("GROQ_MODEL: llama-3.3-70b-versatile"), 3)
        self.assertIn("Groq's default order is llama-3.3-70b-versatile → openai/gpt-oss-120b", text)

    def test_agent_workflow_uses_the_same_groq_model_order(self):
        text = (ROOT / ".github" / "workflows" / "agent.yml").read_text(encoding="utf-8")
        self.assertIn("GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}", text)
        self.assertIn("GROQ_MODEL: llama-3.3-70b-versatile", text)

    def test_exhausted_quota_never_silently_skips_mandatory_ai_authored_calls(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("and not os.environ.get('GROQ_API_KEY', '').strip()", text)
        self.assertIn("cannot execute the AI-authored mandatory map sub-agent calls", text)
        self.assertIn('{ [ -n "${BAZAAR_LINK_API:-}" ] || [ -n "${GEMINI_API_KEY:-}" ] || [ -n "${GROQ_API_KEY:-}" ]; }', text)
