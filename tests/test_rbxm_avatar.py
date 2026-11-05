from __future__ import annotations

import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.convert_rbxm_avatar import parse_legacy_mesh, write_avatar


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
