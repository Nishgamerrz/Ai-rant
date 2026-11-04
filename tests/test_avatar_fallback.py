from __future__ import annotations

import json
import os
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

    def test_scoped_open_cloud_key_authenticates_only_the_official_avatar_mesh_request(self):
        with tempfile.TemporaryDirectory() as temporary:
            user_id = 12345
            endpoint = f"https://thumbnails.roblox.com/v1/users/avatar-3d?userId={user_id}"
            model_url = "https://t6.rbxcdn.com/avatar-model-json"
            calls = []
            model_json = {
                "obj": "obj-hash", "mtl": "mtl-hash", "textures": [],
                "camera": {"position": {"x": 0, "y": 3, "z": 6}},
                "aabb": {"min": {"x": -1, "y": 0, "z": -1},
                         "max": {"x": 1, "y": 5, "z": 1}},
            }

            def fake_request_json(url, data=None, headers=None):
                calls.append((url, headers))
                if url == endpoint:
                    return {"state": "Completed", "imageUrl": model_url}
                if url == model_url:
                    return model_json
                raise AssertionError(f"Unexpected JSON request: {url}")

            def fake_request_bytes(url, data=None, headers=None):
                if url == fetch_roblox_avatars.cdn_url("obj-hash"):
                    return b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"
                if url == fetch_roblox_avatars.cdn_url("mtl-hash"):
                    return b"newmtl avatar\nKd 1 1 1\n"
                raise AssertionError(f"Unexpected asset request: {url}")

            with (
                mock.patch.dict(os.environ, {"ROBLOX_OPEN_CLOUD_API_KEY": "unit-test-key"}),
                mock.patch.object(fetch_roblox_avatars, "request_json", side_effect=fake_request_json),
                mock.patch.object(fetch_roblox_avatars, "request_bytes", side_effect=fake_request_bytes),
            ):
                profile = fetch_roblox_avatars.fetch_avatar_model(user_id, Path(temporary))

            self.assertTrue(profile["model_ready"])
            self.assertEqual(calls[0], (endpoint, {"x-api-key": "unit-test-key"}))
            self.assertEqual(calls[1], (model_url, None))
            self.assertNotIn("unit-test-key", json.dumps(profile))

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

            def fake_request_json(url, data=None, headers=None):
                calls.append((url, data, headers))
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
            self.assertEqual(calls[0], ("https://users.roblox.com/v1/usernames/users",
                                       {"usernames": ["RealUser"], "excludeBannedUsers": False}, None))
            self.assertEqual(len(calls), 2)

    def test_matching_users_folder_obj_is_loaded_before_remote_mesh_lookup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            users_root = root / "users"
            local_model = users_root / "alicewonder"
            local_model.mkdir(parents=True)
            (local_model / "avatar.obj").write_text(
                "mtllib avatar.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", encoding="utf-8"
            )
            (local_model / "avatar.mtl").write_text("newmtl avatar\nKd 1 1 1\nmap_Kd shirt.png\n", encoding="utf-8")
            (local_model / "shirt.png").write_bytes(b"local texture fixture")
            username_file = root / "cast.json"
            username_file.write_text('["AliceWonder"]', encoding="utf-8")
            output = root / "profiles.json"
            assets = root / "avatar-assets"
            api_calls = []

            def fake_request_json(url, data=None, headers=None):
                api_calls.append((url, data, headers))
                if url == "https://users.roblox.com/v1/usernames/users":
                    return {"data": [{"requestedUsername": "AliceWonder", "id": 998877}]}
                if url.startswith("https://thumbnails.roblox.com/v1/users/avatar?"):
                    return {"data": [{"imageUrl": "https://roblox.example/avatar.png"}]}
                raise AssertionError(f"Unexpected request: {url}")

            def save_thumbnail(_url, path):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"official thumbnail")
                return {"thumbnail": str(path), "skin_rgb": [120, 100, 80]}

            with (
                mock.patch.object(sys, "argv", ["fetch_roblox_avatars.py", str(username_file), str(output), str(assets)]),
                mock.patch.object(fetch_roblox_avatars, "USERS_ROOT", users_root),
                mock.patch.object(fetch_roblox_avatars, "request_json", side_effect=fake_request_json),
                mock.patch.object(fetch_roblox_avatars, "profile_from_thumbnail", side_effect=save_thumbnail),
                mock.patch.object(fetch_roblox_avatars, "fetch_avatar_model", side_effect=AssertionError("should use local OBJ")),
            ):
                fetch_roblox_avatars.main()

            profile = json.loads(output.read_text(encoding="utf-8"))[0]
            self.assertEqual(profile["username"], "AliceWonder")
            self.assertEqual(profile["user_id"], 998877)
            self.assertTrue(profile["model_ready"])
            self.assertEqual(profile["model_source"], "users-folder")
            self.assertTrue(Path(profile["model_obj"]).is_file())
            self.assertTrue(Path(profile["model_mtl"]).is_file())
            self.assertTrue((assets / "998877" / "shirt.png").is_file())
            self.assertEqual(api_calls[0][1], {"usernames": ["AliceWonder"], "excludeBannedUsers": False})

    def test_local_mesh_still_works_if_banned_username_is_not_resolved_by_public_lookup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            local_model = root / "users" / "BannedRobloxUser"
            local_model.mkdir(parents=True)
            (local_model / "avatar.obj").write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", encoding="utf-8")
            usernames = root / "cast.json"
            usernames.write_text('["BannedRobloxUser"]', encoding="utf-8")
            output = root / "profiles.json"

            def unavailable_lookup(url, data=None, headers=None):
                raise HTTPError(url, 403, "Unavailable", None, None)

            with (
                mock.patch.object(sys, "argv", ["fetch_roblox_avatars.py", str(usernames), str(output), str(root / "assets")]),
                mock.patch.object(fetch_roblox_avatars, "USERS_ROOT", root / "users"),
                mock.patch.object(fetch_roblox_avatars, "request_json", side_effect=unavailable_lookup),
                mock.patch.object(fetch_roblox_avatars, "fetch_avatar_model", side_effect=AssertionError("local OBJ should be used")),
            ):
                fetch_roblox_avatars.main()

            profile = json.loads(output.read_text(encoding="utf-8"))[0]
            self.assertEqual(profile["user_id"], "local-bannedrobloxuser")
            self.assertTrue(profile["model_ready"])
            self.assertEqual(profile["model_source"], "users-folder")

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
