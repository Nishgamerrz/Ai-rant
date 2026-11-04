#!/usr/bin/env python3
"""Fetch public Roblox avatar OBJ/MTL assets and sampled appearance data."""
from __future__ import annotations

import json
import os
import re
import statistics
import sys
import time
import shutil
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

USERS_ROOT = Path(__file__).resolve().parents[1] / "users"
LOCAL_ASSET_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def request_bytes(url: str, data: dict | None = None, headers: dict[str, str] | None = None) -> bytes:
    body = json.dumps(data).encode("utf-8") if data is not None else None
    request_headers = {
        "User-Agent": "Ai-rant-short-render/1.0",
        "Accept": "application/json, */*",
        **({"Content-Type": "application/json"} if body else {}),
        **(headers or {}),
    }
    request = Request(url, data=body, headers=request_headers, method="POST" if body else "GET")
    with urlopen(request, timeout=25) as response:
        return response.read()


def request_json(url: str, data: dict | None = None, headers: dict[str, str] | None = None):
    return json.loads(request_bytes(url, data, headers).decode("utf-8"))


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


def avatar_model_document_url(user_id: int, open_cloud_api_key: str = ""):
    """Try Roblox's current endpoint with an optional scoped API key, then legacy."""
    endpoints = (
        ("avatar-3d", f"https://thumbnails.roblox.com/v1/users/avatar-3d?userId={user_id}"),
        ("legacy-avatar-3d", f"https://www.roblox.com/avatar-thumbnail-3d/json?userId={user_id}"),
    )
    failures = []
    for source, endpoint in endpoints:
        for attempt in range(6):
            try:
                api_headers = ({"x-api-key": open_cloud_api_key}
                               if source == "avatar-3d" and open_cloud_api_key else None)
                response = request_json(endpoint, headers=api_headers) if api_headers else request_json(endpoint)
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
    open_cloud_api_key = os.environ.get("ROBLOX_OPEN_CLOUD_API_KEY", "").strip()
    model_source, model_url = avatar_model_document_url(user_id, open_cloud_api_key)
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


def find_local_avatar_folder(username: str, users_root: Path = USERS_ROOT) -> Path | None:
    """Find users/<username> case-insensitively without allowing path traversal."""
    if not re.fullmatch(r"[A-Za-z0-9_]{3,20}", username) or not users_root.is_dir() or users_root.is_symlink():
        return None
    root = users_root.resolve()
    for candidate in users_root.iterdir():
        if (candidate.is_dir() and not candidate.is_symlink()
                and candidate.name.casefold() == username.casefold()
                and candidate.resolve().is_relative_to(root)):
            return candidate
    return None


def has_local_avatar_obj(username: str, users_root: Path = USERS_ROOT) -> bool:
    folder = find_local_avatar_folder(username, users_root)
    if folder is None:
        return False
    return any(path.is_file() and not path.is_symlink() and path.name.casefold() == "avatar.obj"
               for path in folder.iterdir())


def load_local_avatar_model(username: str, user_id: int | str, users_root: Path, output_dir: Path) -> dict | None:
    """Use a staged users/<username>/avatar.obj before making an authenticated network request."""
    user_folder = find_local_avatar_folder(username, users_root)
    if user_folder is None:
        return None

    candidates = {path.name.casefold(): path for path in user_folder.iterdir()
                  if path.is_file() and not path.is_symlink()}
    source_obj = candidates.get("avatar.obj")
    if source_obj is None:
        return None
    obj_text = source_obj.read_text(encoding="utf-8", errors="replace")
    if not re.search(r"(?m)^\s*v\s", obj_text) or not re.search(r"(?m)^\s*f\s", obj_text):
        raise ValueError(f"{user_folder}/avatar.obj does not contain a readable OBJ mesh")

    source_mtl = candidates.get("avatar.mtl") or next(
        (path for path in user_folder.iterdir()
         if path.is_file() and not path.is_symlink() and path.suffix.casefold() == ".mtl"),
        None,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    copied_textures = 0
    for source in user_folder.rglob("*"):
        if (source.is_symlink() or not source.is_file()
                or source.suffix.casefold() not in LOCAL_ASSET_SUFFIXES):
            continue
        relative = source.relative_to(user_folder)
        destination = output_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        copied_textures += 1

    obj_path = output_dir / "avatar.obj"
    obj_text = re.sub(r"(?m)^\s*mtllib\s+.*$", "mtllib avatar.mtl", obj_text)
    if not re.search(r"(?m)^\s*mtllib\s", obj_text):
        obj_text = "mtllib avatar.mtl\n" + obj_text
    obj_path.write_text(obj_text, encoding="utf-8")
    mtl_path = output_dir / "avatar.mtl"
    if source_mtl is not None:
        shutil.copyfile(source_mtl, mtl_path)
    else:
        mtl_path.write_text("newmtl LocalAvatar\nKd 0.72 0.72 0.72\n", encoding="utf-8")

    return {"model_obj": str(obj_path.resolve()), "model_mtl": str(mtl_path.resolve()),
            "model_ready": True, "texture_count": copied_textures,
            "front_direction": [0, 0, 1], "model_source": "users-folder"}


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit("usage: fetch_roblox_avatars.py USERNAMES.json OUTPUT_PROFILES.json ASSET_DIR")
    usernames_path, output_path, asset_root = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    usernames = json.loads(usernames_path.read_text(encoding="utf-8"))
    if not usernames:
        raise SystemExit("At least one public Roblox username is required to render a real avatar in the MP4.")

    try:
        try:
            result = request_json(
                "https://users.roblox.com/v1/usernames/users",
                {"usernames": usernames, "excludeBannedUsers": False},
            )
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as lookup_error:
            print(f"Roblox username lookup failed ({type(lookup_error).__name__}); checking local users/<username>/avatar.obj files.", file=sys.stderr)
            result = {}
        data = result.get("data", []) if isinstance(result, dict) else []
        by_name = {item.get("requestedUsername", "").casefold(): item
                   for item in data if isinstance(item, dict) and isinstance(item.get("requestedUsername"), str)}
        records = []
        for username in usernames:
            item = by_name.get(username.casefold())
            local_only = False
            if item and item.get("id"):
                user_id: int | str = int(item["id"])
            elif has_local_avatar_obj(username, USERS_ROOT):
                user_id = f"local-{username.casefold()}"
                local_only = True
                print(f"Roblox did not resolve {username}; using the matching local users/{username}/avatar.obj.")
            else:
                raise RuntimeError(f"Roblox username {username!r} was not found and no local users/{username}/avatar.obj exists")
            profile = {"username": username, "user_id": user_id}
            if not local_only:
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
                try:
                    local_model = load_local_avatar_model(username, user_id, USERS_ROOT, asset_root / str(user_id))
                except (OSError, ValueError) as local_error:
                    print(f"Local users/{username}/avatar.obj could not be used ({local_error}).", file=sys.stderr)
                    local_model = None
                if local_model:
                    profile.update(local_model)
                    print(f"Loaded local avatar OBJ for {username} from users/{username}/avatar.obj ({local_model['texture_count']} local texture files).")
                elif local_only:
                    raise RuntimeError(f"Local avatar mesh for {username} is unreadable")
                else:
                    profile.update(fetch_avatar_model(int(user_id), asset_root / str(user_id)))
                    print(f"Fetched Roblox avatar mesh and textures for {username} ({profile['texture_count']} textures; source={profile['model_source']}).")
            except (HTTPError, URLError, TimeoutError, OSError, ValueError, KeyError, RuntimeError) as exc:
                thumbnail_path = Path(profile.get("thumbnail", ""))
                if local_only or not thumbnail_path.is_file() or thumbnail_path.stat().st_size == 0:
                    raise RuntimeError(f"Avatar mesh access failed and no usable official thumbnail is available for {username}: {exc}") from exc
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
    print(f"Prepared {len(records)} avatar profile(s) for the requested Roblox usernames; source details are reported per profile.")


if __name__ == "__main__":
    main()
