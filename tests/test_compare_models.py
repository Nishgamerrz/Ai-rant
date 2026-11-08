"""The comparison workflow must be the real generator, twice, with only the model differing.

Testing `hard` against `smart_11b` is only meaningful if everything else is held
constant: same story, same theme, same world detail, same voice, same cast. The
one thing allowed to differ is the model preset, because that is what is being
compared.
"""
from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"
COMPARE = yaml.safe_load((WORKFLOWS / "compare_models.yml").read_text(encoding="utf-8"))


class CompareModelsTests(unittest.TestCase):
    def test_it_calls_the_real_generator_rather_than_a_copy(self):
        for job in COMPARE["jobs"].values():
            self.assertEqual(job["uses"], "./.github/workflows/main.yml")

    def test_it_runs_both_presets(self):
        presets = [job["with"]["model_quality"] for job in COMPARE["jobs"].values()]
        self.assertEqual(sorted(presets), ["hard", "smart_11b"])

    def test_only_the_model_preset_differs(self):
        shared = [
            "story_topic", "world_theme", "character_usernames",
            "duration_seconds", "map_detail", "voice_style",
        ]
        values = {key: {job["with"][key] for job in COMPARE["jobs"].values()} for key in shared}
        for key, seen in values.items():
            self.assertEqual(len(seen), 1, f"{key} differs between the two runs: {seen}")
        # ...and each is wired to the form, not frozen to a literal.
        for key in shared:
            self.assertTrue(str(next(iter(values[key]))).startswith("${{ inputs."), key)

    def test_the_form_defaults_to_the_ultra_world_and_a_real_story(self):
        form = COMPARE[True]["workflow_dispatch"]["inputs"]
        self.assertEqual(form["map_detail"]["default"], "ultra")
        self.assertIn("In a world where", form["story_topic"]["default"])
        self.assertTrue(form["world_theme"]["default"].strip())
        # An empty cast is the one input that makes the generator stop immediately.
        self.assertTrue(form["character_usernames"]["default"].strip())
        self.assertNotEqual(form["character_usernames"]["default"].replace(" ", ""), ",")

    def test_both_callers_allow_the_preview_branch_to_be_pushed(self):
        self.assertEqual(COMPARE["permissions"]["contents"], "write")
        start = yaml.safe_load((WORKFLOWS / "start.yml").read_text(encoding="utf-8"))
        self.assertEqual(start["permissions"]["contents"], "write")

    def test_every_preset_it_offers_is_a_preset_the_generator_knows(self):
        main = yaml.safe_load((WORKFLOWS / "main.yml").read_text(encoding="utf-8"))
        choices = set(main[True]["workflow_dispatch"]["inputs"]["model_quality"]["options"])
        for job in COMPARE["jobs"].values():
            self.assertIn(job["with"]["model_quality"], choices)
        detail = set(main[True]["workflow_dispatch"]["inputs"]["map_detail"]["options"])
        self.assertTrue(set(COMPARE[True]["workflow_dispatch"]["inputs"]["map_detail"]["options"]) <= detail)


if __name__ == "__main__":
    unittest.main()
