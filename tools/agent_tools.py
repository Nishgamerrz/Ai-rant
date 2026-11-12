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
import os
import shutil
import socket
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
GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# Twenty callable tools, shared by the local agent and the sub-agent.
TOOL_NAMES = (
    "search_web", "search_assets", "find_model_reference",
    "create_file", "read_file", "list_files", "search_files", "edit_file",
    "run_cmd", "fetch_image", "inspect_image", "resize_image", "crop_image",
    "convert_image", "compare_images", "make_contact_sheet", "generate_image",
    "edit_image", "inspect_video", "package_files",
)

TOOL_GUIDE = """\
AVAILABLE TOOLS (you must write every requested call yourself in a JSON
`tool_calls` array; the runner executes only calls you actually authored):
- search_web(query): current web results for facts.
- search_assets(query): search for visual/model assets and references; use it for
  props such as a light bulb, bed, lamp, or house. Returns source links, not fake IDs.
- find_model_reference(name, kind): find Roblox/catalog/model references for a named prop.
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
        raise ValueError("only public HTTPS image URLs without embedded credentials are accepted")
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


_DISPATCH = {
    "search_web": search_web,
    "search_assets": search_assets,
    "find_model_reference": find_model_reference,
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
