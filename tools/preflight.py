#!/usr/bin/env python3
"""Check the whole pipeline in the first two minutes, not at the last step.

Every expensive failure this workflow has had landed at the end of an hour -
after the model download, the story, the world plan and the narration - because
nothing proved the *tools* worked until they were needed:

* a backtick inside the renderer's HTML template, which only surfaced when
  buildHtml() ran;
* a missing npm module, which only surfaced when Chromium loaded the page;
* a renderer that needed a GPU flag, which only surfaced at the first frame.

This script runs those checks up front and fails fast, with a message naming the
broken thing. It is deliberately stdlib-only, so it works before any pip install.

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


def render_frame():
    """Start Chromium, load the real page and capture one frame."""
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
        "character_placements": [], "camera_shots": [], "face_expressions": [],
    }
    with tempfile.TemporaryDirectory() as tmp:
        map_path = Path(tmp) / "map.json"
        map_path.write_text(json.dumps(plan), encoding="utf-8")
        result = subprocess.run([node, str(RENDERER / "render_short.mjs"),
                                 "--map", str(map_path), "--preflight"],
                                capture_output=True, text=True, cwd=ROOT, timeout=600)
        combined = result.stdout + result.stderr
        assert result.returncode == 0, explain(combined)
        assert "Render preflight passed" in result.stdout, explain(combined)


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
