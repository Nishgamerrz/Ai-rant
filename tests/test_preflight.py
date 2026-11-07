"""Cheap checks first: the run must prove its tools work before the AI starts.

Every expensive failure this workflow has had landed at the end of an hour - a
backtick in the renderer's page template, a missing npm module, a browser without
WebGL - because nothing exercised the tools until they were needed. The preflight
step and the blueprint repair below are what stop that.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github" / "workflows" / "main.yml").read_text(encoding="utf-8")
sys.path.insert(0, str(ROOT / "tools"))

from build_story_map import derive_theme, repair_blueprint  # noqa: E402


class PreflightWiringTests(unittest.TestCase):
    def test_the_preflight_runs_before_the_model_download(self):
        preflight = WORKFLOW.index("Preflight: prove every tool")
        download = WORKFLOW.index("Download the selected AI model")
        self.assertLess(preflight, download)

    def test_it_runs_after_the_tools_are_installed(self):
        npm = WORKFLOW.index("npm ci --no-audit --no-fund")
        preflight = WORKFLOW.index("Preflight: prove every tool")
        self.assertLess(npm, preflight)

    def test_it_renders_a_real_frame(self):
        self.assertIn("python tools/preflight.py --render", WORKFLOW)


class PreflightScriptTests(unittest.TestCase):
    def run_preflight(self, *args):
        return subprocess.run([sys.executable, "tools/preflight.py", *args],
                              cwd=ROOT, capture_output=True, text=True)

    def test_it_checks_sources_syntax_and_the_plan_schema(self):
        result = self.run_preflight()
        for expected in ("python sources compile", "renderer scripts parse",
                         "page template builds", "world-plan schema builds"):
            self.assertIn(expected, result.stdout)
        # In this sandbox ffmpeg and node_modules may legitimately be absent; the
        # runner installs both before the step runs.
        self.assertNotIn("FAIL python sources compile", result.stdout)
        self.assertNotIn("FAIL page template builds", result.stdout)
        self.assertNotIn("FAIL world-plan schema builds", result.stdout)

    def test_a_missing_tool_is_named_not_swallowed(self):
        source = (ROOT / "tools" / "preflight.py").read_text(encoding="utf-8")
        self.assertIn("Fix these before the AI spends an hour on the run.", source)
        self.assertIn("not on PATH", source)

    def test_it_needs_no_third_party_imports(self):
        source = (ROOT / "tools" / "preflight.py").read_text(encoding="utf-8")
        for banned in ("import yaml", "import requests", "from PIL"):
            self.assertNotIn(banned, source)

    def test_the_renderer_has_a_preflight_mode(self):
        renderer = (ROOT / "tools" / "video_renderer" / "render_short.mjs").read_text(encoding="utf-8")
        self.assertIn("async function preflight(", renderer)
        self.assertIn("if(args.preflight){ await preflight(plan); return; }", renderer)
        self.assertIn("Render preflight passed", renderer)


class BlueprintRepairTests(unittest.TestCase):
    """A missing "theme" sentence must not throw away a 48-minute plan."""

    def test_a_missing_theme_is_taken_from_the_story(self):
        plan = {"props": [{"name": "Hall"}], "name": "Skyfall City"}
        repaired, fixes = repair_blueprint(plan, "AUTO FROM STORY",
                                          "Max floats out of his window at eight.", "")
        self.assertEqual(repaired["theme"], "Max floats out of his window at eight.")
        self.assertTrue(any("theme" in note for note in fixes))

    def test_a_real_theme_cue_wins(self):
        plan = {"props": [{"name": "Hall"}]}
        repaired, _ = repair_blueprint(plan, "Bright daytime seaside town", "story", "")
        self.assertEqual(repaired["theme"], "Bright daytime seaside town")

    def test_a_missing_name_is_filled(self):
        repaired, fixes = repair_blueprint({"props": [{"name": "Hall"}]}, "", "A story.", "")
        self.assertEqual(repaired["name"], "Story World")
        self.assertTrue(fixes)

    def test_a_complete_blueprint_is_left_alone(self):
        plan = {"name": "N", "theme": "Neon skyline", "props": [{"name": "Hall"}]}
        repaired, fixes = repair_blueprint(plan, "", "", "")
        self.assertEqual(repaired, plan)
        self.assertEqual(fixes, [])

    def test_the_fallback_theme_mentions_the_world(self):
        theme = derive_theme("", "", "", {"name": "Skyfall City"})
        self.assertIn("Skyfall City", theme)

    def test_the_strict_reader_repairs_instead_of_rejecting(self):
        source = (ROOT / "tools" / "build_story_map.py").read_text(encoding="utf-8")
        self.assertIn("repair_blueprint(", source)
        self.assertNotIn("AI map must include a non-empty prompt-specific theme description", source)
        self.assertIn("Repaired the AI blueprint instead of rejecting it", source)

    def test_it_still_rejects_a_blueprint_with_no_props(self):
        source = (ROOT / "tools" / "build_story_map.py").read_text(encoding="utf-8")
        self.assertIn("the AI blueprint contained no props", source)


class SubAgentInvitationTests(unittest.TestCase):
    def test_the_prompts_invite_one_or_two_uses_at_any_time(self):
        self.assertEqual(WORKFLOW.count(
            "YOU CAN USE IT ONE OR TWO TIMES, OR AS MANY TIMES AS YOU LIKE, AT ANY POINT"), 2)
        self.assertIn("asking is never compulsory, only useful", WORKFLOW)

    def test_the_map_prompt_names_the_required_keys(self):
        self.assertIn('REQUIRED TOP-LEVEL KEYS, every one of them present and non-empty', WORKFLOW)
        self.assertIn('"name", "theme", "props", "character_placements", "camera_shots", '
                      '"face_expressions"', WORKFLOW)
        self.assertIn('never the words "AUTO FROM STORY"', WORKFLOW)


class DefaultTopicTests(unittest.TestCase):
    def test_the_default_topic_is_not_the_gravity_one(self):
        start = WORKFLOW.index("      story_topic:")
        block = WORKFLOW[start:WORKFLOW.index("      character_usernames:", start)]
        self.assertNotIn("gravity", block)
        self.assertIn("In a world where", block)

    def test_it_is_one_of_the_listed_ideas(self):
        topics = (ROOT / "STORY_TOPICS.md").read_text(encoding="utf-8")
        start = WORKFLOW.index("      story_topic:")
        block = WORKFLOW[start:WORKFLOW.index("      character_usernames:", start)]
        default = block.split("default: '", 1)[1].split("'", 1)[0]
        self.assertIn(default, topics)


if __name__ == "__main__":
    unittest.main()
