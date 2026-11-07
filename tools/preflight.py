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


def check(label: str, fn) -> None:
    try:
        fn()
        ok(label)
    except AssertionError as exc:
        fail(f"{label}: {exc}")
    except Exception as exc:  # noqa: BLE001 - any breakage is a failure to report
        fail(f"{label}: {type(exc).__name__}: {exc}")


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
        assert result.returncode == 0, f"{script.name}: {result.stderr.strip().splitlines()[:1]}"


def page_template():
    node = shutil.which("node")
    assert node, "node is not installed"
    result = subprocess.run([node, str(RENDERER / "template_check.mjs")],
                            capture_output=True, text=True, cwd=RENDERER)
    assert result.returncode == 0, (result.stderr or result.stdout).strip().splitlines()[-1]


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
        assert result.returncode == 0, (result.stderr or result.stdout).strip().splitlines()[-1]
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
    plan = {
        "name": "Preflight World",
        "theme": "A plain preflight scene.",
        "props": [{"name": "Preflight Hall", "model": "hall", "shape": "Block", "material": "Brick",
                   "position": [0, 0, 0], "size": [20, 12, 16], "color": [150, 160, 175],
                   "physics": "static"}],
        "character_placements": [], "camera_shots": [], "face_expressions": [],
    }
    with tempfile.TemporaryDirectory() as tmp:
        map_path = Path(tmp) / "map.json"
        map_path.write_text(json.dumps(plan), encoding="utf-8")
        result = subprocess.run([node, str(RENDERER / "render_short.mjs"),
                                 "--map", str(map_path), "--preflight"],
                                capture_output=True, text=True, cwd=ROOT, timeout=600)
        tail = (result.stdout + result.stderr).strip().splitlines()[-1:] or ["no output"]
        assert result.returncode == 0, tail[0]
        assert "Render preflight passed" in result.stdout, tail[0]


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
