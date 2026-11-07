"""Guard against the duration rule drifting between tools again.

A 120 s run once died at the very end because `build_studio_experience.py` still
offered only 30/45/60 while the workflow form, the narration gate, the MP4
renderer and the validator all accepted up to 180 s. Every gate must now read the
same list from `tools/durations.py`.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from durations import DURATION_CHOICES, DURATIONS, MAX_DURATION, MIN_DURATION, check_duration  # noqa: E402

EXPECTED = (30, 45, 60, 90, 120, 150, 180)


class DurationSourceOfTruthTests(unittest.TestCase):
    def test_supported_set_covers_long_form(self):
        self.assertEqual(DURATIONS, EXPECTED)
        self.assertEqual(DURATION_CHOICES, DURATIONS)
        self.assertEqual(MIN_DURATION, 30)
        self.assertEqual(MAX_DURATION, 180)

    def test_check_duration_accepts_every_selectable_length(self):
        for value in DURATIONS:
            self.assertEqual(check_duration(value), float(value))
            self.assertEqual(check_duration(str(value)), float(value))

    def test_check_duration_rejects_unsupported_lengths(self):
        for value in (0, 15, 75, 200, "abc", None):
            with self.assertRaises(ValueError):
                check_duration(value)

    def test_workflow_form_matches_shared_list(self):
        workflow = (ROOT / ".github/workflows/main.yml").read_text(encoding="utf-8")
        start = workflow.index("duration_seconds:")
        block = workflow[start:workflow.index("- '180'", start)] + "- '180'"
        self.assertEqual(
            [int(value) for value in re.findall(r"^\s+- '(\d+)'$", block, re.MULTILINE)],
            list(DURATIONS),
        )


class EveryToolAcceptsLongFormTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.map = self.tmp / "map.json"
        self.cast = self.tmp / "cast.json"
        plan = {
            "name": "Plaza",
            "theme": "daylight plaza",
            "ground_color": [88, 166, 91],
            "props": [
                {"name": f"Prop{index}", "shape": "Block", "size": [4, 4, 4],
                 "position": [index * 5, 2, 20], "color": [200, 200, 200],
                 "material": "SmoothPlastic", "anchored": True}
                for index in range(9)
            ],
            "character_placements": [{"username": "Lead", "position": [0, 0, 24]}],
            "camera_shots": [
                {"time": 0, "position": [0, 30, 70], "target": [0, 3, 24], "transition": "smooth"},
                {"time": 60, "position": [-12, 14, 18], "target": [0, 3, 24], "transition": "smooth"},
                {"time": 120, "position": [12, 14, 18], "target": [0, 3, 24], "transition": "snap"},
            ],
        }
        self.map.write_text(json.dumps(plan), encoding="utf-8")
        self.cast.write_text(json.dumps(["Lead"]), encoding="utf-8")
        self.narration = self.tmp / "narration.txt"
        self.narration.write_text("Maya found the lost wallet. " * 40, encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _help(self, *script):
        return subprocess.run(
            [sys.executable, *script, "--help"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout

    def test_cli_help_lists_every_duration(self):
        expected = "{" + ",".join(str(value) for value in DURATIONS) + "}"
        for script, arg in (
            ("tools/build_studio_experience.py", "--duration"),
            ("tools/validate_short.py", "--duration"),
        ):
            help_text = self._help(script)
            self.assertIn(arg, help_text, msg=script)
            self.assertIn(expected.replace(",", ", "), help_text.replace(",", ", "), msg=script)

    def test_studio_builder_accepts_long_form(self):
        for duration in (60, 120, 180):
            output = self.tmp / f"place_{duration}.rbxlx"
            readme = self.tmp / f"README_{duration}.md"
            result = subprocess.run(
                [sys.executable, "tools/build_studio_experience.py",
                 "--map", str(self.map), "--cast", str(self.cast),
                 "--duration", str(duration), "--narration", str(self.narration),
                 "--output", str(output), "--readme", str(readme)],
                cwd=ROOT, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr[-2000:])
            place = output.read_text(encoding="utf-8")
            self.assertIn(f'"duration":{duration}', place)
            self.assertIn(str(duration), readme.read_text(encoding="utf-8"))

    def test_studio_builder_still_rejects_unlisted_length(self):
        result = subprocess.run(
            [sys.executable, "tools/build_studio_experience.py",
             "--map", str(self.map), "--cast", str(self.cast),
             "--duration", "77", "--output", str(self.tmp / "nope.rbxlx")],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid choice", result.stderr)

    def test_sound_bed_gate_accepts_long_form(self):
        from create_sound_bed import resolve_duration

        for duration in DURATIONS:
            self.assertEqual(resolve_duration(duration), float(duration))
            self.assertEqual(resolve_duration(str(duration)), float(duration))
        for bad in ("20", "200", "abc"):
            with self.assertRaises(SystemExit):
                resolve_duration(bad)

    def test_roblox_animation_accepts_long_form(self):
        animation = {
            "name": "StoryGesture",
            "keyframes": [
                {"time": index * 0.5, "poses": {"UpperTorso": [0, index, 0]}}
                for index in range(14)
            ],
        }
        source = self.tmp / "animation.json"
        source.write_text(json.dumps(animation), encoding="utf-8")
        for duration in (60, 120, 180):
            destination = self.tmp / f"anim_{duration}.json"
            result = subprocess.run(
                [sys.executable, "tools/build_roblox_animation.py",
                 str(source), str(destination), str(duration), "--json-only"],
                cwd=ROOT, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr[-2000:])
            data = json.loads(destination.read_text(encoding="utf-8"))
            self.assertAlmostEqual(float(data["duration_seconds"]), float(duration), delta=0.01)
            self.assertAlmostEqual(float(data["keyframes"][-1]["time"]), float(duration), delta=0.01)

    def test_story_map_stage_accepts_long_form(self):
        for duration in (60, 120, 180):
            destination = self.tmp / f"map_out_{duration}.json"
            result = subprocess.run(
                [sys.executable, "tools/build_story_map.py",
                 str(self.map), str(destination), str(duration),
                 "--json-only", "--fallback", "--theme", "daylight plaza"],
                cwd=ROOT, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr[-2000:])

    def test_legacy_python_renderer_and_node_renderer_share_the_list(self):
        legacy = (ROOT / "tools/render_short.py").read_text(encoding="utf-8")
        self.assertIn("from durations import DURATIONS", legacy)
        self.assertNotIn("choices=(30, 45, 60)", legacy)

        node = (ROOT / "tools/video_renderer/render_short.mjs").read_text(encoding="utf-8")
        match = re.search(r"if \(!\[([^\]]+)\]\.includes\(args\.duration\)\)", node)
        self.assertIsNotNone(match)
        self.assertEqual(
            [int(value) for value in re.findall(r"\d+", match.group(1))],
            list(DURATIONS),
        )

    def test_no_tool_hardcodes_the_old_short_list(self):
        for path in (ROOT / "tools").rglob("*.py"):
            if path.name == "durations.py":
                continue
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("choices=(30, 45, 60)", text, msg=str(path))


if __name__ == "__main__":
    unittest.main()
