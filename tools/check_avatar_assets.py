#!/usr/bin/env python3
"""Fail in the first minutes, not after a 50-minute render.

Run #84 spent fifty-two minutes rendering 3840 frames and then the quality gate
refused the finished video because one avatar had no `.mtl` - a check that could
have run the moment the avatars were downloaded. This is that check, moved to
the front of the run: every requested username must already have an authentic
mesh or a public avatar portrait on disk before any AI time or GPU-free render
time is spent on it.

Usage:
    python tools/check_avatar_assets.py dist/avatar_profiles.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from validate_short import avatar_asset_type  # noqa: E402


def asset_directory(profiles_path: Path, profile: dict) -> Path | None:
    user_id = profile.get("user_id")
    if not user_id:
        return None
    return profiles_path.parent / "avatar-assets" / str(user_id)


def check(profiles_path: Path) -> int:
    profiles = json.loads(profiles_path.read_text(encoding="utf-8"))
    if not isinstance(profiles, list) or not profiles:
        print(f"FAIL avatar assets: no profiles in {profiles_path}")
        return 1
    report, missing = [], []
    for profile in profiles:
        username = str(profile.get("username") or "?")
        source = avatar_asset_type(profile, asset_directory(profiles_path, profile))
        detail = profile.get("model_file") or profile.get("model_obj") or ""
        reason = profile.get("rbxm_import_error") or profile.get("mesh_error") or ""
        if source == "mesh":
            report.append(f"- **{username}:** authentic 3D mesh `{Path(detail).name}`")
            print(f"Avatar {username}: authentic 3D mesh {detail or '(loaded)'} - OK")
        elif source == "thumbnail":
            report.append(f"- **{username}:** public avatar portrait (no 3D mesh)")
            print(f"Avatar {username}: public avatar portrait - OK (2D stand-in)")
        else:
            line = f"- **{username}:** nothing usable on disk"
            if reason:
                line += f" ({reason})"
            report.append(line)
            missing.append(username)
            print(f"Avatar {username}: FAIL - no mesh and no portrait on disk"
                  + (f" ({reason})" if reason else ""), file=sys.stderr)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as out:
            out.write("## Avatar asset preflight\n" + "\n".join(report) + "\n")
    if missing:
        print("FAIL avatar assets: " + ", ".join(missing) + " would be an empty spot in the video; "
              "stopping now instead of after the render.", file=sys.stderr)
        return 1
    print("Avatar asset preflight passed: every requested username has a real Roblox asset.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("profiles", type=Path)
    args = parser.parse_args()
    if not args.profiles.is_file():
        print(f"FAIL avatar assets: missing {args.profiles}", file=sys.stderr)
        return 1
    try:
        return check(args.profiles)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"FAIL avatar assets: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
