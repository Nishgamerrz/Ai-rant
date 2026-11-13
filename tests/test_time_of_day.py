from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from time_of_day import (  # noqa: E402
    CLOCK_TIMES, SCENE_TIME_CHOICES, apply_scene_time_sequence,
    resolve_time_of_day, scene_time_sequence,
)
from build_story_map import configure_plan_time_of_day  # noqa: E402
from plan_schema import build_schema  # noqa: E402


class TimeOfDayTests(unittest.TestCase):
    def test_explicit_choices_and_aliases_win_over_story_context(self):
        self.assertEqual(resolve_time_of_day("night", "bright noon"), "night")
        self.assertEqual(resolve_time_of_day("sunset", "a moonlit midnight"), "sunset")
        self.assertEqual(resolve_time_of_day("evening"), "sunset")
        self.assertEqual(resolve_time_of_day("early-morning"), "dawn")
        self.assertEqual(set(CLOCK_TIMES), set(SCENE_TIME_CHOICES))

    def test_auto_uses_story_hour_and_defaults_to_readable_daylight(self):
        self.assertEqual(resolve_time_of_day("auto", "A moonlit snowy village"), "night")
        self.assertEqual(resolve_time_of_day("auto", "A warm sunset over a village"), "sunset")
        self.assertEqual(resolve_time_of_day("auto", "A quiet sunrise in the hills"), "dawn")
        self.assertEqual(resolve_time_of_day("auto", "A green park"), "day")

    def test_invalid_global_choice_fails_actionably(self):
        with self.assertRaisesRegex(ValueError, "choose from auto, dawn, day, sunset, night"):
            resolve_time_of_day("midnight-blue")

    def test_map_schema_requires_an_ai_global_hour_and_exposes_optional_shot_overrides(self):
        schema = build_schema(["Lead"])
        shot = schema['properties']['camera_shots']['items']
        self.assertEqual(schema['properties']['time_of_day']['enum'], list(SCENE_TIME_CHOICES))
        self.assertIn('time_of_day', schema['required'])
        self.assertEqual(shot['properties']['time_of_day']['enum'], list(SCENE_TIME_CHOICES))
        self.assertNotIn('time_of_day', shot['required'], 'most shots inherit the previous/global hour')

    def test_ordered_scene_notes_support_the_procedural_fallback(self):
        self.assertEqual(scene_time_sequence("Opening at night, later at sunset, then night again."),
                         ["night", "sunset", "night"])
        shots = [{"time": index * 4} for index in range(8)]
        self.assertTrue(apply_scene_time_sequence(shots, "start at night, then sunset"))
        self.assertEqual([shot["time_of_day"] for shot in shots],
                         ["night"] * 4 + ["sunset"] * 4)
        untouched = [{"time": 0}]
        self.assertFalse(apply_scene_time_sequence(untouched, "use blue lighting"))
        self.assertEqual(untouched, [{"time": 0}])

    def test_global_choice_removes_unrequested_ai_hour_overrides(self):
        plan = {"camera_shots": [
            {"time": 0, "time_of_day": "night"},
            {"time": 10, "time_of_day": "sunset"},
        ], "scene_time_notes": "old note"}
        resolved, fallback_applied = configure_plan_time_of_day(plan, "day", "a village")
        self.assertEqual(resolved, "day")
        self.assertFalse(fallback_applied)
        self.assertEqual(plan["time_of_day"], "day")
        self.assertEqual(plan["time_of_day_mode"], "global")
        self.assertNotIn("scene_time_notes", plan)
        self.assertTrue(all("time_of_day" not in shot for shot in plan["camera_shots"]))

    def test_ai_global_and_scene_hours_survive_without_manual_time_inputs(self):
        shots = [
            {"time": 0, "time_of_day": "night"},
            {"time": 15},
            {"time": 30, "time_of_day": "sunset"},
            {"time": 45},
        ]
        plan = {"time_of_day": "night", "camera_shots": shots}
        resolved, fallback_applied = configure_plan_time_of_day(
            plan, "auto", "A bright midday theme with an overnight mystery")
        self.assertEqual(resolved, "night", "AI-authored global hour takes precedence over word heuristics")
        self.assertFalse(fallback_applied)
        self.assertEqual(plan["time_of_day_mode"], "per_scene")
        self.assertEqual([shot.get("time_of_day") for shot in shots],
                         ["night", None, "sunset", None])
        self.assertNotIn("scene_time_notes", plan)

    def test_auto_can_infer_the_initial_hour_from_scene_notes(self):
        plan = {"camera_shots": [{"time": index * 5} for index in range(6)]}
        resolved, fallback_applied = configure_plan_time_of_day(
            plan, "auto", "A quiet village story", "Opening at night, ending at sunset")
        self.assertEqual(resolved, "night")
        self.assertTrue(fallback_applied)
        self.assertEqual(plan["time_of_day_mode"], "per_scene")
        self.assertEqual(plan["scene_time_notes"], "Opening at night, ending at sunset")
        self.assertEqual([shot["time_of_day"] for shot in plan["camera_shots"]],
                         ["night"] * 3 + ["sunset"] * 3)

    def test_scene_notes_do_not_overwrite_ai_authored_hour_overrides(self):
        shots = [
            {"time": 0, "time_of_day": "night"},
            {"time": 10},
            {"time": 20, "time_of_day": "sunset"},
        ]
        plan = {"camera_shots": shots}
        resolved, fallback_applied = configure_plan_time_of_day(
            plan, "day", "story", "opening night, middle day, final sunset")
        self.assertEqual(resolved, "day")
        self.assertFalse(fallback_applied)
        self.assertEqual([shot.get("time_of_day") for shot in shots], ["night", None, "sunset"])
        self.assertEqual(plan["time_of_day_mode"], "per_scene")

    def test_unrecognized_time_notes_keep_the_global_hour(self):
        plan = {"camera_shots": [{"time": 0}, {"time": 30}]}
        resolved, fallback_applied = configure_plan_time_of_day(
            plan, "sunset", "story", "keep the cool blue lighting consistent")
        self.assertEqual(resolved, "sunset")
        self.assertFalse(fallback_applied)
        self.assertEqual(plan["time_of_day_mode"], "global")
        self.assertTrue(all("time_of_day" not in shot for shot in plan["camera_shots"]))


if __name__ == "__main__":
    unittest.main()
