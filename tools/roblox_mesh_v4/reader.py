"""Binary reader for Roblox ``FileMesh`` version 4 (``version 4.00`` / ``4.01``).

Layout reference: ``docs/MESH_FORMAT.md``. Every struct size in this module was
verified against 708 real v4 meshes rather than taken from a spec document; the
sizes that a naive reading gets wrong are called out in comments.
"""

from __future__ import annotations

import struct
from typing import BinaryIO

from .model import (
    BONE_SIZE,
    FACE_SIZE,
    MAX_SUBSET_BONES,
    NO_INDEX,
    SKINNING_SIZE,
    SUBSET_SIZE,
    VERTEX_SIZE,
    Bone,
    Mesh,
    MeshHeader,
    Skinning,
    Subset,
    Vertex,
)

SUPPORTED_VERSIONS = ("4.00", "4.01")

_HEADER = struct.Struct("<HHIIHHIHBb")
_VERTEX = struct.Struct("<3f3f2f4b4B")
_SKINNING = struct.Struct("<8B")
_FACE = struct.Struct("<3I")
_BONE = struct.Struct("<IHHf9f3f")
# 4 uint32 ranges + uint32 numBoneIndices + 26 uint16 bone indices = 72 bytes.
# Reading numBoneIndices as uint16 (a 70-byte record) still yields a plausible
# first subset on little-endian hardware, then silently corrupts everything
# after it. See docs/MESH_FORMAT.md.
_SUBSET = struct.Struct(f"<4II{MAX_SUBSET_BONES}H")


class MeshFormatError(ValueError):
    """Raised when a file is not a readable version 4 mesh."""


def _read_exact(f: BinaryIO, size: int, what: str) -> bytes:
    data = f.read(size)
    if len(data) != size:
        raise MeshFormatError(
            f"Unexpected end of file reading {what}: wanted {size} bytes, got {len(data)}"
        )
    return data


def read_version(f: BinaryIO) -> str:
    """Consume the ``version X.YY`` line and return the version string."""
    line = f.readline()
    if not line.startswith(b"version "):
        raise MeshFormatError(
            f"Not a Roblox mesh: expected a 'version' line, got {line[:32]!r}"
        )
    version = line[8:].decode("ascii", "replace").strip()
    if version not in SUPPORTED_VERSIONS:
        raise MeshFormatError(
            f"Unsupported mesh version {version!r}; "
            f"this reader handles {' and '.join(SUPPORTED_VERSIONS)}. "
            "Versions 1-3 and 5+ use different layouts."
        )
    return version


def read_header(f: BinaryIO) -> MeshHeader:
    header = MeshHeader(*_HEADER.unpack(_read_exact(f, _HEADER.size, "header")))
    if header.sizeof_FileMeshHeaderV4 != _HEADER.size:
        raise MeshFormatError(
            f"Header declares its own size as {header.sizeof_FileMeshHeaderV4} "
            f"bytes, expected {_HEADER.size}"
        )
    return header


def read_vertices(f: BinaryIO, count: int) -> list[Vertex]:
    """Read *count* 40-byte vertices.

    Signed tangent bytes are decoded as SNORM: ``c / 127`` clamped at ``-1.0``,
    so both ``-128`` and ``-127`` mean ``-1.0``. The raw bytes are kept on the
    vertex so that mapping stays reversible.
    """
    blob = _read_exact(f, count * VERTEX_SIZE, "vertices")
    vertices = []
    for px, py, pz, nx, ny, nz, u, v, tx, ty, tz, ts, r, g, b, a in _VERTEX.iter_unpack(
        blob
    ):
        vertices.append(
            Vertex(
                position=(px, py, pz),
                normal=(nx, ny, nz),
                uv=(u, v),
                tangent=tuple(max(c / 127.0, -1.0) for c in (tx, ty, tz, ts)),
                color=(r, g, b, a),
                tangent_bytes=(tx, ty, tz, ts),
            )
        )
    return vertices


def read_skinning(f: BinaryIO, count: int) -> list[Skinning]:
    blob = _read_exact(f, count * SKINNING_SIZE, "skinning data")
    return [
        Skinning(subsetIndices=list(rec[:4]), boneWeights=list(rec[4:]))
        for rec in _SKINNING.iter_unpack(blob)
    ]


def read_faces(f: BinaryIO, count: int, num_verts: int) -> list[tuple[int, int, int]]:
    blob = _read_exact(f, count * FACE_SIZE, "faces")
    faces = [tuple(t) for t in _FACE.iter_unpack(blob)]
    bad = [i for i, t in enumerate(faces) if any(v >= num_verts for v in t)]
    if bad:
        raise MeshFormatError(
            f"{len(bad)} face(s) index vertices outside the mesh "
            f"(first at face {bad[0]}: {faces[bad[0]]}, only {num_verts} vertices). "
            "The file is corrupt or is not a version 4 mesh."
        )
    return faces


def read_lod_offsets(f: BinaryIO, count: int) -> list[int]:
    if count == 0:
        return []
    blob = _read_exact(f, count * 4, "LOD offsets")
    return list(struct.unpack(f"<{count}I", blob))


def read_bones(f: BinaryIO, count: int) -> list[Bone]:
    if count == 0:
        return []
    blob = _read_exact(f, count * BONE_SIZE, "bones")
    bones = []
    for rec in _BONE.iter_unpack(blob):
        name_idx, parent, lod_parent, culling = rec[0], rec[1], rec[2], rec[3]
        r = rec[4:13]
        bones.append(
            Bone(
                boneNameIndex=name_idx,
                parentIndex=None if parent == NO_INDEX else parent,
                lodParentIndex=None if lod_parent == NO_INDEX else lod_parent,
                culling=culling,
                rotation=(r[0:3], r[3:6], r[6:9]),
                position=rec[13:16],
            )
        )
    return bones


def read_bone_names(f: BinaryIO, size: int) -> dict[int, str]:
    """Read the NUL-separated name buffer.

    Keys are *byte offsets* into the buffer, which is what ``Bone.boneNameIndex``
    actually holds -- it is an offset, not an ordinal.
    """
    if size == 0:
        return {}
    blob = _read_exact(f, size, "bone name buffer")
    names: dict[int, str] = {}
    offset = 0
    while offset < len(blob):
        end = blob.find(b"\x00", offset)
        if end == -1:
            break
        names[offset] = blob[offset:end].decode("utf-8", "replace")
        offset = end + 1
    return names


def read_subsets(f: BinaryIO, count: int) -> list[Subset]:
    if count == 0:
        return []
    blob = _read_exact(f, count * SUBSET_SIZE, "subsets")
    subsets = []
    for rec in _SUBSET.iter_unpack(blob):
        num_bone_indices = rec[4]
        if num_bone_indices > MAX_SUBSET_BONES:
            raise MeshFormatError(
                f"Subset declares {num_bone_indices} bone indices, "
                f"the format allows at most {MAX_SUBSET_BONES}"
            )
        subsets.append(
            Subset(
                facesBegin=rec[0],
                facesLength=rec[1],
                vertsBegin=rec[2],
                vertsLength=rec[3],
                boneIndices=list(rec[5 : 5 + num_bone_indices]),
            )
        )
    return subsets


def assign_weights(mesh: Mesh) -> int:
    """Resolve per-vertex bone weights into ``Vertex.weights``.

    Each vertex's four ``subsetIndices`` are subset-local slots that must be
    mapped through the owning subset's ``boneIndices`` table to reach a global
    bone. Returns the number of vertices that received at least one weight.
    """
    if not mesh.bones or not mesh.skinning:
        return 0

    weighted = 0
    for subset in mesh.subsets:
        begin = subset.vertsBegin
        end = min(begin + subset.vertsLength, len(mesh.vertices))
        for i in range(begin, end):
            if i >= len(mesh.skinning):
                break
            skin = mesh.skinning[i]
            weights: dict[str, float] = {}
            for slot, raw_weight in zip(
                skin.subsetIndices, skin.boneWeights, strict=True
            ):
                if raw_weight == 0 or slot >= len(subset.boneIndices):
                    continue
                bone_index = subset.boneIndices[slot]
                if bone_index == NO_INDEX or bone_index >= len(mesh.bones):
                    continue
                name = mesh.bones[bone_index].name
                # A bone can occupy two slots of the same vertex; sum rather
                # than overwrite so the weights still total 1.0.
                weights[name] = weights.get(name, 0.0) + raw_weight / 255.0
            if weights:
                mesh.vertices[i].weights = weights
                weighted += 1
    return weighted


def read_mesh(f: BinaryIO) -> Mesh:
    """Read a complete version 4 mesh from a binary stream."""
    version = read_version(f)
    header = read_header(f)

    vertices = read_vertices(f, header.numVerts)
    # The skinning block is present only when the mesh has bones.
    skinning = read_skinning(f, header.numVerts) if header.numBones else []
    faces = read_faces(f, header.numFaces, header.numVerts)
    lod_offsets = read_lod_offsets(f, header.numLodOffsets)
    bones = read_bones(f, header.numBones)
    bone_names = read_bone_names(f, header.sizeof_boneNames)
    subsets = read_subsets(f, header.numSubsets)

    for bone in bones:
        bone.name = bone_names.get(bone.boneNameIndex, f"<unnamed@{bone.boneNameIndex}>")

    mesh = Mesh(
        version=version,
        header=header,
        vertices=vertices,
        skinning=skinning,
        faces=faces,
        lodOffsets=lod_offsets,
        bones=bones,
        boneNames=bone_names,
        subsets=subsets,
    )
    assign_weights(mesh)
    return mesh


def read_mesh_file(path: str) -> Mesh:
    with open(path, "rb") as f:
        return read_mesh(f)
