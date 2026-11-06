import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.build_story_map import (  # noqa: E402
    default_camera_shots, default_face_expressions, default_plan, normalize_camera_shots,
    normalize_face_expressions, validate,
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
        self.assertGreaterEqual(len(face_shots), 2)
        self.assertTrue(all(shot["focus_username"] in CAST for shot in face_shots))
        self.assertEqual(face_shots[0]["face_distance"], 2.2)
        self.assertEqual(face_shots[-1]["face_distance"], 4.0, "face distance is clamped to a usable range")
        self.assertTrue(all(1.6 <= shot["face_distance"] <= 4.0 for shot in clean))

    def test_generated_camera_plan_always_contains_face_shot(self):
        for duration in (30, 60, 120, 180):
            shots = default_camera_shots(duration, CAST)
            self.assertGreaterEqual(sum(1 for shot in shots if shot["framing"] == "face"), 2)

    def test_validated_plan_carries_faces(self):
        plan = validate(default_plan(), 90, CAST, min_props=8)
        self.assertGreaterEqual(len(plan["face_expressions"]), 6)
        self.assertGreaterEqual(sum(1 for shot in plan["camera_shots"] if shot["framing"] == "face"), 2)

    def test_usernames_accept_commas_spaces_and_semicolons(self):
        self.assertEqual(parse("Alpha, Beta ;Gamma\nDelta"), ["Alpha", "Beta", "Gamma", "Delta"])
        self.assertEqual(parse("Alpha,Beta"), ["Alpha", "Beta"])
        self.assertEqual(parse("  Alpha ,  Beta  "), ["Alpha", "Beta"])


if __name__ == "__main__":
    unittest.main()
