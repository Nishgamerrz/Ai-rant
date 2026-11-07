"""A finished video must not be thrown away by the quality gate.

Run #84 rendered all 3840 frames of a 128-second short (104 MB, 2:08, both
avatars rigged and animated) and then the gate refused it:

    SHORT NOT APPROVED: authentic Roblox avatar mesh and thumbnail are both
    missing for noob

for `users/noob.glb` - a model the renderer had loaded, rigged and animated a
few minutes earlier. The check demanded a separate `.mtl` file from every model,
but a GLB carries its materials inside the file, so it can never have one.

These tests pin the gate to what is actually on disk.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from validate_short import avatar_asset_type  # noqa: E402


class AvatarGateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.work = Path(self._tmp.name)
        self.assets = self.work / "avatar-assets" / "12345"
        self.assets.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, relative: str, payload: bytes = b"mesh data") -> Path:
        path = self.assets / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return path

    def test_a_glb_model_needs_no_material_file(self):
        self.write("noob.glb")
        profile = {"username": "noob", "model_ready": True, "model_file": "noob.glb",
                   "model_format": "glb"}
        self.assertEqual(avatar_asset_type(profile, self.assets), "mesh")

    def test_every_self_contained_format_passes(self):
        for fmt in ("glb", "gltf", "fbx", "dae", "ply", "stl", "3ds"):
            name = f"model.{fmt}"
            self.write(name)
            profile = {"model_ready": True, "model_file": name, "model_format": fmt}
            self.assertEqual(avatar_asset_type(profile, self.assets), "mesh", fmt)

    def test_an_obj_still_needs_its_material_file(self):
        self.write("avatar.obj")
        profile = {"model_ready": True, "model_file": "avatar.obj", "model_format": "obj"}
        self.assertIsNone(avatar_asset_type(profile, self.assets))
        self.write("avatar.mtl", b"newmtl skin\n")
        self.assertEqual(avatar_asset_type(profile, self.assets), "mesh")

    def test_an_absolute_model_path_still_works(self):
        path = self.write("normal.obj")
        self.write("avatar.mtl", b"newmtl skin\n")
        profile = {"model_ready": True, "model_obj": str(path),
                   "model_mtl": str(self.assets / "avatar.mtl")}
        self.assertEqual(avatar_asset_type(profile, self.assets), "mesh")

    def test_a_missing_model_falls_back_to_the_public_thumbnail(self):
        thumbnail = self.work / "avatar.png"
        thumbnail.write_bytes(b"\x89PNG portrait")
        profile = {"model_ready": True, "model_file": "gone.glb", "model_format": "glb",
                   "thumbnail_ready": True, "thumbnail": str(thumbnail)}
        self.assertEqual(avatar_asset_type(profile, self.assets), "thumbnail")

    def test_nothing_on_disk_is_still_refused(self):
        profile = {"model_ready": True, "model_file": "gone.glb", "model_format": "glb",
                   "thumbnail_ready": True, "thumbnail": str(self.work / "absent.png")}
        self.assertIsNone(avatar_asset_type(profile, self.assets))

    def test_an_empty_file_is_not_a_model(self):
        self.write("noob.glb", b"")
        profile = {"model_ready": True, "model_file": "noob.glb", "model_format": "glb"}
        self.assertIsNone(avatar_asset_type(profile, self.assets))

    def test_the_workflow_hands_the_gate_the_asset_directory(self):
        workflow = (ROOT / ".github" / "workflows" / "main.yml").read_text(encoding="utf-8")
        self.assertIn('args.profiles.parent / "avatar-assets"', (
            ROOT / "tools" / "validate_short.py").read_text(encoding="utf-8"))
        self.assertIn("--profiles dist/avatar_profiles.json", workflow)


class NarrationFillTests(unittest.TestCase):
    """A short voiceover is stretched by speaking slower - not by asking for +0%.

    Run #84: 74.09 s of narration in a 128 s video. The fill pass computed
    `+0%` and changed nothing, so 54 seconds of the finished short were silent.
    """

    WORKFLOW = (ROOT / ".github" / "workflows" / "main.yml").read_text(encoding="utf-8")

    @staticmethod
    def fill_rate(seconds: float, target: float) -> int:
        percent = round((max(0.1, seconds) / target - 1) * 100)
        return max(-20, min(4, percent))

    def test_the_formula_runs_the_right_way_round(self):
        self.assertIn("seconds / target - 1", self.WORKFLOW)
        self.assertNotIn("min(seconds, target)) / max(seconds", self.WORKFLOW)

    def test_a_short_take_slows_down(self):
        self.assertEqual(self.fill_rate(74.09, 128), -20)
        self.assertEqual(self.fill_rate(120, 128), -6)
        self.assertLess(self.fill_rate(74.09, 128), 0)

    def test_a_long_take_speeds_up_a_little(self):
        self.assertGreater(self.fill_rate(140, 128), 0)
        self.assertLessEqual(self.fill_rate(140, 128), 4)

    def test_the_cap_keeps_it_a_story_short(self):
        self.assertEqual(self.fill_rate(10, 180), -20)

    def test_the_slower_take_is_only_kept_if_it_fits_better(self):
        self.assertIn("abs($FILLED - $DURATION_SECONDS) < abs($NARRATION_SECONDS - $DURATION_SECONDS)",
                      self.WORKFLOW)
        self.assertIn("the first take stands", self.WORKFLOW)


if __name__ == "__main__":
    unittest.main()
