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

from narration_rate import rate_for_target  # noqa: E402
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
    """Fill-rate corrections must include the rate used for the measured take.

    Run #124: 112.27 s at +4% was retried at -15%, producing 137.38 s for a
    132 s video. The old calculation treated the first take as normal speed.
    """

    WORKFLOW = (ROOT / ".github" / "workflows" / "main.yml").read_text(encoding="utf-8")

    @staticmethod
    def fill_rate(seconds: float, target: float, current_rate: str = "+4%") -> int:
        return rate_for_target(seconds, target, current_rate)

    def test_the_workflow_uses_the_measured_rate_in_its_correction(self):
        self.assertIn("python tools/narration_rate.py", self.WORKFLOW)
        self.assertIn('"$NARRATION_SECONDS" "$DURATION_SECONDS" --current-rate="$RATE"', self.WORKFLOW)
        self.assertNotIn("seconds / target - 1", self.WORKFLOW)

    def test_run_124_short_take_does_not_get_over_slowed(self):
        self.assertEqual(self.fill_rate(112.27, 132, "+4%"), -12)

    def test_a_second_measurement_accounts_for_the_rate_of_the_first_retry(self):
        self.assertEqual(self.fill_rate(137.38, 132, "-15%"), -12)

    def test_a_short_take_slows_down_and_respects_the_cap(self):
        self.assertEqual(self.fill_rate(74.09, 128, "+4%"), -20)
        self.assertEqual(self.fill_rate(120, 128, "+4%"), -2)
        self.assertLess(self.fill_rate(74.09, 128, "+4%"), 0)

    def test_a_long_take_speeds_up_only_to_the_lively_rate_cap(self):
        self.assertEqual(self.fill_rate(140, 128, "+4%"), 4)

    def test_the_cap_keeps_it_a_story_short(self):
        self.assertEqual(self.fill_rate(10, 180, "+4%"), -20)

    def test_an_overlong_fill_candidate_is_never_selected(self):
        self.assertIn("$FILLED <= $maximum", self.WORKFLOW)
        self.assertIn("abs($FILLED - $DURATION_SECONDS) < abs($NARRATION_SECONDS - $DURATION_SECONDS)",
                      self.WORKFLOW)
        self.assertIn("the first take stands", self.WORKFLOW)


if __name__ == "__main__":
    unittest.main()


class AvatarPreflightTests(unittest.TestCase):
    """The same check must run in the first minutes as well as at the gate.

    Run #84 discovered its missing avatar 52 minutes and 3840 frames too late.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.profiles = self.root / "avatar_profiles.json"
        self.assets = self.root / "avatar-assets"

    def tearDown(self):
        self._tmp.cleanup()

    def write_profile(self, payload: list) -> None:
        import json
        self.profiles.write_text(json.dumps(payload), encoding="utf-8")

    def write_asset(self, user_id: str, name: str, payload: bytes = b"mesh") -> None:
        path = self.assets / user_id / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

    def run_check(self):
        import contextlib
        from io import StringIO
        sys.path.insert(0, str(ROOT / "tools"))
        import check_avatar_assets
        out, err = StringIO(), StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = check_avatar_assets.check(self.profiles)
        return code, out.getvalue(), err.getvalue()

    def test_a_glb_mesh_passes_before_the_run_starts(self):
        self.write_asset("777", "noob.glb")
        self.write_profile([{"username": "noob", "user_id": 777, "model_ready": True,
                             "model_file": "noob.glb", "model_format": "glb"}])
        code, out, _ = self.run_check()
        self.assertEqual(code, 0)
        self.assertIn("authentic 3D mesh", out)

    def test_a_portrait_only_avatar_is_allowed_but_reported(self):
        self.write_asset("777", "avatar.png", b"\x89PNG")
        self.write_profile([{"username": "noob", "user_id": 777, "model_ready": False,
                             "thumbnail_ready": True,
                             "thumbnail": str(self.assets / "777" / "avatar.png")}])
        code, out, _ = self.run_check()
        self.assertEqual(code, 0)
        self.assertIn("portrait", out)

    def test_an_avatar_with_nothing_fails_immediately(self):
        self.write_profile([{"username": "ghost", "user_id": 999, "model_ready": True,
                             "model_file": "ghost.glb", "model_format": "glb",
                             "mesh_error": "asset privacy"}])
        code, _, err = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("ghost", err)
        self.assertIn("stopping now instead of after the render", err)

    def test_the_workflow_runs_the_preflight_right_after_the_avatars(self):
        workflow = (ROOT / ".github" / "workflows" / "main.yml").read_text(encoding="utf-8")
        fetched = workflow.index("tools/convert_rbxm_avatar.py")
        preflight = workflow.index("tools/check_avatar_assets.py")
        later = workflow.index("Write a believable real-life story")
        self.assertLess(fetched, preflight)
        self.assertLess(preflight, later)
