"""The typed story prompt is spell-checked once, silently, before planning.

The Actions form is filled in by hand, so the topic can arrive as "a stdent finds
a lost wallett on the way to shcool". Gemini rewrites it - spelling fixed, the
same story, a little more detail - and the run uses that from then on. The reply
must never contain a note about the correction, and a reply that does is thrown
away in favour of the user's own wording.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from gemini_topic import (  # noqa: E402
    META_PHRASES,
    TOPIC_NOTE,
    build_prompt,
    premises,
    refine,
    sanitize,
    starts_with_premise,
)

WORKFLOW = ROOT / ".github" / "workflows" / "main.yml"

# Hermetic marker path: a real quota hit in an earlier workflow step must never
# change what these stub-API tests see (see tests/test_gemini_subagent.py).
os.environ.setdefault("GEMINI_QUOTA_MARKER",
                      str(Path(tempfile.mkdtemp(prefix="quota-marker-")) / "gemini_quota_exhausted"))
# Keep API coverage hermetic; every provider call in these tests uses a local stub.
for _credential in ("BAZAAR_LINK_API", "GEMINI_API_KEY", "GROQ_API_KEY"):
    os.environ.pop(_credential, None)

GOOD = ("A nervous student finds a lost wallet on the way to school and has to decide "
        "what to do before the first bell rings.")


class PromptTests(unittest.TestCase):
    def test_the_note_says_to_fix_mistakes_silently(self):
        prompt = build_prompt("a stdent finds a lost wallett", "story")
        self.assertIn("(Note:", prompt)
        self.assertIn("may contain spelling, grammar or punctuation mistakes", prompt)
        self.assertIn("Correct them silently", prompt)
        self.assertIn("never mention spelling, typos, grammar or corrections", prompt)
        self.assertIn("never say that anything was rewritten", prompt)

    def test_the_note_says_output_only_the_prompt(self):
        prompt = build_prompt("x", "story")
        self.assertIn("Output the rewritten prompt only", prompt)
        self.assertIn("no answer to the prompt itself", prompt)

    def test_the_meaning_must_be_kept(self):
        prompt = build_prompt("x", "story")
        self.assertIn("Keep the user's story, setting, characters and intent", prompt)
        self.assertIn("Do not replace their idea", prompt)
        self.assertIn("with your own", prompt)

    def test_the_theme_has_its_own_rules(self):
        theme = build_prompt("rainy markt street", "theme")
        self.assertIn("world theme", theme)
        self.assertIn("under 35 words", theme)
        self.assertIn("Do not move the story somewhere else", theme)

    def test_the_typed_text_is_passed_through(self):
        self.assertIn("a stdent finds a lost wallett", build_prompt(
            "a stdent finds a lost wallett", "story"))


class SanitizeTests(unittest.TestCase):
    def test_a_clean_rewrite_is_accepted(self):
        text, reason = sanitize(GOOD, "a stdent finds a lost wallett")
        self.assertEqual(reason, "ok")
        self.assertTrue(text.startswith("A nervous student"))

    def test_fences_quotes_and_labels_are_stripped(self):
        for reply in (f'```\n{GOOD}\n```', f'"{GOOD}"', f"Rewritten prompt: {GOOD}",
                      f"Topic: {GOOD}"):
            text, reason = sanitize(reply, "a stdent finds a lost wallett")
            self.assertEqual(reason, "ok", msg=reply[:40])
            self.assertEqual(text, GOOD)

    def test_never_accepts_a_note_about_the_correction(self):
        replies = [
            "Fixed the spelling mistakes. " + GOOD,
            "I corrected your typos: " + GOOD,
            GOOD + " (spelling fixed)",
            "Here is the corrected prompt: " + GOOD,
            "Certainly! " + GOOD,
        ]
        for reply in replies:
            text, reason = sanitize(reply, "a stdent finds a lost wallett")
            self.assertIsNone(text, msg=reply[:50])
            self.assertIn("talked about the change", reason)

    def test_every_meta_phrase_is_actually_tested_for(self):
        # Keep the list meaningful: each phrase must be able to reject a reply.
        for phrase in META_PHRASES:
            text, _ = sanitize(f"{GOOD} {phrase}", "a stdent")
            self.assertIsNone(text, msg=phrase)

    def test_empty_identical_and_runaway_replies_are_refused(self):
        self.assertIsNone(sanitize("", "a stdent")[0])
        self.assertIsNone(sanitize("a stdent", "a stdent")[0])
        self.assertIsNone(sanitize("word " * 400, "a stdent")[0])

    def test_an_explanation_is_refused(self):
        self.assertIsNone(sanitize("**Story**\n\n" + GOOD, "a stdent")[0])


class _Stub(BaseHTTPRequestHandler):
    reply = GOOD
    calls: list[str] = []
    status = 200

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length))
        type(self).calls.append(payload["contents"][0]["parts"][0]["text"])
        if type(self).status != 200:
            self.send_response(type(self).status)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = json.dumps({"candidates": [{"content": {"parts": [
            {"text": type(self).reply}]}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class ApiTests(unittest.TestCase):
    def setUp(self):
        # A quota marker left in the repository would switch these calls off.
        marker = tempfile.NamedTemporaryFile(prefix="quota-", delete=False)
        marker.close()
        Path(marker.name).unlink()
        os.environ["GEMINI_QUOTA_MARKER"] = marker.name
        self.addCleanup(os.environ.pop, "GEMINI_QUOTA_MARKER", None)
        handler = type("Handler", (_Stub,), {"calls": [], "status": 200, "reply": GOOD})
        self.server = HTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)
        self.addCleanup(self.server.server_close)
        self.handler = handler
        self.url = f"http://127.0.0.1:{self.server.server_port}/x"

    def test_the_typos_are_replaced(self):
        result = refine("a stdent finds a lost wallett", api_key="k", model="m",
                        url=self.url)
        self.assertTrue(result["ok"])
        self.assertEqual(result["text"], GOOD)
        self.assertEqual(result["original"], "a stdent finds a lost wallett")

    def test_no_key_keeps_the_text_as_typed(self):
        result = refine("a stdent finds a lost wallett", api_key="", model="m",
                        url=self.url)
        self.assertTrue(result["skipped"])
        self.assertEqual(result["text"], "a stdent finds a lost wallett")
        self.assertEqual(self.handler.calls, [])

    def test_bazaarlink_is_passed_to_the_shared_provider_and_its_completion_is_used(self):
        with patch("gemini_topic.call_any", return_value=(GOOD, "bazaarlink")) as mocked:
            result = refine("a stdent finds a lost wallett", api_key="", model="m",
                            bazaar_key="bazaar-secret")
        self.assertTrue(result["ok"])
        self.assertEqual(result["provider"], "bazaarlink")
        self.assertEqual(result["text"], GOOD)
        self.assertEqual(mocked.call_args.kwargs["bazaar_key"], "bazaar-secret")

    def test_a_meta_reply_falls_back_to_the_typed_text(self):
        self.handler.reply = "Sure, I fixed the spelling: " + GOOD
        result = refine("a stdent finds a lost wallett", api_key="k", model="m",
                        url=self.url)
        self.assertFalse(result["ok"])
        self.assertEqual(result["text"], "a stdent finds a lost wallett")

    def test_a_quota_error_falls_back_to_the_typed_text(self):
        self.handler.status = 429
        result = refine("a stdent finds a lost wallett", api_key="k", model="m",
                        url=self.url)
        self.assertFalse(result["ok"])
        self.assertEqual(result["text"], "a stdent finds a lost wallett")
        self.assertIn("429", result["reason"])

    def test_empty_input_never_calls_the_api(self):
        result = refine("   ", api_key="k", model="m", url=self.url)
        self.assertTrue(result["skipped"])
        self.assertEqual(self.handler.calls, [])


class CommandLineTests(unittest.TestCase):
    def _run(self, tmp, env):
        return subprocess.run(
            [sys.executable, str(ROOT / "tools" / "gemini_topic.py"),
             "--output", "refined.json", "--github-output", "gh_output"],
            cwd=tmp, capture_output=True, text=True,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), **env},
        )

    def test_without_a_key_the_raw_text_is_written_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp, {"RAW_STORY_TOPIC": "a stdent finds a wallett",
                                     "RAW_WORLD_THEME": ""})
            self.assertEqual(result.returncode, 0, msg=result.stderr[-800:])
            self.assertIn("using the prompt exactly as typed", result.stdout)
            outputs = (Path(tmp) / "gh_output").read_text()
            self.assertIn("story_topic=a stdent finds a wallett", outputs)
            self.assertIn("world_theme=\n", outputs)

    def test_multiline_text_uses_the_heredoc_output_form(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._run(tmp, {"RAW_STORY_TOPIC": "line one\nline two", "RAW_WORLD_THEME": ""})
            outputs = (Path(tmp) / "gh_output").read_text()
            self.assertIn("story_topic<<GH_TOPIC_EOF", outputs)
            self.assertIn("line one\nline two", outputs)

    def test_the_json_record_explains_the_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._run(tmp, {"RAW_STORY_TOPIC": "a stdent", "RAW_WORLD_THEME": "rainy"})
            data = json.loads((Path(tmp) / "refined.json").read_text())
            self.assertEqual(data["story"]["reason"], "no API key")
            self.assertTrue(data["story"]["skipped"])


class WorkflowWiringTests(unittest.TestCase):
    def setUp(self):
        self.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_the_cleanup_runs_before_anything_uses_the_prompt(self):
        refine_at = self.workflow.index("tools/gemini_topic.py")
        self.assertLess(refine_at, self.workflow.index("from durations import"))
        self.assertIn("      - name: Fix the spelling in the typed prompt\n        id: refine",
                      self.workflow)

    def test_the_cleanup_reads_the_raw_input_not_its_own_output(self):
        start = self.workflow.index("id: refine")
        block = self.workflow[start:start + 700]
        self.assertIn("RAW_STORY_TOPIC: ${{ inputs.story_topic }}", block)
        self.assertIn("RAW_WORLD_THEME: ${{ inputs.world_theme }}", block)
        self.assertNotIn("RAW_STORY_TOPIC: ${{ steps.refine", block)

    def test_it_uses_the_same_free_provider_secrets(self):
        start = self.workflow.index("id: refine")
        block = self.workflow[start:start + 1000]
        self.assertIn("BAZAAR_LINK_API: ${{ secrets.BAZAAR_LINK_API }}", block)
        self.assertIn("GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}", block)
        self.assertIn("GEMINI_MODEL: ${{ vars.GEMINI_MODEL }}", block)
        self.assertIn("GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}", block)

    def test_every_later_step_uses_the_cleaned_prompt(self):
        # RAW_STORY_TOPIC: ... is the one place the untouched input may appear.
        for line in self.workflow.splitlines():
            stripped = line.strip()
            if stripped.startswith("STORY_TOPIC:"):
                self.assertIn("steps.refine.outputs.story_topic", stripped)
            if stripped.startswith("WORLD_THEME:"):
                self.assertIn("steps.refine.outputs.world_theme", stripped)
        self.assertIn("STORY_TOPIC: ${{ steps.refine.outputs.story_topic || inputs.story_topic }}",
                      self.workflow)
        self.assertIn("WORLD_THEME: ${{ steps.refine.outputs.world_theme || inputs.world_theme }}",
                      self.workflow)

    def test_the_run_summary_mentions_the_silent_cleanup(self):
        self.assertIn("**Prompt cleanup:**", self.workflow)
        self.assertIn("the correction is never mentioned in the text", self.workflow)

    def test_a_broken_cleanup_cannot_fail_the_run(self):
        start = self.workflow.index("id: refine")
        block = self.workflow[start:start + 1200]
        self.assertIn("continue-on-error: true", block)
        self.assertIn("|| true", block)


if __name__ == "__main__":
    unittest.main()


class PremiseKeptTests(unittest.TestCase):
    """Run #78's cleanup turned a what-if premise into a scene.

    Gemini rewrote "In a world where the last person to fall asleep each night
    gets one wish, two brothers keep each other awake on purpose" as "At midnight,
    two brothers in their bunk beds try to stay awake, knowing the last one to
    fall asleep gets one wish ." - a moment instead of an idea, with a space
    before the full stop. The user's own wording is better than that, so the
    rewrite is dropped.
    """

    RAW = ("In a world where the last person to fall asleep each night gets one "
           "wish, two brothers keep each other awake on purpose")
    SCENE = ("At midnight, two brothers in their bunk beds try to stay awake, "
             "knowing the last one to fall asleep gets one wish .")

    def test_the_instructions_ask_for_the_premise_to_be_kept(self):
        prompt = " ".join(build_prompt(self.RAW, "story").split())
        for opener in ('"In a world where ..."', '"In this world where ..."',
                       '"What if ..."', '"Imagine a world where ..."', '"Suppose'):
            self.assertIn(opener, prompt)
        self.assertIn("must stay", prompt)
        self.assertIn("never delete, shorten or paraphrase it", prompt)
        self.assertIn("must survive unchanged", prompt)

    def test_a_rewrite_that_becomes_a_scene_is_rejected(self):
        text, reason = sanitize(self.SCENE, self.RAW)
        self.assertIsNone(text)
        self.assertIn("premise", reason)

    def test_a_rewrite_that_keeps_the_premise_is_accepted(self):
        reply = ("In a world where the last person to fall asleep each night gets "
                 "one wish, two brothers in their bunk beds keep each other awake "
                 "on purpose.")
        text, reason = sanitize(reply, self.RAW)
        self.assertEqual(reason, "ok")
        self.assertTrue(text.startswith("In a world where"))

    def test_a_small_rewording_of_the_opener_is_still_allowed(self):
        text, reason = sanitize("In a world, the last one awake each night gets one wish.", self.RAW)
        self.assertEqual(reason, "ok")

    def test_a_trailing_space_before_the_full_stop_is_closed(self):
        text, _ = sanitize("At midnight, two brothers try to stay awake .", "two brothers stay awake")
        self.assertEqual(text, "At midnight, two brothers try to stay awake.")

    def test_a_missing_full_stop_is_added(self):
        text, _ = sanitize("At midnight two brothers stay awake", "two brothers stay awake")
        self.assertTrue(text.endswith("."))

    def test_a_prompt_without_a_premise_is_not_forced_into_one(self):
        text, reason = sanitize("A student finds a lost wallet on the way to school.",
                                "a stdent finds a lost wallett on the way to shcool")
        self.assertEqual(reason, "ok")


class EveryPremiseShapeTests(unittest.TestCase):
    """Gemini drops "what if" and "in this world" as readily as "in a world where".

    Each shape is checked on its own: the premise clause is the story, so a
    rewrite that deletes it - or that opens with a time or a place instead - is
    discarded and the user's own wording is used.
    """

    CASES = {
        "in a world where": (
            "In a world where the last person to fall asleep gets one wish, two brothers stay awake",
            "At midnight, two brothers try to stay awake.",
        ),
        "in this world": (
            "In this world where every lie turns into a coin, a boy cannot stop lying",
            "A boy in a small town cannot stop lying.",
        ),
        "what if": (
            "What if your shadow knew every secret you kept",
            "One night, a boy notices his shadow watching him.",
        ),
        "imagine": (
            "Imagine a world where it rains only on birthdays",
            "Rain falls on a birthday party.",
        ),
        "suppose": (
            "Suppose every door you open takes you back one year",
            "A girl opens a door and finds yesterday.",
        ),
    }

    def test_each_shape_is_detected(self):
        for name, (raw, _) in self.CASES.items():
            self.assertTrue(premises(raw), name + " was not seen as a premise")
            self.assertTrue(starts_with_premise(raw), name + " does not start with its premise")

    def test_deleting_the_premise_is_refused(self):
        for name, (raw, scene) in self.CASES.items():
            text, reason = sanitize(scene, raw)
            self.assertIsNone(text, name + ": a scene rewrite was accepted")
            self.assertIn("premise", reason)

    def test_moving_the_premise_out_of_the_opening_is_refused(self):
        raw = self.CASES["in this world"][0]
        text, reason = sanitize(
            "A boy cannot stop lying in this world where every lie turns into a coin.", raw)
        self.assertIsNone(text)
        self.assertIn("scene-setting", reason)

    def test_keeping_the_premise_is_never_punished(self):
        for name, (raw, _) in self.CASES.items():
            text, reason = sanitize(raw.rstrip(".") + ".", raw)
            self.assertIn(reason, {"ok", "the reply was identical to the input"}, name)

    def test_a_rewrite_that_keeps_the_opener_and_adds_detail_passes(self):
        raw = "What if your shadow knew every secret you kept"
        text, reason = sanitize(
            "What if your shadow in the school hallway knew every secret you kept?", raw)
        self.assertEqual(reason, "ok")
        self.assertTrue(text.startswith("What if"))

    def test_a_prompt_with_no_premise_still_gets_cleaned(self):
        text, reason = sanitize("A student finds a lost wallet on the way to school.",
                                "a stdent finds a lost wallett on the way to shcool")
        self.assertEqual(reason, "ok")
