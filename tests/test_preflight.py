"""Cheap checks first: the run must prove its tools work before the AI starts.

Every expensive failure this workflow has had landed at the end of an hour - a
backtick in the renderer's page template, a missing npm module, a browser without
WebGL - because nothing exercised the tools until they were needed. The preflight
step and the blueprint repair below are what stop that.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github" / "workflows" / "main.yml").read_text(encoding="utf-8")
sys.path.insert(0, str(ROOT / "tools"))

from build_story_map import derive_theme, repair_blueprint  # noqa: E402
from preflight import write_preflight_avatar  # noqa: E402


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

    def test_the_renderer_has_a_preflight_mode_that_accepts_profiles(self):
        renderer = (ROOT / "tools" / "video_renderer" / "render_short.mjs").read_text(encoding="utf-8")
        self.assertIn("async function preflight(plan, profiles = [])", renderer)
        self.assertIn("awaitpreflight(plan,profiles);return;", renderer.replace(" ", ""))
        self.assertIn("Render preflight avatar check", renderer)
        self.assertIn("Render preflight passed", renderer)

    def test_avatar_scene_ready_failure_is_checked_before_the_ai_starts(self):
        source = (ROOT / "tools" / "preflight.py").read_text(encoding="utf-8")
        workflow = WORKFLOW[WORKFLOW.index("Preflight: prove every tool"):]
        self.assertLess(workflow.index("python tools/preflight.py --render"),
                        workflow.index("Download the selected AI model"))
        self.assertIn('"--profiles", str(profiles_path), "--preflight"', source)
        self.assertIn("Render preflight avatar check: 1/1 synthetic avatar(s) rigged", source)
        self.assertIn("the scene failed to build", (ROOT / "tools/video_renderer/render_short.mjs").read_text(encoding="utf-8"))


class PreflightAvatarFixtureTests(unittest.TestCase):
    def test_fixture_contains_named_r15_parts_and_model_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = write_preflight_avatar(Path(tmp))
            folder = Path(tmp) / profile["user_id"]
            self.assertTrue(profile["model_ready"])
            self.assertEqual(profile["model_format"], "obj")
            self.assertTrue((folder / "avatar.obj").is_file())
            self.assertTrue((folder / "avatar.mtl").is_file())
            obj = (folder / "avatar.obj").read_text(encoding="utf-8")
            for part in ("Head", "Torso", "LeftArm", "RightArm", "LeftLeg", "RightLeg"):
                self.assertIn(f"o {part}", obj)
            self.assertIn("f 1 2 3 4", obj)


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
        # Only the story prompt keeps the open invitation; the map prompt replaced
        # it with the REQUIRED map/camera/models tasks (and dropped the duplicate).
        self.assertEqual(WORKFLOW.count(
            "YOU CAN USE IT ONE OR TWO TIMES, OR AS MANY TIMES AS YOU LIKE, AT ANY POINT"), 1)
        self.assertIn("There is no quota and no rule that you must ask", WORKFLOW)

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


class FailureIsVisibleWithoutTheJobLog(unittest.TestCase):
    """A failed job's raw log sits behind a storage URL that often will not open.

    GitHub still exposes annotations through the API, so every failed check has to
    emit one, and the renderer has to report its frame numbers the same way.
    """

    def test_every_preflight_failure_becomes_an_annotation(self):
        source = (ROOT / "tools/preflight.py").read_text(encoding="utf-8")
        self.assertIn("::error title=Preflight failed::", source)
        # The annotation is emitted inside fail(), so it cannot be forgotten at a
        # new call site.
        body = source.split("def fail(message: str) -> None:", 1)[1].split("def check(", 1)[0]
        self.assertIn("::error title=Preflight failed::", body)

    def test_the_renderer_reports_its_picture_numbers_as_an_annotation(self):
        renderer = (ROOT / "tools/video_renderer/render_short.mjs").read_text(encoding="utf-8")
        self.assertIn("::notice title=Render preflight picture::", renderer)


class PreflightWorldIsRepresentativeTests(unittest.TestCase):
    """The colour audit measures the preflight frame, so that frame has to look
    like a real world. A single grey hall measured 4.8% colour and failed a
    renderer that was in fact working."""

    def test_the_sample_world_actually_has_a_palette(self):
        source = (ROOT / "tools/preflight.py").read_text(encoding="utf-8")
        plan = source.split("plan = {", 1)[1].split("with tempfile", 1)[0]
        colours = re.findall(r'"color": \[([^\]]+)\]', plan)
        self.assertGreaterEqual(len(colours), 5, "the preflight world needs a real palette")
        distinct = {tuple(int(part) for part in colour.split(",")) for colour in colours}
        self.assertGreaterEqual(len(distinct), 5, "the preflight colours must differ from each other")
        # And at least one prop must be a light, so lighting is exercised too.
        self.assertIn('"light":', plan)


if __name__ == "__main__":
    unittest.main()


class PreflightDiagnosticsTests(unittest.TestCase):
    """A preflight failure must name the stage, not print a stack frame."""

    def setUp(self):
        self.renderer = (ROOT / "tools" / "video_renderer" / "render_short.mjs").read_text(encoding="utf-8")
        self.preflight = (ROOT / "tools" / "preflight.py").read_text(encoding="utf-8")

    def test_the_renderer_reports_the_stage_that_broke(self):
        for stage in ("start Chromium", "load the page", "build the 3D scene",
                      "draw one frame", "check the frame"):
            self.assertIn(stage, self.renderer)
        self.assertIn('preflight failed at "${stage}"', self.renderer)

    def test_it_lists_what_the_browser_said(self):
        self.assertIn("What the browser said:", self.renderer)
        self.assertIn("requestfailed", self.renderer)
        self.assertIn("pageerror", self.renderer)

    def test_it_tries_several_webgl_settings(self):
        self.assertIn("GL_CONFIGS", self.renderer)
        self.assertIn("'--use-gl=swiftshader'", self.renderer)
        self.assertIn("Chromium could not start with any WebGL setting", self.renderer)
        # Both the preflight and the real render use the same launcher.
        self.assertEqual(self.renderer.count("await launchBrowser()"), 2)

    def test_it_says_whether_the_browser_binary_exists(self):
        self.assertIn("MISSING", self.renderer)
        self.assertIn("chromium.executablePath()", self.renderer)

    def test_the_helper_does_not_truncate_to_the_last_stack_line(self):
        self.assertIn("def explain(", self.preflight)
        self.assertIn("interesting = [row for row in rows", self.preflight)
        self.assertNotIn("splitlines()[-1:]", self.preflight)

    def test_explain_finds_the_error_line(self):
        sys.path.insert(0, str(ROOT / "tools"))
        from preflight import explain

        output = ("node:internal/errors:1\n"
                  "Error [ERR_MODULE_NOT_FOUND]: Cannot find package 'playwright'\n"
                  "    at ModuleLoader.resolve\n    at async main\n")
        text = explain(output)
        self.assertIn("Cannot find package 'playwright'", text)
        self.assertTrue(text.strip().splitlines()[0].startswith("Error [ERR_MODULE_NOT_FOUND]"))

    def test_the_workflow_installs_a_missing_browser_before_checking(self):
        self.assertIn("Chromium is not on disk", WORKFLOW)
        self.assertIn("npx playwright install --with-deps chromium", WORKFLOW)


class PreflightArgumentTests(unittest.TestCase):
    """The preflight must be able to run the renderer without a real render.

    Run #78 failed at the start because the preflight called the renderer with no
    --duration, which tripped the duration bounds check before Chromium was even
    launched. This runs the real script against a stub browser so the arguments
    are parsed exactly as they are on the runner.
    """

    def _run(self, *args):
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed")
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            shutil.copy(ROOT / "tools" / "video_renderer" / "render_short.mjs", tmp / "render_short.mjs")
            stub = tmp / "node_modules" / "playwright"
            stub.mkdir(parents=True)
            (stub / "package.json").write_text('{"name":"playwright","version":"0.0.0","type":"module","main":"index.mjs"}', encoding="utf-8")
            (stub / "index.mjs").write_text(
                "export const chromium = {\n"
                "  executablePath: () => '/nonexistent/chrome',\n"
                "  launch: async () => { throw new Error('stub browser unavailable'); },\n"
                "};\n", encoding="utf-8")
            mapping = tmp / "map.json"
            mapping.write_text("{}", encoding="utf-8")
            argv = [node, str(tmp / "render_short.mjs")] + [a.replace("MAP", str(mapping)) for a in args]
            result = subprocess.run(argv, capture_output=True, text=True, cwd=tmp, timeout=120)
            return result.returncode, result.stdout + result.stderr

    def test_preflight_gets_past_argument_parsing(self):
        code, output = self._run("--map", "MAP", "--preflight")
        self.assertNotIn("Duration must be between", output)
        self.assertNotIn("Missing --duration", output)
        # It reaches the browser step, which the stub deliberately breaks.
        self.assertIn('preflight failed at "start Chromium"', output)
        self.assertIn("stub browser unavailable", output)
        self.assertEqual(code, 1)

    def test_a_real_render_still_needs_a_length(self):
        code, output = self._run("--map", "MAP", "--output", "out.mp4", "--characters", "a",
                                 "--profiles", "p")
        self.assertIn("Missing --duration", output)
        self.assertEqual(code, 1)

    def test_a_length_outside_the_allowed_window_is_still_rejected(self):
        code, output = self._run("--map", "MAP", "--output", "out.mp4", "--characters", "a",
                                 "--profiles", "p", "--duration", "2")
        self.assertIn("Duration must be between 15 and 300 seconds, got 2.", output)
        self.assertEqual(code, 1)
