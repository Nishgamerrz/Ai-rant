#!/usr/bin/env python3
"""Fetch public Roblox avatar OBJ/MTL assets and sampled appearance data."""
from __future__ import annotations

import json
import os
import re
import statistics
import sys
import time
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def request_bytes(url: str, data: dict | None = None) -> bytes:
    body = json.dumps(data).encode("utf-8") if data is not None else None
    request = Request(url, data=body, headers={
        "User-Agent": "Ai-rant-short-render/1.0",
        "Accept": "application/json, */*",
        **({"Content-Type": "application/json"} if body else {}),
    }, method="POST" if body else "GET")
    with urlopen(request, timeout=25) as response:
        return response.read()


def request_json(url: str, data: dict | None = None):
    return json.loads(request_bytes(url, data).decode("utf-8"))


def cdn_url(asset_hash: str) -> str:
    # Roblox's public avatar-3d response returns content hashes rather than full CDN URLs.
    server = 31
    for character in asset_hash[:38]:
        server ^= ord(character)
    return f"https://t{server % 8}.rbxcdn.com/{asset_hash}"


def image_extension(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return ".png"


def image_pixels(image):
    # Pillow 13 deprecates getdata(); retain compatibility with older runner versions.
    flattened = getattr(image, "get_flattened_data", None)
    return flattened() if callable(flattened) else image.getdata()


def sample_color(image, box):
    width, height = image.size
    left, top, right, bottom = box
    crop = image.crop((int(left * width), int(top * height), int(right * width), int(bottom * height)))
    pixels = [rgba[:3] for rgba in image_pixels(crop) if rgba[3] > 200 and 18 < sum(rgba[:3]) / 3 < 238]
    if len(pixels) < 20:
        return None
    return [int(statistics.median(channel)) for channel in zip(*pixels)]


def sample_hair_color(image):
    width, height = image.size
    crop = image.crop((int(0.35 * width), int(0.10 * height), int(0.65 * width), int(0.25 * height)))
    pixels = [rgba[:3] for rgba in image_pixels(crop)
              if rgba[3] > 200 and 15 < sum(rgba[:3]) / 3 < 145]
    if len(pixels) < 12:
        return None
    return [int(statistics.median(channel)) for channel in zip(*pixels)]


def profile_from_thumbnail(url: str, output: Path):
    from PIL import Image
    raw = request_bytes(url)
    image = Image.open(BytesIO(raw)).convert("RGBA")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(raw)
    return {
        "skin_rgb": sample_color(image, (0.42, 0.20, 0.58, 0.38)),
        "hair_rgb": sample_hair_color(image),
        "shirt_rgb": sample_color(image, (0.32, 0.38, 0.68, 0.62)),
        "pants_rgb": sample_color(image, (0.34, 0.60, 0.66, 0.88)),
        "thumbnail": str(output),
    }


def avatar_model_document_url(user_id: int):
    """Try Roblox's current endpoint, then its legacy public endpoint without credentials."""
    endpoints = (
        ("avatar-3d", f"https://thumbnails.roblox.com/v1/users/avatar-3d?userId={user_id}"),
        ("legacy-avatar-3d", f"https://www.roblox.com/avatar-thumbnail-3d/json?userId={user_id}"),
    )
    failures = []
    for source, endpoint in endpoints:
        for attempt in range(6):
            try:
                response = request_json(endpoint)
            except HTTPError as exc:
                failures.append(f"{source} HTTP {exc.code}")
                if exc.code in (401, 403, 404) or attempt == 5:
                    break
                time.sleep(min(2 ** attempt, 8))
                continue
            except (URLError, TimeoutError, OSError, ValueError) as exc:
                failures.append(f"{source} {type(exc).__name__}")
                if attempt == 5:
                    break
                time.sleep(min(2 ** attempt, 8))
                continue

            if isinstance(response, list):
                response = response[0] if response and isinstance(response[0], dict) else {}
            if isinstance(response, dict) and isinstance(response.get("data"), list):
                response = next((item for item in response["data"] if isinstance(item, dict)), {})
            if not isinstance(response, dict):
                failures.append(f"{source} returned an invalid response")
                break

            model_url = response.get("imageUrl") or response.get("Url") or response.get("url")
            state = str(response.get("state", "")).casefold()
            pending = state not in ("", "completed") or response.get("Final") is False or response.get("final") is False
            if model_url and not pending:
                return source, model_url
            if not pending:
                failures.append(f"{source} returned no model URL")
                break
            if attempt < 5:
                time.sleep(1)
        # An authentication/permission failure on the current endpoint should
        # not block an automatic attempt through Roblox's alternate endpoint.
    raise RuntimeError("Roblox did not provide a public 3D avatar mesh (" + "; ".join(failures) + ")")


def fetch_avatar_model(user_id: int, output_dir: Path) -> dict:
    model_source, model_url = avatar_model_document_url(user_id)
    model_data = request_json(model_url)
    obj_hash, mtl_hash = model_data.get("obj"), model_data.get("mtl")
    texture_hashes = model_data.get("textures", [])
    if not isinstance(obj_hash, str) or not isinstance(mtl_hash, str) or not isinstance(texture_hashes, list):
        raise RuntimeError("Roblox avatar-3d response is missing OBJ/MTL/textures")

    output_dir.mkdir(parents=True, exist_ok=True)
    obj_text = request_bytes(cdn_url(obj_hash)).decode("utf-8", errors="replace")
    mtl_text = request_bytes(cdn_url(mtl_hash)).decode("utf-8", errors="replace")
    if not re.search(r"(?m)^\s*v\s", obj_text) or not re.search(r"(?m)^\s*f\s", obj_text):
        raise RuntimeError("Roblox avatar OBJ does not contain a readable mesh")

    texture_files = {}
    for texture_hash in texture_hashes:
        if not isinstance(texture_hash, str) or not texture_hash:
            continue
        data = request_bytes(cdn_url(texture_hash))
        texture_path = output_dir / f"texture_{texture_hash}{image_extension(data)}"
        texture_path.write_bytes(data)
        texture_files[texture_hash] = texture_path.name

    patched_mtl = []
    for line in mtl_text.splitlines():
        tokens = line.split()
        if tokens and tokens[0].lower().startswith("map_"):
            candidate = tokens[-1].split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
            candidate = os.path.splitext(candidate)[0]
            replacement = texture_files.get(candidate)
            if replacement:
                tokens[-1] = replacement
                line = " ".join(tokens)
        patched_mtl.append(line)

    obj_path = output_dir / "avatar.obj"
    mtl_path = output_dir / "avatar.mtl"
    obj_text = re.sub(r"(?m)^\s*mtllib\s+.*$", "mtllib avatar.mtl", obj_text)
    if not re.search(r"(?m)^\s*mtllib\s", obj_text):
        obj_text = "mtllib avatar.mtl\n" + obj_text
    obj_path.write_text(obj_text, encoding="utf-8")
    mtl_path.write_text("\n".join(patched_mtl) + "\n", encoding="utf-8")
    camera = model_data.get("camera", {}).get("position", {})
    bounds = model_data.get("aabb", {})
    low, high = bounds.get("min", {}), bounds.get("max", {})
    center = [(float(low.get(axis, 0)) + float(high.get(axis, 0))) / 2 for axis in ("x", "y", "z")]
    front = [float(camera.get(axis, 0)) - center[index] for index, axis in enumerate(("x", "y", "z"))]
    return {"model_obj": str(obj_path.resolve()), "model_mtl": str(mtl_path.resolve()),
            "model_ready": True, "texture_count": len(texture_files), "front_direction": front,
            "model_source": model_source}


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit("usage: fetch_roblox_avatars.py USERNAMES.json OUTPUT_PROFILES.json ASSET_DIR")
    usernames_path, output_path, asset_root = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    usernames = json.loads(usernames_path.read_text(encoding="utf-8"))
    if not usernames:
        raise SystemExit("At least one public Roblox username is required to render a real avatar in the MP4.")

    try:
        result = request_json(
            "https://users.roblox.com/v1/usernames/users",
            {"usernames": usernames, "excludeBannedUsers": True},
        )
        by_name = {item.get("requestedUsername", "").casefold(): item for item in result.get("data", [])}
        records = []
        for username in usernames:
            item = by_name.get(username.casefold())
            if not item or not item.get("id"):
                raise RuntimeError(f"Roblox username {username!r} was not found")
            user_id = int(item["id"])
            profile = {"username": username, "user_id": user_id}
            try:
                thumbs = request_json(
                    "https://thumbnails.roblox.com/v1/users/avatar?"
                    f"userIds={user_id}&size=420x420&format=Png&isCircular=false"
                )
                thumb = next((t.get("imageUrl") for t in thumbs.get("data", []) if t.get("imageUrl")), None)
                if thumb:
                    profile.update(profile_from_thumbnail(thumb, asset_root / str(user_id) / "avatar.png"))
            except Exception as exc:
                print(f"Avatar thumbnail color sampling failed for {username}: {type(exc).__name__}.", file=sys.stderr)
            try:
                profile.update(fetch_avatar_model(user_id, asset_root / str(user_id)))
                print(f"Fetched Roblox avatar mesh and textures for {username} ({profile['texture_count']} textures; source={profile['model_source']}).")
            except (HTTPError, URLError, TimeoutError, OSError, ValueError, KeyError, RuntimeError) as exc:
                thumbnail_path = Path(profile.get("thumbnail", ""))
                if not thumbnail_path.is_file() or thumbnail_path.stat().st_size == 0:
                    raise RuntimeError(f"Roblox mesh access failed and no real avatar thumbnail is available for {username}: {exc}") from exc
                profile.update({
                    "model_ready": False,
                    "thumbnail_ready": True,
                    "mesh_error": f"{type(exc).__name__}: {exc}",
                })
                print(f"Roblox automatic 3D mesh lookup failed for {username} ({exc}); using that account's official thumbnail, not a generated substitute.", file=sys.stderr)
            records.append(profile)
            time.sleep(0.12)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, KeyError, RuntimeError) as exc:
        raise SystemExit(f"Could not prepare the actual Roblox avatar(s); no approximate-avatar video will be uploaded: {exc}") from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Prepared {len(records)} authentic Roblox avatar profile(s) for rendering; each uses the account's real mesh when available or its official account thumbnail otherwise.")


if __name__ == "__main__":
    main()
