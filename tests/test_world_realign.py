import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.build_story_map import default_plan, expand_plan, validate  # noqa: E402


class WorldRealignTests(unittest.TestCase):
    def _plan(self):
        plan = expand_plan(validate(default_plan(), 120, ["Lead", "Friend"], min_props=8), 1260)
        plan["duration"] = 120
        # Inject the defects the review pass must repair.
        plan["props"].append({"name": "Huge Unlit Slab", "shape": "Block", "material": "Slate",
                              "position": [1.234, 6.0, 9.876], "size": [120.0, 90.0, 120.0],
                              "color": [3, 3, 5], "physics": "static"})
        plan["props"].append({"name": "Cast Lane Wall", "shape": "Block", "material": "Concrete",
                              "position": [0.0, 10.0, 24.0], "size": [30.0, 20.0, 4.0],
                              "color": [200, 200, 205], "physics": "static"})
        plan["camera_shots"] = [{"time": 1.0, "position": [0.0, 0.2, 26.0], "target": [0, 5, 24],
                                 "transition": "smooth", "focus_username": "Nobody"},
                                {"time": 200.0, "position": [40.0, 12.0, 60.0], "target": [0, 5, 24],
                                 "transition": "weird", "focus_username": "Lead"}]
        return plan

    def test_review_reports_and_repairs_alignment_brightness_and_cameras(self):
        work = ROOT / "dist"
        work.mkdir(exist_ok=True)
        map_path = work / "realign_test_map.json"
        report_path = work / "realign_test_report.json"
        map_path.write_text(json.dumps(self._plan()), encoding="utf-8")
        try:
            result = subprocess.run(
                [sys.executable, str(ROOT / "tools" / "realign_story_map.py"), str(map_path),
                 "--passes", "2", "--target-parts", "1260", "--duration", "120",
                 "--report", str(report_path)],
                capture_output=True, text=True, check=True)
            self.assertIn("aligned, brightly lit Parts", result.stdout)
            plan = json.loads(map_path.read_text(encoding="utf-8"))
            summary = json.loads(report_path.read_text(encoding="utf-8"))
        finally:
            map_path.unlink(missing_ok=True)
            report_path.unlink(missing_ok=True)

        self.assertGreaterEqual(len(plan["props"]), 1260)
        self.assertEqual(len({p["name"].casefold() for p in plan["props"]}), len(plan["props"]))
        for prop in plan["props"]:
            flat = [prop["position"][0], prop["position"][2]] + list(prop["size"])
            for value in flat:
                self.assertAlmostEqual(round(value / 0.5) * 0.5, value, places=6)
            self.assertAlmostEqual(round(prop["position"][1] / 0.25) * 0.25,
                                   prop["position"][1], places=6)
            luminance = (0.2126 * prop["color"][0] + 0.7152 * prop["color"][1]
                         + 0.0722 * prop["color"][2])
            self.assertGreaterEqual(luminance, 100)
            self.assertLessEqual(max(prop["size"]), 64.0)
        self.assertNotIn("Huge Unlit Slab", {p["name"] for p in plan["props"]})
        self.assertNotIn("Cast Lane Wall", {p["name"] for p in plan["props"]})

        shots = plan["camera_shots"]
        self.assertEqual(shots[0]["time"], 0.0)
        self.assertEqual(shots[-1]["time"], 120.0)
        self.assertEqual([s["time"] for s in shots], sorted(s["time"] for s in shots))
        for shot in shots:
            self.assertEqual(shot["transition"], "smooth")
            self.assertGreaterEqual(shot["position"][1], 4.0)
            self.assertIn(shot["focus_username"], {"Lead", "Friend"})
        self.assertGreaterEqual(summary["totals"].get("dropped_camera_blockers", 0), 2)
        self.assertLess(len(shots), 24)


if __name__ == "__main__":
    unittest.main()
