from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError

from tools import fetch_roblox_avatars
from tools.validate_short import avatar_asset_type


class AvatarFallbackTests(unittest.TestCase):
    def test_automatic_legacy_mesh_endpoint_is_tried_after_current_endpoint_403(self):
        with tempfile.TemporaryDirectory() as temporary:
            user_id = 12345
            current_endpoint = f"https://thumbnails.roblox.com/v1/users/avatar-3d?userId={user_id}"
            legacy_endpoint = f"https://www.roblox.com/avatar-thumbnail-3d/json?userId={user_id}"
            model_url = "https://t6.rbxcdn.com/avatar-model-json"
            model_json = {
                "obj": "obj-hash", "mtl": "mtl-hash", "textures": [],
                "camera": {"position": {"x": 0, "y": 3, "z": 6}},
                "aabb": {"min": {"x": -1, "y": 0, "z": -1},
                         "max": {"x": 1, "y": 5, "z": 1}},
            }

            def fake_request_json(url, data=None):
                if url == current_endpoint:
                    raise HTTPError(url, 403, "Forbidden", None, None)
                if url == legacy_endpoint:
                    return {"Url": model_url, "Final": True}
                if url == model_url:
                    return model_json
                raise AssertionError(f"Unexpected JSON request: {url}")

            def fake_request_bytes(url, data=None):
                if url == fetch_roblox_avatars.cdn_url("obj-hash"):
                    return b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"
                if url == fetch_roblox_avatars.cdn_url("mtl-hash"):
                    return b"newmtl avatar\nKd 1 1 1\n"
                raise AssertionError(f"Unexpected asset request: {url}")

            with (
                mock.patch.object(fetch_roblox_avatars, "request_json", side_effect=fake_request_json),
                mock.patch.object(fetch_roblox_avatars, "request_bytes", side_effect=fake_request_bytes),
            ):
                profile = fetch_roblox_avatars.fetch_avatar_model(user_id, Path(temporary))

            self.assertEqual(profile["model_source"], "legacy-avatar-3d")
            self.assertTrue(profile["model_ready"])
            self.assertIn("v 0 0 0", Path(profile["model_obj"]).read_text(encoding="utf-8"))
            self.assertTrue(Path(profile["model_mtl"]).is_file())

    def test_pixel_reader_uses_pillows_non_deprecated_api_when_available(self):
        class ImageWithFlattenedPixels:
            def get_flattened_data(self):
                return [(1, 2, 3, 255)]

            def getdata(self):
                raise AssertionError("deprecated getdata() should not be used when Pillow provides get_flattened_data()")

        self.assertEqual(fetch_roblox_avatars.image_pixels(ImageWithFlattenedPixels()), [(1, 2, 3, 255)])

    def test_mesh_403_keeps_the_users_real_roblox_thumbnail(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "profiles.json"
            usernames = root / "cast.json"
            usernames.write_text('["RealUser"]', encoding="utf-8")
            assets = root / "avatar-assets"
            calls = []

            def fake_request_json(url, data=None):
                calls.append(url)
                if url == "https://users.roblox.com/v1/usernames/users":
                    return {"data": [{"requestedUsername": "RealUser", "id": 12345}]}
                if url.startswith("https://thumbnails.roblox.com/v1/users/avatar?"):
                    return {"data": [{"imageUrl": "https://roblox.example/avatar.png"}]}
                raise AssertionError(f"Unexpected Roblox API request: {url}")

            def save_actual_thumbnail(_url, path):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"actual Roblox thumbnail bytes")
                return {"thumbnail": str(path), "skin_rgb": [120, 100, 80]}

            stderr = StringIO()
            with (
                mock.patch.object(sys, "argv", ["fetch_roblox_avatars.py", str(usernames), str(output), str(assets)]),
                mock.patch.object(fetch_roblox_avatars, "request_json", side_effect=fake_request_json),
                mock.patch.object(fetch_roblox_avatars, "profile_from_thumbnail", side_effect=save_actual_thumbnail),
                mock.patch.object(fetch_roblox_avatars, "fetch_avatar_model", side_effect=HTTPError(
                    "https://thumbnails.roblox.com/avatar-3d", 403, "Forbidden", None, None
                )),
                redirect_stderr(stderr),
            ):
                fetch_roblox_avatars.main()

            profile = json.loads(output.read_text(encoding="utf-8"))[0]
            self.assertEqual(profile["username"], "RealUser")
            self.assertEqual(profile["user_id"], 12345)
            self.assertFalse(profile["model_ready"])
            self.assertTrue(profile["thumbnail_ready"])
            self.assertIn("403", profile["mesh_error"])
            self.assertEqual(Path(profile["thumbnail"]).read_bytes(), b"actual Roblox thumbnail bytes")
            self.assertIn("not a generated substitute", stderr.getvalue())
            self.assertEqual(len(calls), 2)

    def test_validator_accepts_existing_thumbnail_when_mesh_is_unavailable(self):
        with tempfile.TemporaryDirectory() as temporary:
            thumbnail = Path(temporary) / "avatar.png"
            thumbnail.write_bytes(b"real thumbnail")
            self.assertEqual(avatar_asset_type({
                "model_ready": False,
                "thumbnail_ready": True,
                "thumbnail": str(thumbnail),
            }), "thumbnail")
            self.assertIsNone(avatar_asset_type({
                "model_ready": False,
                "thumbnail_ready": True,
                "thumbnail": str(thumbnail.with_name("missing.png")),
            }))

    def test_full_mesh_remains_preferred_over_thumbnail(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            obj = root / "avatar.obj"
            mtl = root / "avatar.mtl"
            thumbnail = root / "avatar.png"
            for path in (obj, mtl, thumbnail):
                path.write_bytes(b"asset")
            self.assertEqual(avatar_asset_type({
                "model_ready": True,
                "model_obj": str(obj),
                "model_mtl": str(mtl),
                "thumbnail_ready": True,
                "thumbnail": str(thumbnail),
            }), "mesh")


if __name__ == "__main__":
    unittest.main()
