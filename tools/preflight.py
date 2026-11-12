#!/usr/bin/env python3
"""Check the whole pipeline in the first two minutes, not at the last step.

Every expensive failure this workflow has had landed at the end of an hour -
after the model download, the story, the world plan and the narration - because
nothing proved the *tools* worked until they were needed:

* a backtick inside the renderer's HTML template, which only surfaced when
  buildHtml() ran;
* a missing npm module, which only surfaced when Chromium loaded the page;
* an avatar rig whose joint map was mistaken for its Three.js root, which only
  surfaced after the story and the full camera plan were finished;
* a renderer that needed a GPU flag, which only surfaced at the first frame.

This script runs those checks up front with a synthetic R15 OBJ avatar, so the
real browser scene-ready and avatar-rig path fails fast with the exact browser
error instead of waiting an hour for the production render. It is deliberately stdlib-only, so it works before any pip install.

    python tools/preflight.py            # static checks only
    python tools/preflight.py --render   # also render one real frame
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RENDERER = ROOT / "tools" / "video_renderer"
FAILURES: list[str] = []


def ok(message: str) -> None:
    print(f"  ok   {message}", flush=True)


def fail(message: str) -> None:
    FAILURES.append(message)
    print(f"  FAIL {message}", flush=True)
    # A GitHub runner shows this on the run page as an annotation, and the
    # annotations API can read it back - the only way to see why a job failed
    # when the raw job log sits behind a storage URL that will not open.
    summary = " ".join(message.split())
    print(f"::error title=Preflight failed::{summary[:900]}", flush=True)


def check(label: str, fn) -> None:
    try:
        fn()
        ok(label)
    except AssertionError as exc:
        fail(f"{label}: {exc}")
    except Exception as exc:  # noqa: BLE001 - any breakage is a failure to report
        fail(f"{label}: {type(exc).__name__}: {exc}")


def explain(output: str, lines: int = 25) -> str:
    """The useful part of a subprocess failure, not just the last stack line.

    A Node crash ends with a stack frame, so reporting only the final line threw
    away the one line that says what broke.
    """
    rows = [row for row in output.splitlines() if row.strip()]
    if not rows:
        return "no output"
    interesting = [row for row in rows
                   if row.lstrip().startswith(("Error", "TypeError", "RangeError",
                                               "Error [", "  FAIL", "RuntimeError"))]
    picked = interesting[:2] + rows[-lines:]
    seen, unique = set(), []
    for row in picked:
        if row not in seen:
            seen.add(row)
            unique.append(row)
    return "\n".join(unique)


def python_sources():
    """Every Python file in the repo must at least compile."""
    broken = []
    for path in sorted(ROOT.rglob("*.py")):
        if any(part in {".git", "node_modules", "dist", "__pycache__"} for part in path.parts):
            continue
        try:
            compile(path.read_text(encoding="utf-8", errors="replace"), str(path), "exec")
        except py_compile.PyCompileError as exc:
            broken.append(f"{path.relative_to(ROOT)}: {exc.msg.strip().splitlines()[-1]}")
    assert not broken, "; ".join(broken[:3])


def renderer_syntax():
    node = shutil.which("node")
    assert node, "node is not installed"
    scripts = sorted(RENDERER.glob("*.mjs"))
    assert scripts, "no renderer scripts found"
    for script in scripts:
        result = subprocess.run([node, "--check", str(script)], capture_output=True, text=True)
        assert result.returncode == 0, f"{script.name}: {explain(result.stderr, 4)}"


def page_template():
    node = shutil.which("node")
    assert node, "node is not installed"
    result = subprocess.run([node, str(RENDERER / "template_check.mjs")],
                            capture_output=True, text=True, cwd=RENDERER)
    assert result.returncode == 0, explain(result.stderr or result.stdout, 4)


def renderer_modules():
    modules = RENDERER / "node_modules"
    assert modules.is_dir(), "tools/video_renderer/node_modules is missing (run npm ci there)"
    for name in ("playwright", "three", "ffmpeg-static"):
        if name == "ffmpeg-static":
            continue            # the workflow uses the system ffmpeg
        assert (modules / name).exists(), f"npm module {name} is not installed"


def binaries():
    missing = [name for name in ("ffmpeg", "node", "npm") if not shutil.which(name)]
    assert not missing, f"not on PATH: {', '.join(missing)}"


def plan_schema():
    """The map schema must build, or the world-plan request cannot be made."""
    schema_path = ROOT / "tools" / "plan_schema.py"
    with tempfile.TemporaryDirectory() as tmp:
        cast = Path(tmp) / "cast.json"
        cast.write_text(json.dumps(["Lead"]), encoding="utf-8")
        out = Path(tmp) / "schema.json"
        result = subprocess.run([sys.executable, str(schema_path), "--usernames", str(cast),
                                 "--output", str(out)], capture_output=True, text=True, cwd=ROOT)
        assert result.returncode == 0, explain(result.stderr or result.stdout, 4)
        schema = json.loads(out.read_text(encoding="utf-8"))
        assert isinstance(schema, dict) and schema.get("properties"), "the plan schema is empty"
        required = schema.get("required") or []
        for key in ("name", "theme", "props"):
            assert key in required, f'the schema does not require "{key}"'
        cast = schema["properties"]["character_placements"]["items"]["properties"]["username"]
        assert cast.get("enum") == ["Lead"], f"the schema ignores the cast: {cast}"


def write_preflight_avatar(asset_root: Path) -> dict:
    """Write one tiny, real OBJ avatar so browser preflight exercises sceneReady rigging."""
    user_id = "preflight-avatar"
    avatar_dir = asset_root / user_id
    avatar_dir.mkdir(parents=True, exist_ok=True)
    parts = [
        ("Head", (0, 5.55, 0), (0.72, 0.72, 0.72)),
        ("Torso", (0, 3.55, 0), (1.05, 1.75, 0.58)),
        ("LeftArm", (-1.0, 3.7, 0), (0.4, 1.4, 0.4)),
        ("RightArm", (1.0, 3.7, 0), (0.4, 1.4, 0.4)),
        ("LeftLeg", (-0.35, 1.3, 0), (0.5, 2.4, 0.6)),
        ("RightLeg", (0.35, 1.3, 0), (0.5, 2.4, 0.6)),
    ]
    corners = [(-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
               (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]
    faces = [(0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1),
             (3, 2, 6, 7), (0, 3, 7, 4), (1, 5, 6, 2)]
    obj = ["mtllib avatar.mtl"]
    base = 1
    for name, center, size in parts:
        obj.extend((f"o {name}", "usemtl PreflightAvatar"))
        for signs in corners:
            vertex = [center[axis] + signs[axis] * size[axis] / 2 for axis in range(3)]
            obj.append("v " + " ".join(f"{value:.4f}" for value in vertex))
        for face in faces:
            obj.append("f " + " ".join(str(base + index) for index in face))
        base += len(corners)
    (avatar_dir / "avatar.obj").write_text("\n".join(obj) + "\n", encoding="utf-8")
    (avatar_dir / "avatar.mtl").write_text(
        "newmtl PreflightAvatar\nKd 0.26 0.68 0.34\nKa 0.12 0.12 0.12\n"
        "Ks 0.08 0.08 0.08\nNs 12\n", encoding="utf-8")
    return {
        "username": "PreflightLead", "user_id": user_id, "model_ready": True,
        "model_file": "avatar.obj", "model_format": "obj",
        "model_source": "preflight-fixture", "front_direction": [0, 0, 1],
        "thumbnail_ready": False,
    }


def render_frame():
    """Start Chromium, rig a synthetic R15 avatar, then load the real page and capture a frame."""
    node = shutil.which("node")
    assert node, "node is not installed"
    # A representative world, not a single grey box. The colour audit measures
    # this frame and refuses a colourless world, so the sample it measures has to
    # look like the thing it is standing in for: grass, a painted hall, a
    # terracotta roof, a lamp and a bright prop.
    plan = {
        "name": "Preflight World",
        "theme": "A small sunlit town square: grass, a painted hall, a tiled roof and a lamp.",
        "ground_color": [126, 182, 120],
        "ambient_color": [186, 210, 238],
        "props": [
            {"name": "Preflight Ground", "model": "ground", "shape": "Block", "material": "Grass",
             "position": [0, -0.5, 0], "size": [120, 1, 120], "color": [126, 182, 120],
             "physics": "static"},
            {"name": "Preflight Hall", "model": "hall", "shape": "Block", "material": "Brick",
             "position": [0, 6, 0], "size": [26, 12, 18], "color": [186, 150, 120],
             "physics": "static"},
            {"name": "Preflight Roof", "model": "roof", "shape": "Wedge", "material": "Slate",
             "position": [0, 14, 0], "size": [28, 5, 20], "color": [196, 104, 74],
             "physics": "static"},
            {"name": "Preflight Tree", "model": "tree", "shape": "Ball", "material": "Grass",
             "position": [-16, 8, 6], "size": [9, 9, 9], "color": [74, 148, 66],
             "physics": "static"},
            {"name": "Preflight Lamp", "model": "lamp", "shape": "Cylinder", "material": "Neon",
             "position": [12, 6, 6], "size": [1, 12, 1], "color": [255, 226, 156],
             "light": {"color": [255, 226, 156], "brightness": 2.0, "range": 30},
             "physics": "static"},
            {"name": "Preflight Bench", "model": "bench", "shape": "Block", "material": "Wood",
             "position": [8, 2, 10], "size": [6, 2, 2], "color": [120, 82, 50],
             "physics": "static"},
        ],
        "character_placements": [
            {"username": "PreflightLead", "role": "lead", "position": [0, 0, 24]},
        ],
        "camera_shots": [], "face_expressions": [],
    }
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        map_path = work / "map.json"
        map_path.write_text(json.dumps(plan), encoding="utf-8")
        profile = write_preflight_avatar(work / "dist" / "avatar-assets")
        profiles_path = work / "profiles.json"
        profiles_path.write_text(json.dumps([profile]), encoding="utf-8")
        result = subprocess.run([node, str(RENDERER / "render_short.mjs"),
                                 "--map", str(map_path), "--profiles", str(profiles_path), "--preflight"],
                                capture_output=True, text=True, cwd=work, timeout=600)
        combined = result.stdout + result.stderr
        assert result.returncode == 0, explain(combined)
        assert "Render preflight avatar check: 1/1 synthetic avatar(s) rigged" in result.stdout, explain(combined)
        assert "Render preflight passed" in result.stdout, explain(combined)


def render_room_frame():
    """Render a REAL indoor scene built by the real builder, at the start of the run.

    Run #109 spent three hours building a bedroom story and then rendered an open
    field: no room, no walls, just outside. This check builds the same kind of room
    the run will build (through tools/build_story_map.py), loads it in Chromium and
    asks the renderer to prove every camera stays inside the walls. If anything in
    that path is broken, the run dies here - in the first minutes - instead of after
    the render.
    """
    node = shutil.which("node")
    assert node, "node is not installed"
    response = {
        "message": {"content": json.dumps({
            "name": "Preflight Bedroom", "theme": "A cramped bedroom at night",
            "ground_material": "Wood", "ground_color": [150, 190, 225],
            "ambient_color": [190, 200, 215],
            "props": [
                {"name": "Bed", "model": "furniture", "shape": "Block", "material": "Wood",
                 "position": [-10, 1.5, 30], "size": [6, 3, 7], "color": [200, 160, 120],
                 "physics": "static"},
                {"name": "Desk", "model": "furniture", "shape": "Block", "material": "Wood",
                 "position": [12, 1.5, 32], "size": [4, 3, 2], "color": [190, 150, 110],
                 "physics": "static"},
                {"name": "Chair", "model": "furniture", "shape": "Block", "material": "Wood",
                 "position": [12, 1, 29], "size": [2, 2, 2], "color": [170, 130, 95],
                 "physics": "static"},
                {"name": "Wardrobe", "model": "furniture", "shape": "Block", "material": "Wood",
                 "position": [-13, 4, 40], "size": [4, 8, 2], "color": [150, 110, 80],
                 "physics": "static"},
                {"name": "Lamp", "model": "lamp", "shape": "Cylinder", "material": "Neon",
                 "position": [14, 4, 40], "size": [1, 5, 1], "color": [255, 230, 180],
                 "physics": "static"},
                {"name": "Bookshelf", "model": "shelf", "shape": "Block", "material": "Wood",
                 "position": [8, 4, 40], "size": [4, 8, 1.5], "color": [160, 120, 90],
                 "physics": "static"},
                {"name": "Plant", "model": "plant", "shape": "Cylinder", "material": "Wood",
                 "position": [15, 2, 26], "size": [2, 4, 2], "color": [90, 160, 90],
                 "physics": "static"},
                {"name": "Nightstand", "model": "furniture", "shape": "Block", "material": "Wood",
                 "position": [-14, 1, 30], "size": [2, 2, 2], "color": [180, 140, 100],
                 "physics": "static"},
            ],
            "character_placements": [
                {"username": "PreflightLead", "role": "lead", "position": [0, 0, 24]},
                {"username": "PreflightFriend", "role": "supporting", "position": [-6, 0, 24]},
            ],
            "camera_shots": [
                {"time": 0, "position": [0, 75, 170], "target": [0, 3, 24],
                 "focus_username": "PreflightLead", "transition": "smooth", "framing": "auto"},
                {"time": 15, "position": [3, 6, 30], "target": [0, 5, 24],
                 "focus_username": "PreflightFriend", "transition": "snap", "framing": "face",
                 "face_distance": 2.6},
                {"time": 30, "position": [0, 10, 44], "target": [0, 4, 24],
                 "focus_username": "PreflightLead", "transition": "smooth", "framing": "wide"},
            ],
            "face_expressions": [
                {"time": 1, "expression": "neutral", "intensity": 0.6, "username": "PreflightLead"},
                {"time": 20, "expression": "happy", "intensity": 1, "username": "PreflightFriend"},
                {"time": 29, "expression": "worried", "intensity": 0.8, "username": "PreflightLead"},
            ],
            "search_queries": [],
        })}
    }
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        source = work / "response.json"
        source.write_text(json.dumps(response), encoding="utf-8")
        cast = work / "cast.json"
        cast.write_text(json.dumps(["PreflightLead", "PreflightFriend"]), encoding="utf-8")
        world = work / "room.json"
        built = subprocess.run([sys.executable, str(ROOT / "tools" / "build_story_map.py"),
                                str(source), str(world), "40", "--json-only", "--strict",
                                "--min-props", "8", "--target-props", "1260",
                                "--usernames", str(cast),
                                "--story-topic", "two brothers in a cramped bedroom"],
                               capture_output=True, text=True, cwd=ROOT, timeout=300)
        assert built.returncode == 0, explain(built.stderr or built.stdout, 6)
        plan = json.loads(world.read_text(encoding="utf-8"))
        assert plan.get("interior"), "the bedroom story was not built as a room"
        names = " ".join(part["name"] for part in plan["props"])
        for needed in ("Room Floor", "Room Ceiling", "Room Wall", "Room Door"):
            assert needed in names, f"the built room has no {needed}"
        result = subprocess.run([node, str(RENDERER / "render_short.mjs"),
                                 "--map", str(world), "--preflight"],
                                capture_output=True, text=True, cwd=ROOT, timeout=600)
        combined = result.stdout + result.stderr
        assert result.returncode == 0, explain(combined)
        assert "Render preflight room check" in result.stdout, explain(combined)
        assert "camera positions all inside" in result.stdout, explain(combined)
        assert "Render preflight interior check:" in result.stdout, explain(combined)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--render", action="store_true",
                        help="also load the page in Chromium and capture a frame")
    args = parser.parse_args()
    print("Preflight: checking the pipeline before the AI starts", flush=True)
    check("python sources compile", python_sources)
    check("ffmpeg, node and npm are installed", binaries)
    check("renderer scripts parse", renderer_syntax)
    check("page template builds", page_template)
    check("renderer npm modules are installed", renderer_modules)
    check("world-plan schema builds", plan_schema)
    if args.render:
        check("renderer loads the page and captures a frame", render_frame)
        check("renderer builds a real room and keeps every camera inside it",
              render_room_frame)
    if FAILURES:
        print(f"\nPreflight failed in {len(FAILURES)} check(s):", flush=True)
        for item in FAILURES:
            print(f"  - {item}", flush=True)
        print("Fix these before the AI spends an hour on the run.", flush=True)
        return 1
    print("\nPreflight passed: the tools and the renderer are ready.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
