"""In-memory representation of a Roblox ``FileMesh`` version 4.

The field names mirror the names used in the binary format so that
:mod:`roblox_mesh.reader` reads like the layout table in ``docs/MESH_FORMAT.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

Vec2 = tuple[float, float]
Vec3 = tuple[float, float, float]
Vec4 = tuple[float, float, float, float]

#: Bytes per vertex record. Version 4 always stores RGBA colour, so unlike
#: version 2 (which may be 36 or 40) this is fixed. Verified against 708 real
#: v4.01 files -- see ``docs/MESH_FORMAT.md``.
VERTEX_SIZE = 40
#: Bytes per skinning record (4 subset-local bone slots + 4 weights).
SKINNING_SIZE = 8
#: Bytes per face record (three uint32 vertex indices).
FACE_SIZE = 12
#: Bytes per bone record.
BONE_SIZE = 60
#: Bytes per subset record. ``numBoneIndices`` is a uint32, not a uint16 --
#: getting this wrong is the single most destructive mistake in a v4 reader.
SUBSET_SIZE = 72
#: Maximum bone slots a subset can reference.
MAX_SUBSET_BONES = 26
#: Sentinel used for "no parent" / "unused bone slot".
NO_INDEX = 0xFFFF


@dataclass(slots=True)
class MeshHeader:
    """The 24-byte ``FileMeshHeaderV4`` that follows the version line."""

    sizeof_FileMeshHeaderV4: int
    lodType: int
    numVerts: int
    numFaces: int
    numLodOffsets: int
    numBones: int
    sizeof_boneNames: int
    numSubsets: int
    numHighQualityLODs: int
    unused: int


@dataclass(slots=True)
class Vertex:
    position: Vec3
    normal: Vec3
    uv: Vec2
    #: Tangent as SNORM floats in [-1, 1].
    tangent: Vec4
    color: Vec4 | None = None
    #: Bone name -> normalised weight, filled in by :func:`assign_weights`.
    weights: dict[str, float] = field(default_factory=dict)
    #: The tangent's four raw signed bytes, kept so a mesh can be rewritten
    #: byte-for-byte. SNORM decoding maps both -128 and -127 to -1.0, so the
    #: float form alone cannot round-trip -- and real Roblox meshes do contain
    #: -128 tangent bytes.
    tangent_bytes: tuple[int, int, int, int] | None = None


@dataclass(slots=True)
class Skinning:
    """Per-vertex bone binding.

    ``subsetIndices`` are *subset-local*: each one indexes the owning subset's
    ``boneIndices`` table, not the global bone list.
    """

    subsetIndices: list[int]
    boneWeights: list[int]


@dataclass(slots=True)
class Bone:
    boneNameIndex: int
    parentIndex: int | None
    lodParentIndex: int | None
    culling: float
    #: Row-major 3x3 rotation, model space.
    rotation: tuple[Vec3, Vec3, Vec3]
    #: Model-space position. Absolute, *not* relative to the parent bone --
    #: verified empirically, see ``docs/MESH_FORMAT.md``.
    position: Vec3
    name: str = ""


@dataclass(slots=True)
class Subset:
    facesBegin: int
    facesLength: int
    vertsBegin: int
    vertsLength: int
    boneIndices: list[int]


@dataclass(slots=True)
class Mesh:
    version: str
    header: MeshHeader
    vertices: list[Vertex]
    skinning: list[Skinning]
    faces: list[tuple[int, int, int]]
    lodOffsets: list[int]
    bones: list[Bone]
    boneNames: dict[int, str]
    subsets: list[Subset]

    @property
    def is_skinned(self) -> bool:
        return bool(self.bones)

    def lod_faces(self, level: int = 0) -> list[tuple[int, int, int]]:
        """Faces belonging to one LOD level; level 0 is the highest detail.

        ``lodOffsets`` delimits ranges in the face list, so level *n* is
        ``faces[lodOffsets[n]:lodOffsets[n + 1]]``. Meshes without LOD data
        return every face.
        """
        if len(self.lodOffsets) < 2:
            return list(self.faces)
        if not 0 <= level < len(self.lodOffsets) - 1:
            raise IndexError(
                f"LOD level {level} out of range (mesh has {len(self.lodOffsets) - 1})"
            )
        return self.faces[self.lodOffsets[level] : self.lodOffsets[level + 1]]
