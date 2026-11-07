"""The local model can delegate work to a Gemini sub-agent at any time.

Configuration lives in the repository: a secret named ``GEMINI_API_KEY`` (free key
from aistudio.google.com/apikey) and an optional variable ``GEMINI_MODEL``. Without
the secret every delegated task is skipped and the run carries on untouched.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from gemini_subagent import (  # noqa: E402
    build_prompt,
    normalize_request,
    run_tasks,
    safe_target,
)

WORKFLOW = ROOT / ".github" / "workflows" / "main.yml"


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
        self.assertIn("exactly one of: Block, Ball, Cylinder", text)
        self.assertIn("SmoothPlastic", text)
        self.assertIn("multiples of 0.5", text)
        self.assertIn("|x| + width/2 <= 320", text)

    def test_camera_and_face_rules_come_with_the_blueprint(self):
        from gemini_workspace import guide

        text = guide({"kind": "edit", "instruction": "retime the close-up shots",
                      "topic": "cameras"})
        self.assertIn("CAMERA PLAN", text)
        self.assertIn("WORLD BLUEPRINT", text)  # always shipped together
        self.assertIn("1.6..4.0", text)
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
            self.assertIn("GEMINI_API_KEY is not configured", result.stdout)

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
        self.assertIn("GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}", self.workflow)
        self.assertIn("GEMINI_MODEL: ${{ vars.GEMINI_MODEL }}", self.workflow)

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

    def test_the_reply_is_visible_in_the_console(self):
        helper = (ROOT / "tools" / "gemini_subagent.py").read_text(encoding="utf-8")
        self.assertIn("reply to {task['id']}", helper)
        self.assertIn("full answer for {entry['id']}", helper)
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
