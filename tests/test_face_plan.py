import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.build_story_map import (  # noqa: E402
    default_camera_shots, default_face_expressions, default_plan, normalize_camera_shots,
    normalize_face_expressions, target_camera_count, validate,
)
from tools.parse_roblox_usernames import parse  # noqa: E402

CAST = ["LeadRblx", "FriendRblx"]


class FacePlanTests(unittest.TestCase):
    def test_default_expression_arc_follows_the_whole_short(self):
        timeline = default_face_expressions(120, CAST)
        self.assertGreaterEqual(len(timeline), 6)
        times = [beat["time"] for beat in timeline]
        self.assertEqual(times, sorted(times))
        self.assertEqual(times[0], 0.0)
        self.assertLessEqual(times[-1], 120)
        self.assertGreaterEqual(times[-1], 100, "the arc must reach the ending beat")
        self.assertTrue(all(beat["username"] == CAST[0] for beat in timeline))
        self.assertIn("happy", {beat["expression"] for beat in timeline})

    def test_expression_timeline_is_cleaned_and_ordered(self):
        raw = [
            {"time": 30, "expression": "sad", "intensity": 2, "username": "leadrblx"},
            {"time": 5, "expression": "happy", "intensity": 0.4},
            {"time": -1, "expression": "happy"},
            {"time": 12, "expression": "beaming"},
            {"time": 44, "expression": "surprised", "intensity": "loud", "username": "stranger"},
            {"time": 999, "expression": "happy"},
        ]
        timeline = normalize_face_expressions(raw, 120, CAST)
        # The arc always starts at 0s so the face is never blank at the first frame.
        self.assertEqual([beat["time"] for beat in timeline], [0.0, 5, 30, 44])
        self.assertEqual(timeline[0]["expression"], "neutral")
        self.assertEqual(timeline[1]["expression"], "happy")
        self.assertEqual(timeline[2]["username"], CAST[0], "usernames are re-cased to the real cast")
        self.assertEqual(timeline[2]["intensity"], 1.0, "intensity is clamped")
        self.assertEqual(timeline[3]["username"], "", "unknown actors fall back to everyone")
        self.assertEqual(timeline[3]["intensity"], 0.8)
        with_zero = normalize_face_expressions(raw + [{"time": 0, "expression": "happy"}], 120, CAST)
        self.assertEqual(with_zero[0]["time"], 0.0)
        self.assertEqual(with_zero[0]["expression"], "happy")

    def test_bad_or_missing_timeline_falls_back_to_a_full_arc(self):
        self.assertEqual(len(normalize_face_expressions([], 60, CAST)), len(default_face_expressions(60, CAST)))
        self.assertEqual(len(normalize_face_expressions("nope", 60, CAST)), len(default_face_expressions(60, CAST)))

    def test_camera_plan_keeps_face_closeups_and_framing(self):
        shots = [
            {"time": 0, "position": [0, 60, 90], "target": [0, 4, 24], "focus_username": CAST[0]},
            {"time": 10, "position": [4, 6, 30], "target": [0, 5, 24], "focus_username": CAST[0],
             "framing": "face", "face_distance": 2.2, "transition": "snap"},
            {"time": 20, "position": [-20, 20, 60], "target": [0, 4, 24], "focus_username": CAST[1]},
            {"time": 30, "position": [10, 8, 26], "target": [0, 5, 24], "focus_username": CAST[0],
             "framing": "CLOSE", "face_distance": 99},
        ]
        clean = normalize_camera_shots(shots, 60, CAST)
        face_shots = [shot for shot in clean if shot["framing"] == "face"]
        self.assertGreaterEqual(len(face_shots), 3)
        self.assertTrue(all(shot["focus_username"] in CAST for shot in face_shots))
        at_10 = next(shot for shot in clean if shot["time"] == 10)
        at_30 = next(shot for shot in clean if shot["time"] == 30)
        self.assertEqual(at_10["face_distance"], 2.8, "too-tight AI crops are raised to the minimum")
        self.assertEqual(at_30["face_distance"], 4.0, "face distance is clamped to a usable range")
        self.assertTrue(all(2.8 <= shot["face_distance"] <= 4.0 for shot in clean))

    def test_camera_plan_preserves_explicit_scene_hour_overrides(self):
        shots = [
            {"time": 0, "position": [0, 30, 70], "target": [0, 4, 24], "focus_username": CAST[0],
             "time_of_day": "night"},
            {"time": 12, "position": [4, 12, 34], "target": [0, 5, 24], "focus_username": CAST[0]},
            {"time": 25, "position": [-8, 14, 40], "target": [0, 5, 24], "focus_username": CAST[1],
             "time_of_day": "sunset"},
            {"time": 40, "position": [10, 18, 55], "target": [0, 4, 24], "focus_username": CAST[0]},
        ]
        clean = normalize_camera_shots(shots, 60, CAST)
        by_time = {shot["time"]: shot for shot in clean}
        self.assertEqual(by_time[0]["time_of_day"], "night")
        self.assertNotIn("time_of_day", by_time[12], "the hour holds until another override")
        self.assertEqual(by_time[25]["time_of_day"], "sunset")
        self.assertNotIn("time_of_day", by_time[40])
        self.assertNotIn("time_of_day", clean[-1], "the renderer inherits the last scene hour")

    def test_sparse_ai_storyboard_is_densified_with_reference_style_cuts(self):
        sparse = [
            {"time": time, "position": [index * 2, 12 + index, 60 - index * 3],
             "target": [0, 4, 24], "focus_username": CAST[index % len(CAST)],
             "transition": "smooth", "framing": "auto"}
            for index, time in enumerate((0, 12, 24, 36, 48, 60))
        ]
        clean = normalize_camera_shots(sparse, 60, CAST)
        self.assertEqual(len(clean), target_camera_count(60))
        times = [shot["time"] for shot in clean]
        self.assertEqual(times[0], 0)
        self.assertEqual(times[-1], 60)
        self.assertLessEqual(max(b - a for a, b in zip(times, times[1:])), 6)
        self.assertGreaterEqual(sum(shot["transition"] == "snap" for shot in clean), 3)
        self.assertGreaterEqual(sum(shot["framing"] == "face" for shot in clean), 3)

    def test_generated_camera_plan_always_contains_three_face_shots(self):
        for duration in (30, 60, 120, 180):
            shots = default_camera_shots(duration, CAST)
            self.assertGreaterEqual(sum(1 for shot in shots if shot["framing"] == "face"), 3)

    def test_validated_plan_carries_faces(self):
        plan = validate(default_plan(), 90, CAST, min_props=8)
        self.assertGreaterEqual(len(plan["face_expressions"]), 6)
        self.assertGreaterEqual(sum(1 for shot in plan["camera_shots"] if shot["framing"] == "face"), 3)

    def test_usernames_accept_commas_spaces_and_semicolons(self):
        self.assertEqual(parse("Alpha, Beta ;Gamma\nDelta"), ["Alpha", "Beta", "Gamma", "Delta"])
        self.assertEqual(parse("Alpha,Beta"), ["Alpha", "Beta"])
        self.assertEqual(parse("  Alpha ,  Beta  "), ["Alpha", "Beta"])


if __name__ == "__main__":
    unittest.main()
