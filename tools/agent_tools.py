#!/usr/bin/env python3
"""Shared, bounded tools for the local NishAgent and Gemini/Groq sub-agent.

File operations are rooted at the caller's workspace. Image understanding and
image generation use the configured Gemini API; image manipulation, asset
reference search, video inspection and ZIP packaging use local tools. A model
must author each JSON ``tool_calls`` entry itself before the runner executes it.
"""
from __future__ import annotations

import base64
import io
import ipaddress
import json
import math
import os
import shutil
import socket
import struct
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

MAX_TEXT_BYTES = 24_000
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_EDGE = 1536
MAX_ZIP_BYTES = 100 * 1024 * 1024
MAX_MESH_BYTES = 25 * 1024 * 1024
GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# Twenty-nine callable tools, shared by the local agent and the sub-agent.
TOOL_NAMES = (
    "search_web", "search_assets", "find_model_reference", "search_roblox_meshes",
    "fetch_mesh_reference", "inspect_mesh_dimensions", "plan_mesh_placement",
    "create_file", "read_file", "list_files", "search_files", "edit_file",
    "run_cmd", "fetch_image", "inspect_image", "resize_image", "crop_image",
    "convert_image", "compare_images", "make_contact_sheet", "generate_image",
    "edit_image", "inspect_video", "package_files", "analyze_short_script",
    "plan_short_lighting", "audit_roblox_map", "audit_short_captions",
    "inspect_roblox_short",
)

TOOL_GUIDE = """\
AVAILABLE TOOLS (you must write every requested call yourself in a JSON
`tool_calls` array; the runner executes only calls you actually authored):
- search_web(query): current web results for facts.
- search_assets(query): search for visual/model assets and references; use it for
  props such as a light bulb, bed, lamp, or house. Returns source links, not fake IDs.
- find_model_reference(name, kind): find Roblox/catalog/model references for a named prop.
- search_roblox_meshes(query, limit=8): search Roblox's public Creator Store API for Model
  and MeshPart listings, then fall back to web references if that API is unavailable. It
  returns actual IDs only when Roblox supplies them; listings are not licensing guarantees.
- fetch_mesh_reference(url, path): download one direct public HTTPS OBJ/STL/ASCII-PLY/glTF/GLB
  file into the workspace with SSRF, redirect, file-type and 25 MiB checks. Creator Store
  listing pages are not mesh files; glTF buffers must be embedded in the file.
- inspect_mesh_dimensions(path, studs_per_unit=null): measure supported local mesh bounds
  and report its coordinate-space size; units are not called studs unless you specify the
  scale. Supports OBJ, STL, ASCII PLY, glTF and GLB accessors with bounds.
- plan_mesh_placement(name, dimensions, position, room_size, studs_per_unit, model=""):
  requires an explicit conversion from source units to studs, then returns a grid-aligned,
  room-fitted map anchor plus its actual fitted dimensions for the plan;
  optionally choose a supported generated map model such as "house" or "tree".
  For a measured reference, call search_roblox_meshes, then fetch_mesh_reference,
  inspect_mesh_dimensions and plan_mesh_placement; use the returned anchor's exact size
  and position. Search snippets do not establish dimensions or Roblox-stud units. This is
  a blueprint/reference placement; the short builder renders editable Part/model anchors,
  not an imported external mesh. For an assigned model anchor, always search its exact
  name with search_roblox_meshes and return real IDs/URLs from the tool result; never invent
  an ID. If a permitted supported mesh file can actually be downloaded, call
  inspect_mesh_dimensions. For every successful measurement, call plan_mesh_placement
  with that exact dimensions_source_units value and an explicit studs_per_unit scale, then
  use the returned anchor size and position. If no supported file is available, report that
  dimensions are unavailable; do not infer dimensions from a Creator Store listing.
- create_file(path, content), read_file(path), list_files(path), search_files(query, path).
- edit_file(path, old_text, new_text): succeeds only when old_text occurs once.
- run_cmd(cmd): short sandbox command; credentials are stripped from its environment.
- fetch_image(url, path): download a supplied HTTPS image into the workspace.
- inspect_image(path, question): ask Gemini Vision to inspect the actual pixels and
  return a concise, actionable visual description. Use this for supplied face photos.
- resize_image(path, width, height, output), crop_image(path, x, y, width, height, output),
  convert_image(path, format, output), compare_images(path_a, path_b),
  make_contact_sheet(paths, output).
- generate_image(prompt, output), edit_image(path, prompt, output): use the configured
  Gemini image model; edit_image passes the original pixels as the visual reference.
- inspect_video(path): report video/audio streams, dimensions, duration, and codecs.
- package_files(path, output): create a ZIP from the selected workspace folder.
Roblox-short production tools (use these for the story/map/captions/render):
- analyze_short_script(text=... or path=..., duration=150): estimate read time and target
  fill, identify hook/turn/payoff lines, and flag long sentences; path wins if both are given.
- plan_short_lighting(text=... or path=..., duration=150): suggest a global hour plus
  ordered dawn/day/sunset/night story cues and approximate overrides. Treat times as hints;
  align actual camera-shot overrides to story beats.
- audit_roblox_map(path=..., duration=150, cast=[]): run the production normalizer and
  report world Parts, camera rhythm, face shots, invalid camera/hour fields, and overrides.
- audit_short_captions(text=... or path=..., duration=0, max_words=1): check SRT order,
  overlaps, video bounds, gaps, and one-word reference-style caption readability.
- inspect_roblox_short(path=..., report='', frames_dir='', samples=8, timeout=180): run
  the shipped MP4 visual/technical audit across decoded frames (lighting, colour, black
  slabs, aspect, codecs, duration). All supplied and returned artifact paths are relative.
Paths are relative to your workspace; absolute paths and `..` are refused. Images are
bounded and decoded before use. A reference URL must be public HTTPS; no localhost,
private-network, or credential-bearing URL is fetched. Prefer `inspect_image` before
choosing face style, and make a clear final note if no image was supplied.
"""


def safe_path(root: Path, value: str, *, allow_root: bool = False) -> Path:
    root = Path(root).resolve()
    raw = Path(str(value or "").strip())
    if raw.is_absolute() or ".." in raw.parts:
        raise ValueError("path must be workspace-relative; absolute paths and '..' are refused")
    target = (root / raw).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("path escapes the workspace") from exc
    if target == root and not allow_root:
        raise ValueError("a file path is required")
    return target


def _bounded_text(path: Path, limit: int = MAX_TEXT_BYTES) -> str:
    raw = path.read_bytes()
    if len(raw) > limit:
        raw = raw[:limit]
        suffix = "\n... truncated at the tool output limit"
    else:
        suffix = ""
    return raw.decode("utf-8", "replace") + suffix


def _search(query: str) -> list[dict]:
    from ai_web_search import search
    return search(str(query or "").strip()[:240])[:6]


def search_web(query: str, **_: Any) -> dict:
    query = str(query or "").strip()
    if not query:
        return {"ok": False, "error": "query is required"}
    return {"ok": True, "query": query, "results": _search(query)}


def search_assets(query: str, **_: Any) -> dict:
    query = str(query or "").strip()
    if not query:
        return {"ok": False, "error": "query is required"}
    terms = [
        f"{query} 3D model reference asset",
        f"Roblox Studio {query} model asset reference",
    ]
    results: list[dict] = []
    seen: set[str] = set()
    for term in terms:
        for item in _search(term):
            url = str(item.get("url") or "")
            if url and url not in seen:
                seen.add(url)
                results.append(item)
    return {"ok": True, "query": query, "results": results[:8],
            "note": "Use these as visual references; results are not verified asset IDs."}


def find_model_reference(name: str, kind: str = "Roblox model", **_: Any) -> dict:
    name = str(name or "").strip()
    kind = str(kind or "Roblox model").strip()
    if not name:
        return {"ok": False, "error": "name is required"}
    result = search_assets(f"{name} {kind}")
    result["name"] = name
    result["kind"] = kind
    result["note"] = "Reference search only: verify licensing and the source before using an asset."
    return result


def search_roblox_meshes(query: str, limit: int = 8, **_: Any) -> dict:
    """Search the official public Creator Store first, then web references."""
    query = " ".join(str(query or "").split()).strip()[:240]
    if not query:
        return {"ok": False, "error": "query is required"}
    limit = max(1, min(12, int(limit)))
    results: list[dict] = []
    seen: set[str] = set()
    categories = ("Model", "MeshPart")
    store_errors: list[str] = []
    store_succeeded = False
    for category in categories:
        try:
            payload = _creator_store_search(query, category)
            store_succeeded = True
        except Exception as exc:  # A store outage must not suppress the public web fallback.
            store_errors.append(f"{category}: {type(exc).__name__}")
            continue
        rows = payload.get("creatorStoreAssets") or payload.get("data") or []
        for entry in rows if isinstance(rows, list) else []:
            if not isinstance(entry, dict):
                continue
            asset = entry.get("asset") if isinstance(entry.get("asset"), dict) else entry
            asset_id = str(asset.get("id") or asset.get("assetId") or "").strip()
            if not asset_id.isdigit() or asset_id in seen:
                continue
            seen.add(asset_id)
            creator = entry.get("creator") if isinstance(entry.get("creator"), dict) else {}
            results.append({
                "title": str(asset.get("name") or entry.get("name") or "Roblox asset")[:160],
                "asset_id": asset_id,
                "asset_type": category,
                "creator": str(creator.get("name") or creator.get("displayName") or "")[:100],
                "url": f"https://create.roblox.com/store/asset/{asset_id}",
                "snippet": str(asset.get("description") or entry.get("description") or "")[:420],
                "source": "Roblox Creator Store API",
            })
            if len(results) >= limit:
                break
        if len(results) >= limit:
            break

    source = "Roblox Creator Store API"
    if not results:
        # Public text search is a fallback for documentation and other source
        # links; its pages are not presented as verified Roblox assets.
        searches = (
            f"site:create.roblox.com/store/asset {query} model mesh",
            f"Roblox Studio Toolbox {query} mesh model",
            f"Roblox Creator Store {query} 3D model dimensions",
        )
        for term in searches:
            for item in _search(term):
                url = str(item.get("url") or "").strip()
                if not url.startswith("https://") or url in seen:
                    continue
                seen.add(url)
                results.append({
                    "title": str(item.get("title") or "")[:160],
                    "url": url[:500],
                    "snippet": str(item.get("snippet") or "")[:420],
                    "source": "public web reference",
                })
                if len(results) >= limit:
                    break
            if len(results) >= limit:
                break
        source = "public web reference search"

    return {
        "ok": True,
        "query": query,
        "source": source,
        "creator_store_api_status": "available" if store_succeeded else "unavailable",
        "creator_store_errors": store_errors[:2],
        "creator_store_search_url": "https://create.roblox.com/store/asset?" + urllib.parse.urlencode({"query": query}),
        "results": results,
        "note": ("Search results are references only. The Creator Store search does not supply "
                 "verified mesh dimensions or Roblox-stud units, and discovery does not verify "
                 "permissions or licensing. Download a permitted, supported mesh file and inspect "
                 "its bounds before planning placement."),
    }


def create_file(root: Path, path: str, content: str = "", **_: Any) -> dict:
    target = safe_path(root, path)
    text = str(content or "")
    if len(text.encode("utf-8")) > MAX_TEXT_BYTES * 4:
        return {"ok": False, "error": "content exceeds the 96 KB tool limit"}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return {"ok": True, "path": target.relative_to(Path(root).resolve()).as_posix(),
            "bytes": len(text.encode("utf-8"))}


def read_file(root: Path, path: str, **_: Any) -> dict:
    target = safe_path(root, path)
    if not target.is_file():
        return {"ok": False, "error": f"file not found: {path}"}
    if target.stat().st_size > MAX_TEXT_BYTES * 8:
        return {"ok": False, "error": "file is too large for read_file; use search_files or run_cmd"}
    return {"ok": True, "path": target.relative_to(Path(root).resolve()).as_posix(),
            "content": _bounded_text(target)}


def list_files(root: Path, path: str = ".", **_: Any) -> dict:
    target = safe_path(root, path, allow_root=True)
    if not target.exists():
        return {"ok": False, "error": f"path not found: {path}"}
    if target.is_file():
        return {"ok": True, "files": [target.relative_to(Path(root).resolve()).as_posix()]}
    ignored = {".git", "node_modules", ".venv", "__pycache__", ".next"}
    found: list[str] = []
    for child in sorted(target.rglob("*")):
        relative = child.relative_to(Path(root).resolve())
        if any(part in ignored for part in relative.parts):
            continue
        found.append(("dir/" if child.is_dir() else "") + relative.as_posix())
        if len(found) >= 120:
            found.append("... additional files omitted")
            break
    return {"ok": True, "path": str(path), "files": found}


def search_files(root: Path, query: str, path: str = ".", **_: Any) -> dict:
    query = str(query or "").strip()
    if not query:
        return {"ok": False, "error": "query is required"}
    base = safe_path(root, path, allow_root=True)
    if not base.exists():
        return {"ok": False, "error": f"path not found: {path}"}
    needles = query.casefold().split()
    ignored = {".git", "node_modules", ".venv", "__pycache__", ".next"}
    matches: list[dict] = []
    files = [base] if base.is_file() else base.rglob("*")
    for file in files:
        if not file.is_file() or any(part in ignored for part in file.relative_to(Path(root).resolve()).parts):
            continue
        try:
            if file.stat().st_size > 1_000_000:
                continue
            text = file.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            low = line.casefold()
            if all(needle in low for needle in needles):
                matches.append({"path": file.relative_to(Path(root).resolve()).as_posix(),
                                "line": number, "text": line[:300]})
                if len(matches) >= 30:
                    return {"ok": True, "matches": matches, "truncated": True}
    return {"ok": True, "matches": matches, "truncated": False}


def edit_file(root: Path, path: str, old_text: str, new_text: str, **_: Any) -> dict:
    target = safe_path(root, path)
    if not target.is_file():
        return {"ok": False, "error": f"file not found: {path}"}
    original = target.read_text(encoding="utf-8")
    old_text = str(old_text or "")
    if not old_text:
        return {"ok": False, "error": "old_text must not be empty"}
    count = original.count(old_text)
    if count != 1:
        return {"ok": False, "error": f"old_text must match exactly once; found {count}"}
    updated = original.replace(old_text, str(new_text or ""), 1)
    if len(updated.encode("utf-8")) > 1_000_000:
        return {"ok": False, "error": "edited file exceeds the 1 MB tool limit"}
    target.write_text(updated, encoding="utf-8")
    return {"ok": True, "path": target.relative_to(Path(root).resolve()).as_posix(),
            "bytes": len(updated.encode("utf-8"))}


def run_cmd(root: Path, cmd: str, timeout: int = 30, **_: Any) -> dict:
    cmd = str(cmd or "").strip()
    if not cmd:
        return {"ok": False, "error": "cmd is required"}
    blocked = ("rm -rf /", "mkfs", ":(){:|:&};:", "shutdown", "reboot")
    if any(item in cmd for item in blocked):
        return {"ok": False, "error": "blocked command"}
    # Commands run in a clean, workspace-local environment. In particular, no
    # GitHub/Gemini/Groq credentials are inherited by model-authored shell code.
    source_env = os.environ
    safe_env = {key: value for key, value in source_env.items()
                if not any(secret in key.upper() for secret in
                           ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "GITHUB_",
                            "GEMINI", "GROQ", "OPENAI", "VERCEL"))}
    safe_env["HOME"] = str(Path(root).resolve() / ".tool-home")
    safe_env["TMPDIR"] = str(Path(root).resolve() / ".tool-tmp")
    Path(safe_env["HOME"]).mkdir(parents=True, exist_ok=True)
    Path(safe_env["TMPDIR"]).mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(cmd, shell=True, cwd=str(Path(root).resolve()),
                                capture_output=True, text=True,
                                timeout=max(1, min(60, int(timeout))), env=safe_env)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "command timed out", "cmd": cmd}
    except OSError as exc:
        return {"ok": False, "error": str(exc), "cmd": cmd}
    output = ((result.stdout or "") + (result.stderr or ""))[:MAX_TEXT_BYTES]
    return {"ok": result.returncode == 0, "code": result.returncode,
            "output": output, "cmd": cmd}


def _public_https(url: str) -> urllib.parse.SplitResult:
    parsed = urllib.parse.urlsplit(str(url or "").strip())
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("only public HTTPS URLs without embedded credentials are accepted")
    if parsed.port not in (None, 443):
        raise ValueError("non-standard HTTPS ports are refused")
    host = parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "metadata.google.internal", "metadata.google"}:
        raise ValueError("private and metadata hosts are refused")
    try:
        direct = ipaddress.ip_address(host)
        if not direct.is_global:
            raise ValueError("private-network URLs are refused")
    except ValueError as exc:
        if "private-network" in str(exc):
            raise
        try:
            resolved = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        except OSError:
            resolved = []
        if resolved and any(not ipaddress.ip_address(row[4][0]).is_global for row in resolved):
            raise ValueError("URL resolves to a private or reserved address")
    return parsed


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: N802
        return None


def _download(url: str, limit: int = MAX_IMAGE_BYTES) -> tuple[bytes, str, str]:
    opener = urllib.request.build_opener(_NoRedirect)
    current = url
    for _ in range(6):
        _public_https(current)
        request = urllib.request.Request(current, headers={"User-Agent": "Ai-rant-agent/1.0"})
        try:
            response = opener.open(request, timeout=20)
        except urllib.error.HTTPError as exc:
            if exc.code in (301, 302, 303, 307, 308):
                location = exc.headers.get("Location") or ""
                current = urllib.parse.urljoin(current, location)
                continue
            raise ValueError(f"image download returned HTTP {exc.code}") from exc
        with response:
            content_type = str(response.headers.get("Content-Type") or "").split(";", 1)[0].lower()
            length = int(response.headers.get("Content-Length") or 0)
            if length > limit:
                raise ValueError("image exceeds the 8 MiB download limit")
            data = response.read(limit + 1)
            if len(data) > limit:
                raise ValueError("image exceeds the 8 MiB download limit")
            if not content_type.startswith("image/"):
                raise ValueError(f"URL did not return an image (Content-Type: {content_type or 'unknown'})")
            return data, content_type, current
    raise ValueError("too many redirects while downloading image")


def _download_mesh(url: str, limit: int = MAX_MESH_BYTES) -> tuple[bytes, str, str]:
    """Download one bounded mesh file, revalidating every public HTTPS redirect."""
    opener = urllib.request.build_opener(_NoRedirect)
    current = str(url or "").strip()
    for _ in range(6):
        _public_https(current)
        request = urllib.request.Request(current, headers={"User-Agent": "Ai-rant-agent/1.0"})
        try:
            response = opener.open(request, timeout=25)
        except urllib.error.HTTPError as exc:
            if exc.code in (301, 302, 303, 307, 308):
                current = urllib.parse.urljoin(current, exc.headers.get("Location") or "")
                continue
            raise ValueError(f"mesh download returned HTTP {exc.code}") from exc
        with response:
            length = int(response.headers.get("Content-Length") or 0)
            if length > limit:
                raise ValueError("mesh exceeds the 25 MiB download limit")
            data = response.read(limit + 1)
            if len(data) > limit:
                raise ValueError("mesh exceeds the 25 MiB download limit")
            content_type = str(response.headers.get("Content-Type") or "").split(";", 1)[0].lower()
            return data, content_type, current
    raise ValueError("too many redirects while downloading mesh")


def _creator_store_search(query: str, category: str) -> dict:
    """Use Roblox's public Creator Store Toolbox search API without credentials.

    The GET query parameters and creatorStoreAssets response shape follow the
    official Roblox Creator Hub OpenAPI document:
    https://github.com/Roblox/creator-docs/blob/main/content/en-us/reference/cloud/toolbox-service/v1.json
    """
    url = "https://apis.roblox.com/toolbox-service/v2/assets:search?" + urllib.parse.urlencode({
        "searchCategoryType": category,
        "query": query[:240],
    })
    opener = urllib.request.build_opener(_NoRedirect)
    current = url
    for _ in range(6):
        _public_https(current)
        request = urllib.request.Request(current, headers={
            "Accept": "application/json",
            "User-Agent": "Ai-rant-agent/1.0",
        })
        try:
            response = opener.open(request, timeout=15)
        except urllib.error.HTTPError as exc:
            if exc.code in (301, 302, 303, 307, 308):
                current = urllib.parse.urljoin(current, exc.headers.get("Location") or "")
                continue
            raise ValueError(f"Creator Store search returned HTTP {exc.code}") from exc
        with response:
            length = int(response.headers.get("Content-Length") or 0)
            if length > 2 * 1024 * 1024:
                raise ValueError("Creator Store search response exceeds the 2 MiB limit")
            raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise ValueError("Creator Store search response exceeds the 2 MiB limit")
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise ValueError("Creator Store search returned invalid JSON") from exc
            if not isinstance(payload, dict):
                raise ValueError("Creator Store search response must be an object")
            return payload
    raise ValueError("too many redirects while searching Creator Store")


def _mesh_points_from_obj(raw: bytes) -> list[tuple[float, float, float]]:
    points = []
    for line in raw.decode("utf-8", "replace").splitlines():
        parts = line.strip().split()
        if len(parts) < 4 or parts[0] != "v":
            continue
        try:
            point = tuple(float(value) for value in parts[1:4])
        except ValueError:
            continue
        if all(math.isfinite(value) for value in point):
            points.append(point)
            if len(points) >= 1_000_000:
                break
    return points


def _mesh_points_from_stl(raw: bytes) -> list[tuple[float, float, float]]:
    if len(raw) >= 84:
        count = struct.unpack_from("<I", raw, 80)[0]
        if count and 84 + count * 50 == len(raw):
            points = []
            for triangle in range(count):
                base = 84 + triangle * 50
                for offset in (12, 24, 36):
                    point = struct.unpack_from("<3f", raw, base + offset)
                    if all(math.isfinite(value) for value in point):
                        points.append(point)
            return points
    text = raw.decode("utf-8", "replace")
    points = []
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) < 4 or parts[0].lower() != "vertex":
            continue
        try:
            point = tuple(float(value) for value in parts[1:4])
        except ValueError:
            continue
        if all(math.isfinite(value) for value in point):
            points.append(point)
            if len(points) >= 1_000_000:
                break
    return points


def _gltf_document(raw: bytes, suffix: str) -> dict:
    if suffix == ".gltf":
        document = json.loads(raw.decode("utf-8", "replace"))
        if (not isinstance(document, dict)
                or str((document.get("asset") or {}).get("version") or "") != "2.0"):
            raise ValueError("glTF must be a version 2.0 JSON object")
        return document
    if len(raw) < 20 or raw[:4] != b"glTF":
        raise ValueError("GLB header is invalid")
    version, declared_length = struct.unpack_from("<II", raw, 4)
    if version != 2 or declared_length > len(raw):
        raise ValueError("only valid glTF 2.0 binary files are supported")
    cursor = 12
    while cursor + 8 <= min(declared_length, len(raw)):
        length, kind = struct.unpack_from("<II", raw, cursor)
        cursor += 8
        chunk = raw[cursor:cursor + length]
        cursor += length
        if len(chunk) != length:
            break
        if kind == 0x4E4F534A:
            document = json.loads(chunk.rstrip(b"\x00 \t\r\n").decode("utf-8", "replace"))
            if (isinstance(document, dict)
                    and str((document.get("asset") or {}).get("version") or "") == "2.0"):
                return document
    raise ValueError("GLB file has no valid JSON metadata chunk")


def _mesh_bounds_from_gltf(document: dict) -> tuple[list[float], list[float]] | None:
    accessors = document.get("accessors") or []
    lows: list[float] = []
    highs: list[float] = []
    for mesh in document.get("meshes") or []:
        for primitive in mesh.get("primitives") or []:
            attributes = primitive.get("attributes") or {}
            if "POSITION" not in attributes:
                continue
            try:
                accessor = accessors[int(attributes["POSITION"])]
                low, high = accessor["min"], accessor["max"]
                if len(low) < 3 or len(high) < 3:
                    continue
                lows.append([float(value) for value in low[:3]])
                highs.append([float(value) for value in high[:3]])
            except (IndexError, KeyError, TypeError, ValueError):
                continue
    if not lows:
        return None
    low = [min(row[axis] for row in lows) for axis in range(3)]
    high = [max(row[axis] for row in highs) for axis in range(3)]
    if (not all(math.isfinite(value) for value in [*low, *high])
            or any(low[axis] > high[axis] for axis in range(3))):
        return None
    return low, high


def _mesh_points_from_ply(raw: bytes) -> list[tuple[float, float, float]]:
    header_end = raw.find(b"end_header")
    if header_end < 0:
        return []
    header = raw[:header_end].decode("ascii", "replace").splitlines()
    if not any(line.strip() == "format ascii 1.0" for line in header):
        return []
    vertex_count = 0
    in_vertices = False
    names = []
    for line in header:
        parts = line.strip().split()
        if parts[:2] == ["element", "vertex"] and len(parts) == 3:
            vertex_count = min(1_000_000, int(parts[2]))
            in_vertices = True
        elif parts and parts[0] == "element":
            in_vertices = False
        elif in_vertices and parts[:1] == ["property"] and len(parts) >= 3:
            names.append(parts[-1])
    if vertex_count <= 0:
        return []
    try:
        indices = [names.index(axis) for axis in ("x", "y", "z")]
    except ValueError:
        return []
    body = raw[header_end + len(b"end_header"):].lstrip(b"\r\n")
    points = []
    for line in body.decode("ascii", "replace").splitlines()[:vertex_count]:
        parts = line.split()
        try:
            point = tuple(float(parts[index]) for index in indices)
        except (ValueError, IndexError):
            continue
        if all(math.isfinite(value) for value in point):
            points.append(point)
    return points


def fetch_mesh_reference(root: Path, url: str, path: str = "references/mesh.obj", **_: Any) -> dict:
    """Save a permitted, bounded public mesh reference for inspection."""
    target = safe_path(root, path)
    suffix = target.suffix.lower()
    if suffix not in {".obj", ".stl", ".ply", ".gltf", ".glb"}:
        return {"ok": False, "error": "mesh path must end in .obj, .stl, .ply, .gltf, or .glb"}
    data, content_type, final_url = _download_mesh(url)
    try:
        if suffix == ".obj":
            valid = bool(_mesh_points_from_obj(data))
        elif suffix == ".stl":
            valid = bool(_mesh_points_from_stl(data))
        elif suffix == ".ply":
            valid = bool(_mesh_points_from_ply(data))
        else:
            document = _gltf_document(data, suffix)
            bounds = _mesh_bounds_from_gltf(document)
            buffers = document.get("buffers") or []
            has_external_buffer = (suffix == ".gltf" and any(
                isinstance(buffer, dict) and buffer.get("uri")
                and not str(buffer.get("uri")).startswith("data:")
                for buffer in buffers))
            valid = bounds is not None and not has_external_buffer
    except (ValueError, json.JSONDecodeError, struct.error):
        valid = False
    if not valid:
        return {"ok": False, "error": f"downloaded file is not a readable {suffix[1:]} mesh"}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return {"ok": True, "path": target.relative_to(Path(root).resolve()).as_posix(),
            "format": suffix[1:], "bytes": len(data), "content_type": content_type,
            "source": final_url}


def inspect_mesh_dimensions(root: Path, path: str,
                            studs_per_unit: float | None = None, **_: Any) -> dict:
    """Measure an OBJ/STL/ASCII-PLY/glTF/GLB axis-aligned mesh bounding box."""
    target = safe_path(root, path)
    if not target.is_file():
        return {"ok": False, "error": f"mesh not found: {path}"}
    if target.stat().st_size > MAX_MESH_BYTES:
        return {"ok": False, "error": "mesh exceeds the 25 MiB inspection limit"}
    suffix = target.suffix.lower()
    raw = target.read_bytes()
    if suffix == ".obj":
        points = _mesh_points_from_obj(raw)
    elif suffix == ".stl":
        points = _mesh_points_from_stl(raw)
    elif suffix == ".ply":
        points = _mesh_points_from_ply(raw)
    elif suffix in {".gltf", ".glb"}:
        try:
            bounds = _mesh_bounds_from_gltf(_gltf_document(raw, suffix))
        except (ValueError, json.JSONDecodeError, struct.error):
            bounds = None
        if bounds is None:
            return {"ok": False, "error": "glTF has no usable POSITION accessor min/max bounds"}
        low, high = bounds
        points = []
    else:
        return {"ok": False, "error": "supported mesh formats: OBJ, STL, ASCII PLY, glTF, and GLB"}
    if suffix not in {".gltf", ".glb"}:
        if not points:
            return {"ok": False, "error": f"{suffix[1:].upper()} contains no readable vertices"}
        low = [min(point[axis] for point in points) for axis in range(3)]
        high = [max(point[axis] for point in points) for axis in range(3)]
    dimensions = [round(high[axis] - low[axis], 4) for axis in range(3)]
    result = {
        "ok": True,
        "path": target.relative_to(Path(root).resolve()).as_posix(),
        "format": suffix[1:],
        "vertices_measured": len(points) if points else None,
        "bounds": {"min": [round(value, 4) for value in low],
                   "max": [round(value, 4) for value in high]},
        "dimensions_source_units": dimensions,
        "units": "source mesh coordinate units; not assumed to be Roblox studs",
        "bounds_frame": ("glTF POSITION accessor coordinates; node transforms are not applied"
                         if suffix in {".gltf", ".glb"} else "file vertex coordinates"),
    }
    if studs_per_unit is not None:
        if isinstance(studs_per_unit, bool):
            return {"ok": False, "error": "studs_per_unit must be a number"}
        try:
            scale = float(studs_per_unit)
        except (TypeError, ValueError):
            return {"ok": False, "error": "studs_per_unit must be a number"}
        if not math.isfinite(scale) or not 0 < scale <= 1000:
            return {"ok": False, "error": "studs_per_unit must be greater than 0 and at most 1000"}
        result["studs_per_unit"] = scale
        result["estimated_dimensions_studs"] = [round(value * scale, 3) for value in dimensions]
    return result


def plan_mesh_placement(name: str, dimensions: list, position: list | None = None,
                        room_size: list | None = None, studs_per_unit: float | None = None,
                        margin: float = 1.0, color: list | None = None,
                        model: str = "", **_: Any) -> dict:
    """Fit measured mesh bounds into a room and return a normalized map anchor."""
    def vector(value, field, default):
        values = default if value is None else value
        if (not isinstance(values, (list, tuple)) or len(values) != 3
                or any(isinstance(item, bool) or not isinstance(item, (int, float))
                       or not math.isfinite(float(item)) for item in values)):
            raise ValueError(f"{field} must contain three finite numbers")
        return [float(item) for item in values]

    clean_name = " ".join(str(name or "").split())[:40]
    if not clean_name:
        return {"ok": False, "error": "name is required"}
    if studs_per_unit is None:
        return {"ok": False, "error": "studs_per_unit is required; mesh coordinate units are not assumed to be Roblox studs"}
    try:
        dims = vector(dimensions, "dimensions", [])
        room = vector(room_size, "room_size", [34, 11, 34])
        target_position = vector(position, "position", [0, 0, 0])
        if isinstance(studs_per_unit, bool):
            raise ValueError("studs_per_unit must be a number")
        scale_units = float(studs_per_unit)
        if isinstance(margin, bool):
            raise ValueError("margin must be a number")
        margin = float(margin)
    except (TypeError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}
    if any(value <= 0 or value > 1_000_000 for value in dims):
        return {"ok": False, "error": "dimensions must be positive and at most 1,000,000 source units"}
    if any(value <= 0 for value in room):
        return {"ok": False, "error": "room dimensions must be positive"}
    if room[0] > 500 or room[2] > 500 or room[1] > 250:
        return {"ok": False, "error": "room dimensions exceed the 500 x 250 x 500 map-planning limits"}
    if not math.isfinite(scale_units) or not 0 < scale_units <= 1000:
        return {"ok": False, "error": "studs_per_unit must be greater than 0 and at most 1000"}
    if not math.isfinite(margin) or margin < 0 or margin >= min(room[0] / 2, room[2] / 2, room[1]):
        return {"ok": False, "error": "margin must leave usable room on every side"}

    studs = [value * scale_units for value in dims]
    if any(not math.isfinite(value) or value <= 0 for value in studs):
        return {"ok": False, "error": "scaled mesh dimensions are outside the supported numeric range"}
    available = [room[0] - 2 * margin, room[1] - margin, room[2] - 2 * margin]
    if min(available) < 0.5:
        return {"ok": False, "error": "room has less than 0.5 studs of usable space after margins"}
    factor = min(1.0, *(available[index] / studs[index] for index in range(3)),
                 *(64.0 / value for value in studs))
    # Round down to the builder's half-stud grid so the fitted dimensions never
    # grow past either the room clearance or the map builder's 64-stud limit.
    size = [max(0.5, math.floor(value * factor * 2 + 1e-9) / 2) for value in studs]

    def snap_within(value: float, low: float, high: float) -> float:
        first = math.ceil(low * 2 - 1e-9) / 2
        last = math.floor(high * 2 + 1e-9) / 2
        if first > last:
            raise ValueError("no half-stud grid position fits the requested room")
        snapped = round(value * 2) / 2
        return max(first, min(last, snapped))

    try:
        center = list(target_position)
        if position is None:
            center[1] = size[1] / 2
        center[0] = snap_within(center[0], -room[0] / 2 + margin + size[0] / 2,
                                room[0] / 2 - margin - size[0] / 2)
        center[2] = snap_within(center[2], -room[2] / 2 + margin + size[2] / 2,
                                room[2] / 2 - margin - size[2] / 2)
        center[1] = snap_within(center[1], size[1] / 2,
                                room[1] - margin - size[1] / 2)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    rgb = color if color is not None else [128, 145, 168]
    if (not isinstance(rgb, (list, tuple)) or len(rgb) != 3
            or any(isinstance(value, bool) or not isinstance(value, (int, float))
                   or not math.isfinite(float(value)) for value in rgb)):
        return {"ok": False, "error": "color must contain three finite RGB values"}
    rgb = [max(0, min(255, round(float(value)))) for value in rgb]
    anchor = {"name": clean_name, "shape": "Block", "material": "SmoothPlastic",
              "position": center, "size": size, "color": rgb, "physics": "static"}
    clean_model = " ".join(str(model or "").strip().casefold().replace("_", " ").split())
    supported_models = {"building", "house", "shop", "tower", "school", "cafe", "station",
                        "temple", "market", "hall", "library", "museum", "bakery",
                        "restaurant", "clinic", "workshop", "cottage", "castle", "tree",
                        "plant", "bench", "lamp", "stall", "fence", "rock", "statue", "vehicle"}
    if clean_model:
        if clean_model not in supported_models:
            return {"ok": False, "error": "model must be a supported generated map model such as house, tree, or bench"}
        anchor["model"] = clean_model
    return {
        "ok": True,
        "anchor": anchor,
        "source_dimensions": dims,
        "source_units_per_stud": 1.0 / scale_units,
        "scale_applied": round(factor, 5),
        "room_size": room,
        "note": ("Anchor dimensions are measured, grid-aligned, and fitted with the "
                 "requested clearance. This is a map-plan reference only: the current "
                 "short renderer uses editable Part/model anchor geometry and does not "
                 "import the downloaded mesh into the MP4."),
    }


def _image_bytes(path: Path, *, max_edge: int = MAX_IMAGE_EDGE) -> tuple[bytes, str, tuple[int, int]]:
    from PIL import Image, ImageOps
    Image.MAX_IMAGE_PIXELS = 20_000_000
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        original_size = image.size
        image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=86, optimize=True)
    data = buffer.getvalue()
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("processed image exceeds the 8 MiB API limit")
    return data, "image/jpeg", original_size


def fetch_image(root: Path, url: str, path: str = "reference_face.png", **_: Any) -> dict:
    data, _, final_url = _download(url)
    from PIL import Image
    target = safe_path(root, path)
    target = target.with_suffix(".png")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
        image.convert("RGBA" if "A" in image.getbands() else "RGB").save(target, format="PNG", optimize=True)
    except Exception as exc:
        raise ValueError(f"downloaded image could not be decoded: {exc}") from exc
    return {"ok": True, "path": target.relative_to(Path(root).resolve()).as_posix(),
            "bytes": target.stat().st_size, "source": final_url}


def _gemini_parts(prompt: str, parts: list[dict], *, image_model: bool = False) -> tuple[str, list[tuple[str, bytes]]]:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured; image understanding/generation is unavailable")
    model = (os.environ.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image") if image_model
             else os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"))
    url = GEMINI_ENDPOINT.format(model=model)
    content_parts: list[dict] = [{"text": prompt}, *parts]
    config: dict[str, Any] = {"temperature": 0.25, "maxOutputTokens": 2048}
    if image_model:
        config["responseModalities"] = ["TEXT", "IMAGE"]
    body = json.dumps({"contents": [{"role": "user", "parts": content_parts}],
                       "generationConfig": config}).encode("utf-8")
    request = urllib.request.Request(url, data=body,
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"Gemini image request returned HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Gemini image request failed: {type(exc).__name__}: {exc}") from exc
    texts: list[str] = []
    images: list[tuple[str, bytes]] = []
    for candidate in payload.get("candidates") or []:
        for item in (candidate.get("content") or {}).get("parts") or []:
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                texts.append(text.strip())
            data = item.get("inlineData") or item.get("inline_data") or {}
            encoded = data.get("data")
            mime = data.get("mimeType") or data.get("mime_type") or "image/png"
            if encoded:
                try:
                    raw = base64.b64decode(encoded, validate=True)
                    if len(raw) <= MAX_IMAGE_BYTES:
                        images.append((mime, raw))
                except (ValueError, TypeError):
                    continue
    return "\n".join(texts).strip(), images


def inspect_image(root: Path, path: str, question: str = "Describe the visual style and details that should guide the output.", **_: Any) -> dict:
    target = safe_path(root, path)
    if not target.is_file():
        return {"ok": False, "error": f"image not found: {path}"}
    image, mime, dimensions = _image_bytes(target)
    prompt = ("Inspect this supplied reference image. " + str(question or "Describe its visual style.")
              + " Be specific about visible colors, facial features, eyebrow shape/thickness, expression, "
                "lighting, and style. Distinguish observation from guesses; do not identify a person.")
    text, _ = _gemini_parts(prompt, [{"inline_data": {"mime_type": mime,
                                                       "data": base64.b64encode(image).decode("ascii")}}])
    if not text:
        return {"ok": False, "error": "Gemini returned no visual description"}
    return {"ok": True, "path": target.relative_to(Path(root).resolve()).as_posix(),
            "dimensions": list(dimensions), "analysis": text[:6000]}


def _save_gemini_image(root: Path, output: str, prompt: str, reference: str = "") -> dict:
    parts: list[dict] = []
    if reference:
        source = safe_path(root, reference)
        if not source.is_file():
            return {"ok": False, "error": f"reference image not found: {reference}"}
        image, mime, _ = _image_bytes(source)
        parts.append({"inline_data": {"mime_type": mime,
                                      "data": base64.b64encode(image).decode("ascii")}})
    text, images = _gemini_parts(str(prompt or "Create a clean, vivid reference illustration."),
                                 parts, image_model=True)
    if not images:
        return {"ok": False, "error": "Gemini returned no image. Check GEMINI_IMAGE_MODEL and image-generation access.",
                "text": text[:1200]}
    target = safe_path(root, output or "generated.png")
    target.parent.mkdir(parents=True, exist_ok=True)
    mime, data = images[0]
    from PIL import Image
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
        suffix = ".jpg" if mime in ("image/jpeg", "image/jpg") else ".png"
        target = target.with_suffix(suffix)
        image.save(target, format="JPEG" if suffix == ".jpg" else "PNG", quality=92)
    except Exception as exc:
        raise ValueError(f"Gemini image could not be decoded: {exc}") from exc
    return {"ok": True, "path": target.relative_to(Path(root).resolve()).as_posix(),
            "bytes": target.stat().st_size, "text": text[:1200]}


def generate_image(root: Path, prompt: str, output: str = "generated.png", **_: Any) -> dict:
    return _save_gemini_image(root, prompt, output)


def edit_image(root: Path, path: str, prompt: str, output: str = "edited.png", **_: Any) -> dict:
    return _save_gemini_image(root, prompt, output, path)


def resize_image(root: Path, path: str, width: int, height: int = 0,
                 output: str = "resized.png", **_: Any) -> dict:
    from PIL import Image, ImageOps
    source = safe_path(root, path)
    target = safe_path(root, output)
    width, height = int(width), int(height or 0)
    if width < 1 or width > 8192 or height < 0 or height > 8192:
        return {"ok": False, "error": "width/height must be between 1 and 8192 (height 0 keeps aspect ratio)"}
    with Image.open(source) as image:
        image = ImageOps.exif_transpose(image)
        if height == 0:
            ratio = width / image.width
            height = max(1, round(image.height * ratio))
        image = image.resize((width, height), Image.Resampling.LANCZOS)
        target.parent.mkdir(parents=True, exist_ok=True)
        image.save(target)
    return {"ok": True, "path": target.relative_to(Path(root).resolve()).as_posix(),
            "dimensions": [width, height]}


def crop_image(root: Path, path: str, x: int, y: int, width: int, height: int,
               output: str = "crop.png", **_: Any) -> dict:
    from PIL import Image, ImageOps
    source = safe_path(root, path)
    target = safe_path(root, output)
    x, y, width, height = int(x), int(y), int(width), int(height)
    if x < 0 or y < 0 or width < 1 or height < 1:
        return {"ok": False, "error": "crop x/y must be non-negative and width/height positive"}
    with Image.open(source) as image:
        image = ImageOps.exif_transpose(image)
        if x + width > image.width or y + height > image.height:
            return {"ok": False, "error": "crop rectangle falls outside the source image"}
        target.parent.mkdir(parents=True, exist_ok=True)
        image.crop((x, y, x + width, y + height)).save(target)
    return {"ok": True, "path": target.relative_to(Path(root).resolve()).as_posix(),
            "dimensions": [width, height]}


def convert_image(root: Path, path: str, format: str, output: str = "converted.png", **_: Any) -> dict:
    from PIL import Image, ImageOps
    source = safe_path(root, path)
    target = safe_path(root, output)
    kind = str(format or target.suffix.lstrip(".")).upper()
    if kind == "JPG":
        kind = "JPEG"
    if kind not in {"PNG", "JPEG", "WEBP", "BMP"}:
        return {"ok": False, "error": "supported formats: PNG, JPEG, WEBP, BMP"}
    target = target.with_suffix({"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "BMP": ".bmp"}[kind])
    with Image.open(source) as image:
        image = ImageOps.exif_transpose(image)
        if kind == "JPEG":
            image = image.convert("RGB")
        target.parent.mkdir(parents=True, exist_ok=True)
        image.save(target, format=kind, quality=90 if kind in {"JPEG", "WEBP"} else None)
    return {"ok": True, "path": target.relative_to(Path(root).resolve()).as_posix(),
            "format": kind, "bytes": target.stat().st_size}


def compare_images(root: Path, path_a: str, path_b: str, **_: Any) -> dict:
    from PIL import Image, ImageChops, ImageStat, ImageOps
    a, b = safe_path(root, path_a), safe_path(root, path_b)
    with Image.open(a) as first, Image.open(b) as second:
        first = ImageOps.fit(first.convert("RGB"), (256, 256))
        second = ImageOps.fit(second.convert("RGB"), (256, 256))
        diff = ImageChops.difference(first, second)
        mean = sum(ImageStat.Stat(diff).mean) / 3
        changed = sum(1 for pixel in diff.getdata() if max(pixel) > 24)
        fraction = changed / (256 * 256)
    return {"ok": True, "mean_absolute_difference": round(mean, 2),
            "changed_pixel_fraction": round(fraction, 4),
            "similarity_percent": round((1 - fraction) * 100, 1)}


def make_contact_sheet(root: Path, paths: list[str], output: str = "contact_sheet.jpg", **_: Any) -> dict:
    from PIL import Image, ImageDraw, ImageOps
    values = [str(value) for value in (paths or [])[:12]]
    if not values:
        return {"ok": False, "error": "paths must contain at least one image"}
    tile_w, tile_h = 320, 240
    columns = min(3, len(values))
    rows = (len(values) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * tile_w, rows * tile_h), (28, 30, 34))
    draw = ImageDraw.Draw(sheet)
    for index, relative in enumerate(values):
        source = safe_path(root, relative)
        with Image.open(source) as image:
            tile = ImageOps.contain(ImageOps.exif_transpose(image).convert("RGB"), (tile_w - 16, tile_h - 42))
        x, y = (index % columns) * tile_w, (index // columns) * tile_h
        sheet.paste(tile, (x + (tile_w - tile.width) // 2, y + 5))
        draw.text((x + 8, y + tile_h - 30), relative[:44], fill=(235, 235, 238))
    target = safe_path(root, output)
    target.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(target, format="JPEG", quality=90)
    return {"ok": True, "path": target.relative_to(Path(root).resolve()).as_posix(),
            "images": len(values), "dimensions": list(sheet.size)}


def inspect_video(root: Path, path: str, **_: Any) -> dict:
    target = safe_path(root, path)
    ffprobe = shutil.which("ffprobe")
    if not target.is_file():
        return {"ok": False, "error": f"video not found: {path}"}
    if not ffprobe:
        return {"ok": False, "error": "ffprobe is not installed"}
    try:
        result = subprocess.run([ffprobe, "-v", "error", "-show_streams", "-show_format",
                                 "-of", "json", str(target)], capture_output=True, text=True, timeout=30)
        if result.returncode:
            return {"ok": False, "error": (result.stderr or "ffprobe failed")[:1500]}
        data = json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as exc:
        return {"ok": False, "error": str(exc)}
    streams = [{key: stream.get(key) for key in
                ("codec_type", "codec_name", "width", "height", "duration", "sample_aspect_ratio", "avg_frame_rate")
                if key in stream} for stream in data.get("streams", [])]
    return {"ok": True, "path": target.relative_to(Path(root).resolve()).as_posix(),
            "duration": (data.get("format") or {}).get("duration"), "streams": streams}


def package_files(root: Path, path: str = ".", output: str = "deliverable.zip", **_: Any) -> dict:
    base = safe_path(root, path, allow_root=True)
    target = safe_path(root, output)
    if not base.exists():
        return {"ok": False, "error": f"path not found: {path}"}
    target.parent.mkdir(parents=True, exist_ok=True)
    ignored = {".git", "node_modules", ".venv", "__pycache__", ".next", ".cache"}
    total = 0
    files = 0
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        candidates = [base] if base.is_file() else sorted(base.rglob("*"))
        for source in candidates:
            if not source.is_file() or source.resolve() == target.resolve():
                continue
            relative = source.relative_to(Path(root).resolve())
            if any(part in ignored for part in relative.parts) or source.is_symlink():
                continue
            size = source.stat().st_size
            total += size
            if total > MAX_ZIP_BYTES:
                target.unlink(missing_ok=True)
                return {"ok": False, "error": "selected files exceed the 100 MiB ZIP input limit"}
            archive.write(source, relative.as_posix())
            files += 1
    return {"ok": True, "path": target.relative_to(Path(root).resolve()).as_posix(),
            "files": files, "uncompressed_bytes": total, "bytes": target.stat().st_size}


def _short_text(root: Path, path: str = "", text: str = "") -> tuple[str, dict | None]:
    if path:
        source = safe_path(root, path)
        if not source.is_file():
            return "", {"ok": False, "error": f"file not found: {path}"}
        if source.stat().st_size > MAX_TEXT_BYTES * 8:
            return "", {"ok": False, "error": "input file is too large for a short-production tool"}
        return _bounded_text(source, MAX_TEXT_BYTES * 8), None
    value = str(text or "")
    if len(value.encode("utf-8")) > MAX_TEXT_BYTES * 4:
        return "", {"ok": False, "error": "text input exceeds the 96 KB tool limit"}
    return value, None


def analyze_short_script(root: Path, path: str = "", text: str = "",
                         duration: float = 150, **_: Any) -> dict:
    source, error = _short_text(root, path, text)
    if error:
        return error
    from rbx_short_tools import analyze_short_script as analyze
    return analyze(source, duration)


def plan_short_lighting(root: Path, path: str = "", text: str = "",
                         duration: float = 150, **_: Any) -> dict:
    source, error = _short_text(root, path, text)
    if error:
        return error
    from rbx_short_tools import plan_short_lighting as plan
    return plan(source, duration)


def audit_roblox_map(root: Path, path: str, duration: float = 150,
                     cast: list[str] | str = (), **_: Any) -> dict:
    source = safe_path(root, path)
    if not source.is_file():
        return {"ok": False, "error": f"map file not found: {path}"}
    if source.stat().st_size > 32 * 1024 * 1024:
        return {"ok": False, "error": "map file exceeds the 32 MiB audit limit"}
    plan = json.loads(source.read_text(encoding="utf-8"))
    if isinstance(cast, str):
        cast_names = [name.strip() for name in cast.replace(";", ",").split(",") if name.strip()]
    else:
        cast_names = [str(name).strip() for name in cast or [] if str(name).strip()]
    from rbx_short_tools import audit_roblox_map as audit
    return audit(plan, duration, cast_names)


def audit_short_captions(root: Path, path: str = "", text: str = "",
                         duration: float = 0, max_words: int = 1, **_: Any) -> dict:
    source, error = _short_text(root, path, text)
    if error:
        return error
    from rbx_short_tools import audit_short_captions as audit
    return audit(source, duration, max_words)


def inspect_roblox_short(root: Path, path: str, report: str = "",
                         frames_dir: str = "", samples: int = 8,
                         timeout: int = 180, **_: Any) -> dict:
    video = safe_path(root, path)
    if not video.is_file():
        return {"ok": False, "error": f"video not found: {path}"}
    root_path = Path(root).resolve()
    report_path = safe_path(root_path, report) if report else None
    if report_path and report_path.resolve() == video.resolve():
        return {"ok": False, "error": "inspection report must not overwrite the source video"}
    if report_path and report_path.exists() and report_path.is_dir():
        return {"ok": False, "error": "inspection report path points to a directory"}
    frames_path = safe_path(root_path, frames_dir, allow_root=True) if frames_dir else None
    if frames_path and frames_path.resolve() == video.resolve():
        return {"ok": False, "error": "frames directory must not be the source video"}
    if frames_path and frames_path.exists() and not frames_path.is_dir():
        return {"ok": False, "error": "frames directory path points to a file"}
    if report_path and frames_path and report_path.resolve() == frames_path.resolve():
        return {"ok": False, "error": "inspection report path must not be the frames directory"}
    from rbx_short_tools import inspect_roblox_short as inspect
    result = inspect(video, report_path, frames_path, samples, timeout)
    if report_path:
        result["report"] = report_path.relative_to(root_path).as_posix()
    if frames_path:
        result["frames_dir"] = frames_path.relative_to(root_path).as_posix()
    return result


_DISPATCH = {
    "search_web": search_web,
    "search_assets": search_assets,
    "find_model_reference": find_model_reference,
    "search_roblox_meshes": search_roblox_meshes,
    "fetch_mesh_reference": fetch_mesh_reference,
    "inspect_mesh_dimensions": inspect_mesh_dimensions,
    "plan_mesh_placement": plan_mesh_placement,
    "create_file": create_file,
    "read_file": read_file,
    "list_files": list_files,
    "search_files": search_files,
    "edit_file": edit_file,
    "run_cmd": run_cmd,
    "fetch_image": fetch_image,
    "inspect_image": inspect_image,
    "resize_image": resize_image,
    "crop_image": crop_image,
    "convert_image": convert_image,
    "compare_images": compare_images,
    "make_contact_sheet": make_contact_sheet,
    "generate_image": generate_image,
    "edit_image": edit_image,
    "inspect_video": inspect_video,
    "package_files": package_files,
    "analyze_short_script": analyze_short_script,
    "plan_short_lighting": plan_short_lighting,
    "audit_roblox_map": audit_roblox_map,
    "audit_short_captions": audit_short_captions,
    "inspect_roblox_short": inspect_roblox_short,
}


def execute_tool(name: str, arguments: dict, root: Path) -> dict:
    name = str(name or "").strip().lower()
    aliases = {"search": "search_web", "web_search": "search_web",
               "search_models": "find_model_reference", "read_image": "inspect_image",
               "create_image": "generate_image", "download_image": "fetch_image",
               "make_zip": "package_files"}
    name = aliases.get(name, name)
    if name not in _DISPATCH:
        return {"ok": False, "error": f"unknown tool {name}"}
    try:
        return _DISPATCH[name](root=Path(root), **(arguments or {}))
    except (ValueError, OSError, RuntimeError, urllib.error.URLError) as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:1200]}
    except Exception as exc:  # model-authored tool calls should fail as tool results, not kill the run
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:1200]}
