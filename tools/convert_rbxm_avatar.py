#!/usr/bin/env python3
"""Convert MeshParts referenced by a username-matched RBXM into renderer assets."""
from __future__ import annotations

import json
import math
import re
import struct
import sys
from io import BytesIO
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))
from roblox_mesh_v4.reader import read_mesh


def parse_legacy_mesh(data: bytes):
    """Read Roblox FileMesh v1/v2 geometry into (vertices, faces, flip_v)."""
    line, separator, rest = data.partition(b"\n")
    if not separator:
        raise ValueError("Roblox mesh is missing its version header")
    version = line.decode("ascii", "replace").strip()
    if version in {"version 4.00", "version 4.01"}:
        mesh = read_mesh(BytesIO(data))
        vertices = [(v.position, v.uv) for v in mesh.vertices]
        faces = mesh.lod_faces(0)
        return vertices, faces, False
    if version == "version 2.00":
        if len(rest) < 12:
            raise ValueError("Roblox v2 mesh has a truncated header")
        header_size, vertex_size, face_size, vertex_count, face_count = struct.unpack_from("<HBBII", rest)
        if header_size != 12 or vertex_size not in (36, 40) or face_size != 12:
            raise ValueError(f"Unsupported Roblox v2 mesh header ({header_size=}, {vertex_size=}, {face_size=})")
        offset = 12
        expected = offset + vertex_count * vertex_size + face_count * face_size
        if vertex_count <= 0 or face_count <= 0 or expected > len(rest) or vertex_count > 5_000_000 or face_count > 5_000_000:
            raise ValueError("Roblox v2 mesh has invalid vertex or face counts")
        vertices = []
        for _ in range(vertex_count):
            values = struct.unpack_from("<9f", rest, offset)
            offset += vertex_size
            vertices.append(((values[0], values[1], values[2]), (values[6], values[7])))
        faces = [struct.unpack_from("<III", rest, offset + index * 12) for index in range(face_count)]
        if any(index >= vertex_count for face in faces for index in face):
            raise ValueError("Roblox v2 mesh contains an out-of-range face index")
        return vertices, faces, True
    if version in {"version 1.00", "version 1.01"}:
        text = data.decode("ascii", "replace")
        tuples = re.findall(r"\[\s*(-?[\d.eE+-]+)\s*,\s*(-?[\d.eE+-]+)\s*,\s*(-?[\d.eE+-]+)\s*\]", text)
        if len(tuples) < 9 or len(tuples) % 9:
            raise ValueError("Roblox v1 mesh contains an invalid triangle list")
        vertices = []
        faces = []
        scale = 0.5 if version == "version 1.00" else 1.0
        for i in range(0, len(tuples), 9):
            face = []
            for j in range(3):
                start = i + j * 3
                pos = tuple(float(value) * scale for value in tuples[start])
                uv_group = tuples[start + 2]
                vertices.append((pos, (float(uv_group[0]), float(uv_group[1]))))
                face.append(len(vertices) - 1)
            faces.append(tuple(face))
        return vertices, faces, True
    raise ValueError(f"Unsupported Roblox mesh format {version!r}; supported versions are 1, 2, and 4")


def mat_vec(rotation, vector):
    return [sum(rotation[row * 3 + column] * vector[column] for column in range(3)) for row in range(3)]


def write_avatar(manifest_path: Path):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format") != "rbxm-avatar-manifest-v1" or not manifest.get("parts"):
        raise ValueError(f"{manifest_path} is not a populated RBXM avatar manifest")
    output_dir = manifest_path.parent
    root_pos = manifest["root_cframe"]["position"]
    root_rot = manifest["root_cframe"]["orientation"]
    inverse_root_rot = [root_rot[c * 3 + r] for r in range(3) for c in range(3)]
    obj_lines = ["# Temporary renderer mesh generated from the user's RBXM model.", "mtllib avatar.mtl"]
    mtl_lines = []
    vertex_offset = 1
    texture_count = 0
    part_count = 0

    for index, part in enumerate(manifest["parts"]):
        mesh_path = Path(part["mesh_path"])
        if not mesh_path.is_file():
            raise ValueError(f"Missing downloaded mesh asset for RBXM part {part['name']}: {mesh_path}")
        vertices, faces, flip_v = parse_legacy_mesh(mesh_path.read_bytes())
        if not vertices or not faces:
            raise ValueError(f"RBXM part {part['name']} has no renderable mesh triangles")
        material = f"rbxm_part_{index:02d}"
        obj_lines.extend([f"o {re.sub(r'[^A-Za-z0-9_ -]', '_', part['name'])}", f"usemtl {material}"])
        position = part["cframe"]["position"]
        rotation = part["cframe"]["orientation"]
        size = part["size"]
        initial_size = part.get("initial_size") or size
        scale = [size[i] / initial_size[i] if abs(initial_size[i]) > 1e-7 else 1.0 for i in range(3)]
        for point, uv in vertices:
            scaled = [point[i] * scale[i] for i in range(3)]
            world = mat_vec(rotation, scaled)
            relative = [world[i] + position[i] - root_pos[i] for i in range(3)]
            local = mat_vec(inverse_root_rot, relative)
            obj_lines.append("v " + " ".join(f"{component:.7g}" for component in local))
        for _, uv in vertices:
            u, v = float(uv[0]), float(uv[1])
            obj_lines.append(f"vt {u:.7g} {1.0 - v if flip_v else v:.7g}")
        for face in faces:
            indices = [int(value) + vertex_offset for value in face]
            obj_lines.append("f " + " ".join(f"{value}/{value}" for value in indices))
        vertex_offset += len(vertices)

        color = part.get("color", [0.8, 0.8, 0.8])
        mtl_lines.extend([f"newmtl {material}", "Ka 0 0 0", "Kd " + " ".join(f"{max(0, min(1, float(c))):.6g}" for c in color), "Ks 0.05 0.05 0.05", "Ns 8"])
        texture_path = part.get("texture_path")
        if texture_path and Path(texture_path).is_file():
            try:
                relative_texture = Path(texture_path).resolve().relative_to(output_dir.resolve()).as_posix()
                mtl_lines.append(f"map_Kd {relative_texture}")
                texture_count += 1
            except ValueError:
                pass
        mtl_lines.append("")
        part_count += 1

    if not part_count:
        raise ValueError("RBXM model contains no supported MeshParts")
    obj_path = output_dir / "avatar.obj"
    mtl_path = output_dir / "avatar.mtl"
    obj_path.write_text("\n".join(obj_lines) + "\n", encoding="utf-8")
    mtl_path.write_text("\n".join(mtl_lines), encoding="utf-8")
    return obj_path, mtl_path, part_count, texture_count


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: convert_rbxm_avatar.py PROFILES.json ASSET_ROOT")
    profiles_path, asset_root = Path(sys.argv[1]), Path(sys.argv[2])
    profiles = json.loads(profiles_path.read_text(encoding="utf-8"))
    for profile in profiles:
        manifest_path = profile.get("rbxm_manifest")
        if not manifest_path:
            continue
        obj_path, mtl_path, parts, textures = write_avatar(Path(manifest_path))
        profile.update({
            "model_obj": str(obj_path.resolve()),
            "model_mtl": str(mtl_path.resolve()),
            "model_ready": True,
            "thumbnail_ready": False,
            "texture_count": textures,
            "front_direction": [0, 0, 1],
            "model_source": "rbxm-file",
            "rbxm_mesh_part_count": parts,
        })
        print(f"Converted {profile['username']}'s RBXM rig into renderer geometry ({parts} MeshParts; {textures} textures).")
    profiles_path.write_text(json.dumps(profiles, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise SystemExit(f"RBXM avatar conversion failed: {exc}") from exc
