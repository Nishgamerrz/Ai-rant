"""The short length is free-form: any moment the user picks, never a round minute.

Two things must keep working:
  * an exact request ("2:24", "144", "1m47s") reaches every stage unchanged, and
  * a window ("2-3m") is honoured as a ceiling the AI ends inside -- 2:59 is fine,
    3:00 and 3:01 are not.
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

from durations import (  # noqa: E402
    MAX_DURATION,
    MIN_DURATION,
    SUGGESTED_DURATIONS,
    check_duration,
    choose_from_selection,
    choose_length,
    format_duration,
    parse_duration,
    parse_spec,
    selection_window,
)


class ParsesWhatAPersonTypesTests(unittest.TestCase):
    def test_exact_lengths(self):
        cases = {
            "144": 144, 144: 144, "2:24": 144, "02:24": 144, "1:47": 107,
            "1m47s": 107, "2m24s": 144, "2 min 24 sec": 144, "90s": 90,
            "2 min and 30 sec": 150, "0:45": 45, "150.4": 150,
        }
        for raw, expected in cases.items():
            self.assertEqual(parse_duration(raw), expected, msg=repr(raw))
            self.assertEqual(format_duration(expected), format_duration(parse_duration(raw)))

    def test_format_is_clock_style(self):
        self.assertEqual(format_duration(144), "2:24")
        self.assertEqual(format_duration(59), "0:59")
        self.assertEqual(format_duration(180), "3:00")
        self.assertEqual(format_duration(65.4), "1:05")

    def test_rejects_nonsense_and_out_of_range(self):
        for bad in ("", "abc", None, True, "2:xx", 5, 900, "10:00"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                parse_duration(bad)

    def test_check_duration_returns_seconds(self):
        self.assertEqual(check_duration("2:24"), 144.0)
        self.assertEqual(check_duration(144), 144.0)
        with self.assertRaises(ValueError):
            check_duration("2-3m")  # windows are settled by choose_length


class WindowTests(unittest.TestCase):
    def test_windows_parse_to_bounds(self):
        for spec in ("2-3m", "2 to 3 min", "2:00-3:00", "120-180",
                     "between 2 and 3 min", "2m-3m", "2-3 minutes"):
            self.assertEqual(parse_spec(spec), (120, 180), msg=spec)
        self.assertEqual(parse_spec("2:24"), (144, 144))
        self.assertEqual(parse_spec("1:40-2:10"), (100, 130))

    def test_pick_never_lands_on_a_round_minute(self):
        for seed in range(40):
            seconds = choose_length("2-3m", seed=seed)
            self.assertGreaterEqual(seconds, 120)
            self.assertLess(seconds, 180, "a 2-3m window must never reach 3:00")
            self.assertNotEqual(seconds % 60, 0)

    def test_pick_varies_and_can_reach_2_59(self):
        picks = {choose_length("2-3m", seed=seed) for seed in range(60)}
        self.assertGreater(len(picks), 3, "the ending should not always be the same second")
        self.assertTrue(all(120 <= value <= 179 for value in picks))

    def test_pick_stays_inside_short_windows(self):
        for seed in range(20):
            self.assertTrue(100 <= choose_length("1:40-2:10", seed=seed) <= 130)

    def test_exact_request_is_never_changed(self):
        for seed in range(5):
            self.assertEqual(choose_length("2:24", seed=seed), 144)

    def test_window_outside_supported_range_is_rejected(self):
        for spec in ("0-1m", "10-20m"):
            with self.assertRaises(ValueError, msg=spec):
                parse_spec(spec)


class DropdownPlusAiSecondsTests(unittest.TestCase):
    """Pick the length from the menu; the AI picks the exact seconds."""

    def test_menu_is_the_old_selection(self):
        self.assertEqual(SUGGESTED_DURATIONS, (30, 45, 60, 90, 120, 150, 180))

    def test_each_selection_stays_inside_its_own_minute(self):
        expected = {
            30: (30, 59), 45: (45, 59), 60: (60, 119), 90: (90, 119),
            120: (120, 179), 150: (150, 179), 180: (180, 239),
        }
        for selection, window in expected.items():
            self.assertEqual(selection_window(selection), window, msg=selection)

    def test_pick_never_leaves_the_selected_minute(self):
        for selection in SUGGESTED_DURATIONS:
            low, high = selection_window(selection)
            for seed in range(30):
                seconds = choose_from_selection(selection, seed=seed)
                self.assertGreaterEqual(seconds, low, msg=(selection, seconds))
                self.assertLessEqual(seconds, high, msg=(selection, seconds))
                self.assertNotEqual(seconds % 60, 0, "never a round minute")

    def test_two_minutes_never_becomes_three(self):
        for seed in range(40):
            seconds = choose_from_selection(120, seed=seed)
            self.assertLess(seconds, 180)
            self.assertGreaterEqual(seconds, 120)

    def test_one_minute_can_end_at_145_without_crossing_into_two_minutes(self):
        self.assertEqual(selection_window("1m"), (60, 119))
        self.assertEqual(format_duration(choose_from_selection("1m", seed=19)), "1:45")
        for seed in range(80):
            seconds = choose_from_selection("1m", seed=seed)
            self.assertGreaterEqual(seconds, 60)
            self.assertLess(seconds, 120)
            self.assertNotEqual(format_duration(seconds), "2:01")

    def test_pick_varies_between_runs(self):
        picks = {choose_from_selection(120, seed=seed) for seed in range(60)}
        self.assertGreater(len(picks), 5)

    def test_same_seed_repeats_so_a_rerun_is_reproducible(self):
        self.assertEqual(choose_from_selection(120, seed="abc"),
                         choose_from_selection(120, seed="abc"))

    def test_selection_accepts_the_strings_the_form_sends(self):
        self.assertEqual(selection_window("120"), (120, 179))
        self.assertEqual(selection_window("30"), (30, 59))


class EveryToolAcceptsAnyLengthTests(unittest.TestCase):
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
                {"time": 63.4, "position": [-12, 14, 18], "target": [0, 3, 24], "transition": "smooth"},
                {"time": 144, "position": [12, 14, 18], "target": [0, 3, 24], "transition": "snap"},
            ],
        }
        self.map.write_text(json.dumps(plan), encoding="utf-8")
        self.cast.write_text(json.dumps(["Lead"]), encoding="utf-8")
        self.narration = self.tmp / "narration.txt"
        self.narration.write_text("Maya found the lost wallet. " * 60, encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_studio_builder_takes_the_exact_moment(self):
        for written, seconds in (("60", 60), ("2:24", 144), ("1m47s", 107), ("180", 180)):
            output = self.tmp / f"place_{seconds}.rbxlx"
            readme = self.tmp / f"README_{seconds}.md"
            result = subprocess.run(
                [sys.executable, "tools/build_studio_experience.py",
                 "--map", str(self.map), "--cast", str(self.cast),
                 "--duration", written, "--narration", str(self.narration),
                 "--output", str(output), "--readme", str(readme)],
                cwd=ROOT, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr[-2000:])
            self.assertIn(f'"duration":{seconds}', output.read_text(encoding="utf-8"))
            self.assertIn(format_duration(seconds), readme.read_text(encoding="utf-8"))

    def test_studio_builder_rejects_impossible_lengths(self):
        result = subprocess.run(
            [sys.executable, "tools/build_studio_experience.py",
             "--map", str(self.map), "--cast", str(self.cast),
             "--duration", "9:00", "--output", str(self.tmp / "nope.rbxlx")],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duration", result.stderr.lower())

    def test_sound_bed_gate_takes_any_length(self):
        from create_sound_bed import resolve_duration

        for written, seconds in (("144", 144), ("2:24", 144), ("1m47s", 107)):
            self.assertEqual(resolve_duration(written), float(seconds))
        for bad in ("5", "9:00", "abc"):
            with self.assertRaises(SystemExit):
                resolve_duration(bad)

    def test_roblox_animation_stretches_to_the_exact_second(self):
        animation = {
            "name": "StoryGesture",
            "keyframes": [
                {"time": index * 0.5, "poses": {"UpperTorso": [0, index, 0]}}
                for index in range(14)
            ],
        }
        source = self.tmp / "animation.json"
        source.write_text(json.dumps(animation), encoding="utf-8")
        for written, seconds in (("2:24", 144), ("180", 180)):
            destination = self.tmp / f"anim_{seconds}.json"
            result = subprocess.run(
                [sys.executable, "tools/build_roblox_animation.py",
                 str(source), str(destination), written, "--json-only"],
                cwd=ROOT, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr[-2000:])
            data = json.loads(destination.read_text(encoding="utf-8"))
            self.assertAlmostEqual(float(data["duration_seconds"]), float(seconds), delta=0.01)
            self.assertAlmostEqual(float(data["keyframes"][-1]["time"]), float(seconds), delta=0.01)

    def test_story_map_stage_takes_the_exact_moment(self):
        for written, seconds in (("2:24", 144), ("180", 180)):
            destination = self.tmp / f"map_out_{seconds}.json"
            result = subprocess.run(
                [sys.executable, "tools/build_story_map.py",
                 str(self.map), str(destination), written,
                 "--json-only", "--fallback", "--theme", "daylight plaza"],
                cwd=ROOT, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr[-2000:])

    def test_narration_word_targets_scale_with_any_length(self):
        response = self.tmp / "narration_response.json"
        # Unique sentences so the extractor keeps every word; enough text for 144 s.
        sentences = [
            f"Beat {index} shows Maya crossing the busy market square with her friend."
            for index in range(18)
        ]
        words = " ".join(sentences)
        self.assertTrue(216 <= len(words.split()) <= 240, len(words.split()))
        response.write_text(
            json.dumps({"message": {"content": json.dumps({"narration": words})}}),
            encoding="utf-8",
        )
        output = self.tmp / "narration_out.txt"
        result = subprocess.run(
            [sys.executable, "tools/prepare_narration.py", str(response), str(output), "2:24"],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr[-2000:])
        self.assertTrue(output.read_text(encoding="utf-8").strip())


class SharedRulesTests(unittest.TestCase):
    def test_node_renderer_uses_the_same_bounds(self):
        node = (ROOT / "tools/video_renderer/render_short.mjs").read_text(encoding="utf-8")
        self.assertIsNone(
            re.search(r"\[\s*30,\s*45,\s*60", node),
            "the renderer must not hardcode a preset list any more")
        self.assertIn(f"const MIN_DURATION = {MIN_DURATION};", node)
        self.assertIn(f"const MAX_DURATION = {MAX_DURATION};", node)

    def test_every_tool_reads_the_shared_module(self):
        for name in (
            "build_studio_experience", "build_story_map", "validate_short",
            "render_short", "create_sound_bed", "build_roblox_animation",
            "prepare_narration", "package_studio_deliverables",
        ):
            text = (ROOT / "tools" / f"{name}.py").read_text(encoding="utf-8")
            self.assertIn("from durations import", text, msg=name)
            self.assertNotIn("choices=(30, 45, 60)", text, msg=name)

    def test_workflow_form_is_a_length_menu_not_a_text_box(self):
        workflow = (ROOT / ".github/workflows/main.yml").read_text(encoding="utf-8")
        start = workflow.index("duration_seconds:")
        block = workflow[start:workflow.index("map_detail:", start)]
        self.assertIn("type: choice", block)
        self.assertNotIn("type: string", block)
        self.assertEqual(
            [int(value) for value in re.findall(r"^\s+- '(\d+)'$", block, re.MULTILINE)],
            list(SUGGESTED_DURATIONS),
        )
        self.assertIn("Set short timing — AI picks the exact ending", workflow)
        self.assertIn("AI picks seconds within your selected minute band", workflow)
        self.assertIn("Short length in seconds; AI keeps the ending within the selected minute band", workflow)
        self.assertNotIn("2½-minute band includes", workflow)
        self.assertIn("selected minute stays fixed", workflow)
        self.assertIn("never at 2:01", workflow)
        for form_path in (ROOT / "web/app/rbxshort/page.tsx",
                          ROOT / "web/components/NewChatModal.tsx"):
            form = form_path.read_text(encoding="utf-8")
            self.assertIn("Short timing", form)
            self.assertIn("AI chooses the exact ending within the selected minute band", form)
            self.assertIn("60s can end at 1:45, never 2:01", form)
        self.assertIn("DURATION_LABEL=", workflow)
        self.assertIn("DURATION_WINDOW=", workflow)
        self.assertNotIn("DURATION_SECONDS: ${{ inputs.duration_seconds }}", workflow)
        self.assertIn("choose_from_selection(raw, seed=seed)", workflow)
        self.assertIn("selection_window(raw)", workflow)

    def test_workflow_tells_the_ai_the_exact_ending(self):
        workflow = (ROOT / ".github/workflows/main.yml").read_text(encoding="utf-8")
        self.assertIn("runs exactly ${DURATION_SECONDS} seconds (${DURATION_LABEL})", workflow)
        self.assertIn("The ending is a specific moment, not a round number", workflow)
        self.assertIn("not on a round minute", workflow)


if __name__ == "__main__":
    unittest.main()
