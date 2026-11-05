from __future__ import annotations

import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.convert_rbxm_avatar import parse_legacy_mesh, write_avatar
from tools.fetch_roblox_avatars import find_local_avatar_model, find_local_avatar_place, load_local_avatar_model


def make_v2_mesh() -> bytes:
    vertices = [
        (0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 1.0, 0.0),
    ]
    header = struct.pack("<HBBII", 12, 36, 12, 3, 1)
    vertex_bytes = b"".join(struct.pack("<9f", *vertex) for vertex in vertices)
    faces = struct.pack("<III", 0, 1, 2)
    return b"version 2.00\n" + header + vertex_bytes + faces


class RbxmAvatarTests(unittest.TestCase):
    def test_native_animation_ids_survive_external_mesh_401(self):
        importer = (Path(__file__).resolve().parents[1] / "tools/rbxm_importer/prepare_rbxm_avatar.mjs").read_text(encoding="utf-8")
        animation_assignment = importer.index("profile.rbxm_animation_ids = animationIds")
        first_mesh_download = importer.index("for (const part of meshParts)")
        self.assertLess(animation_assignment, first_mesh_download)
        self.assertNotIn("delete profile.rbxm_animation_ids", importer)
        self.assertIn("profile.model_ready && ['users-file', 'users-folder'].includes(profile.model_source)", importer)

    def test_flat_username_rbxm_is_selected_even_if_public_lookup_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            users_root = root / "users"
            users_root.mkdir()
            model = users_root / "NORMAL.RBXM"
            model.write_bytes(b"RBXM fixture; the Node importer validates the actual binary.")
            usernames = root / "cast.json"
            usernames.write_text('["normal"]', encoding="utf-8")
            output = root / "profiles.json"

            def unavailable_lookup(url, data=None, headers=None):
                raise OSError("public lookup unavailable")

            with (
                mock.patch("sys.argv", ["fetch_roblox_avatars.py", str(usernames), str(output), str(root / "assets")]),
                mock.patch("tools.fetch_roblox_avatars.USERS_ROOT", users_root),
                mock.patch("tools.fetch_roblox_avatars.request_json", side_effect=unavailable_lookup),
                mock.patch("tools.fetch_roblox_avatars.fetch_avatar_model", side_effect=AssertionError("RBXM is the local source")),
            ):
                from tools.fetch_roblox_avatars import main
                main()

            profile = json.loads(output.read_text(encoding="utf-8"))[0]
            self.assertEqual(profile["user_id"], "local-normal")
            self.assertEqual(profile["model_source"], "rbxm-file")
            self.assertTrue(profile["rbxm_source_selected"])
            self.assertEqual(Path(profile["rbxm_path"]), model.resolve())
            self.assertFalse(profile.get("model_ready", False))

    def test_flat_obj_is_preferred_and_staged_with_mtl_textures(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "users"
            root.mkdir()
            obj = root / "normal.obj"
            obj.write_text("mtllib normal.mtl\ng Body\nv 0 0 0\nv 0 1 0\nv 1 0 0\nf 1 2 3\n", encoding="utf-8")
            (root / "normal.mtl").write_text("newmtl BodyMtl\nmap_Kd normal_assets/body.png\n", encoding="utf-8")
            (root / "normal_assets").mkdir()
            (root / "normal_assets/body.png").write_bytes(b"fake png fixture")
            (root / "normal.rbxm").write_bytes(b"RBXM exists but a self-contained mesh should win")
            self.assertEqual(find_local_avatar_model("NORMAL", root), obj)

            profile = load_local_avatar_model("normal", 123, root, Path(temporary) / "staged")
            self.assertEqual(profile["model_format"], "obj")
            self.assertEqual(profile["model_file"], "avatar.obj")
            self.assertEqual(profile["model_source"], "users-file")
            self.assertIn("mtllib avatar.mtl", Path(profile["model_obj"]).read_text(encoding="utf-8"))
            self.assertTrue((Path(temporary) / "staged/normal_assets/body.png").is_file())
            self.assertEqual(profile["texture_count"], 1)

    def test_workflow_profile_uses_flat_obj_instead_of_rbxm_or_remote_avatar(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            users_root = root / "users"
            users_root.mkdir()
            (users_root / "normal.obj").write_text("v 0 0 0\nv 0 1 0\nv 1 0 0\nf 1 2 3\n", encoding="utf-8")
            (users_root / "normal.rbxm").write_bytes(b"RBXM with protected mesh references")
            usernames = root / "cast.json"
            usernames.write_text('["normal"]', encoding="utf-8")
            output = root / "profiles.json"

            def lookup(url, data=None, headers=None):
                if "users.roblox.com/v1/usernames/users" in url:
                    return {"data": [{"requestedUsername": "normal", "id": 123}]}
                return {"data": []}

            with (
                mock.patch("sys.argv", ["fetch_roblox_avatars.py", str(usernames), str(output), str(root / "assets")]),
                mock.patch("tools.fetch_roblox_avatars.USERS_ROOT", users_root),
                mock.patch("tools.fetch_roblox_avatars.request_json", side_effect=lookup),
                mock.patch("tools.fetch_roblox_avatars.fetch_avatar_model", side_effect=AssertionError("the local OBJ must skip protected remote mesh lookup")),
            ):
                from tools.fetch_roblox_avatars import main
                main()

            profile = json.loads(output.read_text(encoding="utf-8"))[0]
            self.assertEqual(profile["user_id"], 123)
            self.assertEqual(profile["model_source"], "users-file")
            self.assertEqual(profile["model_format"], "obj")
            self.assertTrue(profile["model_ready"])
            self.assertTrue(profile["rbxm_source_selected"])
            self.assertEqual(Path(profile["rbxm_path"]), (users_root / "normal.rbxm").resolve())

    def test_rbxl_place_is_not_mistaken_for_a_standalone_avatar_mesh(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            place = root / "normal.RBXL"
            place.write_bytes(b"place fixture")
            self.assertEqual(find_local_avatar_place("normal", root), place)
            self.assertIsNone(find_local_avatar_model("normal", root))

    def test_flat_gltf_dependencies_are_staged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "users"
            root.mkdir()
            (root / "normal.gltf").write_text(json.dumps({
                "asset": {"version": "2.0"},
                "buffers": [{"uri": "normal.bin", "byteLength": 4}],
                "images": [{"uri": "textures/body.png"}],
            }), encoding="utf-8")
            (root / "normal.bin").write_bytes(b"1234")
            (root / "textures").mkdir()
            (root / "textures/body.png").write_bytes(b"png fixture")
            profile = load_local_avatar_model("normal", 123, root, Path(temporary) / "staged")
            self.assertEqual(profile["model_format"], "gltf")
            self.assertEqual(profile["texture_count"], 1)
            self.assertTrue((Path(temporary) / "staged/normal.bin").is_file())
            self.assertTrue((Path(temporary) / "staged/textures/body.png").is_file())

    def test_v2_roblox_mesh_parser_and_obj_writer(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            source_mesh = output / "part.mesh"
            source_mesh.write_bytes(make_v2_mesh())
            vertices, faces, flip_v = parse_legacy_mesh(source_mesh.read_bytes())
            self.assertEqual(len(vertices), 3)
            self.assertEqual(faces, [(0, 1, 2)])
            self.assertTrue(flip_v)

            manifest = {
                "format": "rbxm-avatar-manifest-v1",
                "username": "FixtureUser",
                "root_cframe": {"position": [0, 0, 0], "orientation": [1, 0, 0, 0, 1, 0, 0, 0, 1]},
                "parts": [{
                    "name": "Head", "mesh_path": str(source_mesh), "mesh_id": "11",
                    "texture_path": None, "size": [1, 1, 1], "initial_size": [1, 1, 1],
                    "cframe": {"position": [0, 0, 0], "orientation": [1, 0, 0, 0, 1, 0, 0, 0, 1]},
                    "color": [0.25, 0.5, 0.75],
                }],
            }
            manifest_path = output / "rbxm-avatar-manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            obj_path, mtl_path, parts, texture_count = write_avatar(manifest_path)
            obj = obj_path.read_text(encoding="utf-8")
            mtl = mtl_path.read_text(encoding="utf-8")
            self.assertEqual((parts, texture_count), (1, 0))
            self.assertEqual(obj.count("\nv "), 3)
            self.assertIn("f 1/1 2/2 3/3", obj)
            self.assertIn("Kd 0.25 0.5 0.75", mtl)


if __name__ == "__main__":
    unittest.main()
