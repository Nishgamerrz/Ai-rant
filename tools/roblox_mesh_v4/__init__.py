"""Minimal vendored reader for Roblox FileMesh v4, based on MIT-licensed RBXMesh."""
from .reader import MeshFormatError, read_mesh, read_mesh_file

__all__ = ["MeshFormatError", "read_mesh", "read_mesh_file"]
