#!/usr/bin/env python3
"""Validate an AI map layout and emit a runnable Roblox Studio Lua map builder."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

MATERIALS = {"Plastic", "SmoothPlastic", "Concrete", "Grass", "Slate", "Wood", "Metal", "Neon", "Glass", "Brick", "Asphalt"}
SHAPES = {"Block", "Ball", "Cylinder"}


def default_plan():
    return {
        "name": "Neon City Plaza",
        "theme": "A colorful night-time Roblox city plaza with a central showcase stage.",
        "ground_color": [37, 47, 65],
        "ambient_color": [135, 155, 205],
        "props": [
            {"name": "North Tower", "shape": "Block", "material": "Glass", "position": [-55, 20, -58], "size": [24, 40, 24], "color": [65, 100, 160]},
            {"name": "South Tower", "shape": "Block", "material": "Glass", "position": [58, 25, -50], "size": [28, 50, 26], "color": [90, 75, 160]},
            {"name": "Arcade", "shape": "Block", "material": "Neon", "position": [-48, 7, 4], "size": [24, 14, 20], "color": [25, 205, 220]},
            {"name": "Cafe", "shape": "Block", "material": "Brick", "position": [48, 6, 12], "size": [22, 12, 24], "color": [255, 145, 85]},
            {"name": "Showcase Stage", "shape": "Block", "material": "SmoothPlastic", "position": [0, 1, -8], "size": [28, 2, 18], "color": [95, 80, 210]},
            {"name": "Cyan Sign", "shape": "Block", "material": "Neon", "position": [-48, 17, 4], "size": [18, 3, 1], "color": [35, 235, 255]},
            {"name": "Amber Sign", "shape": "Block", "material": "Neon", "position": [48, 15, 12], "size": [16, 3, 1], "color": [255, 190, 65]},
            {"name": "Tree One", "shape": "Cylinder", "material": "Wood", "position": [-28, 5, 43], "size": [3, 10, 3], "color": [110, 75, 45]},
            {"name": "Tree Crown One", "shape": "Ball", "material": "Grass", "position": [-28, 12, 43], "size": [11, 11, 11], "color": [60, 175, 105]},
            {"name": "Tree Two", "shape": "Cylinder", "material": "Wood", "position": [30, 5, 42], "size": [3, 10, 3], "color": [110, 75, 45]},
            {"name": "Tree Crown Two", "shape": "Ball", "material": "Grass", "position": [30, 12, 42], "size": [11, 11, 11], "color": [60, 175, 105]},
            {"name": "Blue Light Pillar", "shape": "Block", "material": "Neon", "position": [-18, 5, -25], "size": [1, 10, 1], "color": [45, 160, 255]},
            {"name": "Pink Light Pillar", "shape": "Block", "material": "Neon", "position": [18, 5, -25], "size": [1, 10, 1], "color": [255, 75, 195]},
            {"name": "Bench One", "shape": "Block", "material": "Wood", "position": [-18, 1.5, 30], "size": [10, 1, 3], "color": [145, 95, 55]},
            {"name": "Bench Two", "shape": "Block", "material": "Wood", "position": [18, 1.5, 30], "size": [10, 1, 3], "color": [145, 95, 55]},
            {"name": "Planter One", "shape": "Block", "material": "Concrete", "position": [-32, 1, 28], "size": [8, 2, 8], "color": [90, 105, 120]},
            {"name": "Planter Two", "shape": "Block", "material": "Concrete", "position": [34, 1, 29], "size": [8, 2, 8], "color": [90, 105, 120]},
            {"name": "Golden Orb", "shape": "Ball", "material": "Neon", "position": [0, 9, -8], "size": [5, 5, 5], "color": [255, 195, 65]},
        ],
    }


def default_camera_shots(duration):
    """A mix of smooth camera sweeps and story-beat snap cuts for the rendered short."""
    beats = [0, .16, .32, .48, .64, .80, 1.0]
    views = [
        ([0, 32, 76], [0, 3, 24], "smooth"),
        ([-16, 12, 48], [0, 3, 24], "smooth"),
        ([18, 10, 38], [8, 4, 24], "snap"),
        ([22, 14, 10], [0, 3, 24], "smooth"),
        ([-10, 8, 38], [0, 3, 24], "snap"),
        ([8, 10, 54], [0, 3, 24], "smooth"),
        ([0, 28, 84], [0, 3, 24], "smooth"),
    ]
    return [
        {"time": round(duration * ratio, 2), "position": pos, "target": target, "transition": mode}
        for ratio, (pos, target, mode) in zip(beats, views)
    ]


def normalize_camera_shots(shots, duration):
    if not isinstance(shots, list) or not 4 <= len(shots) <= 12:
        return default_camera_shots(duration)
    clean, previous = [], -1.0
    for shot in shots:
        if not isinstance(shot, dict):
            return default_camera_shots(duration)
        time, pos, target = shot.get("time"), shot.get("position"), shot.get("target")
        transition = shot.get("transition", "smooth")
        if (isinstance(time, bool) or not isinstance(time, (int, float))
                or not 0 <= time <= duration or time <= previous):
            return default_camera_shots(duration)
        for vector in (pos, target):
            if (not isinstance(vector, list) or len(vector) != 3
                    or any(isinstance(v, bool) or not isinstance(v, (int, float))
                           or not -120 <= v <= 120 for v in vector)):
                return default_camera_shots(duration)
        if transition not in {"smooth", "snap"}:
            transition = "smooth"
        clean.append({
            "time": round(float(time), 2),
            "position": [round(float(v), 2) for v in pos],
            "target": [round(float(v), 2) for v in target],
            "transition": transition,
        })
        previous = time
    if clean[0]["time"] != 0:
        clean.insert(0, default_camera_shots(duration)[0])
    if clean[-1]["time"] < duration:
        last = dict(clean[-1])
        last["time"] = float(duration)
        last["transition"] = "smooth"
        clean.append(last)
    return clean


def decode_response(path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    response = payload.get("response", "") if isinstance(payload, dict) else ""
    try:
        plan = json.loads(response)
    except (json.JSONDecodeError, TypeError):
        plan = {}
    return plan


def validate(plan, duration=90):
    if not isinstance(plan, dict):
        raise ValueError("map plan must be an object")
    props = plan.get("props")
    if not isinstance(props, list) or not 10 <= len(props) <= 36:
        raise ValueError("map must contain 10 to 36 props")
    name = plan.get("name", "Roblox Story Map")
    if not isinstance(name, str):
        name = "Roblox Story Map"
    name = re.sub(r"[^A-Za-z0-9 _-]", "", name).strip()[:50] or "Roblox Story Map"
    theme = plan.get("theme", "A colorful Roblox story environment.")
    if not isinstance(theme, str):
        theme = "A colorful Roblox story environment."
    theme = re.sub(r"[\r\n]+", " ", theme)[:180]

    def color(value, default):
        if (not isinstance(value, list) or len(value) != 3
                or any(isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 255 for v in value)):
            return default
        return value

    clean_props = []
    for index, prop in enumerate(props):
        if not isinstance(prop, dict):
            raise ValueError("every map prop must be an object")
        shape = prop.get("shape", "Block")
        material = prop.get("material", "SmoothPlastic")
        pos, size = prop.get("position"), prop.get("size")
        if shape not in SHAPES or material not in MATERIALS:
            raise ValueError("map prop has an unsupported shape or material")
        if (not isinstance(pos, list) or len(pos) != 3
                or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not -85 <= v <= 85 for v in pos)):
            raise ValueError("prop position must be three coordinates from -85 to 85")
        if (not isinstance(size, list) or len(size) != 3
                or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not 0.5 <= v <= 60 for v in size)):
            raise ValueError("prop size must be three dimensions from 0.5 to 60")
        if abs(pos[0]) + size[0] / 2 > 89 or abs(pos[2]) + size[2] / 2 > 89:
            raise ValueError("prop footprint must fit on the walkable map platform")
        prop_name = prop.get("name", f"Map Prop {index + 1}")
        if not isinstance(prop_name, str):
            prop_name = f"Map Prop {index + 1}"
        prop_name = re.sub(r"[^A-Za-z0-9 _-]", "", prop_name).strip()[:40] or f"Map Prop {index + 1}"
        clean_props.append({
            "name": prop_name, "shape": shape, "material": material,
            "position": [round(float(v), 2) for v in pos],
            "size": [round(float(v), 2) for v in size],
            "color": color(prop.get("color"), [120, 145, 180]),
        })
    return {
        "name": name, "theme": theme,
        "ground_color": color(plan.get("ground_color"), [50, 60, 75]),
        "ambient_color": color(plan.get("ambient_color"), [145, 160, 195]),
        "props": clean_props,
        "camera_shots": normalize_camera_shots(plan.get("camera_shots"), duration),
    }


def lua_string(value):
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


def emit_lua(plan, output):
    lines = [
        "-- Generated Roblox 3D map. Run this file from Roblox Studio's Command Bar.",
        "local Workspace = game:GetService('Workspace')",
        "local Lighting = game:GetService('Lighting')",
        "local previous = Workspace:FindFirstChild('GeneratedStoryMap')",
        "if previous then previous:Destroy() end",
        "local map = Instance.new('Model')",
        "map.Name = 'GeneratedStoryMap'",
        f"map:SetAttribute('DisplayName', {lua_string(plan['name'])})",
        "map.Parent = Workspace",
        "local function makePart(name, size, position, color, material, shape)",
        "    local p = Instance.new('Part')",
        "    p.Name = name",
        "    p.Anchored = true",
        "    p.Size = Vector3.new(size[1], size[2], size[3])",
        "    local transform = CFrame.new(position[1], position[2], position[3])",
        "    if shape == 'Cylinder' then transform = transform * CFrame.Angles(0, 0, math.rad(90)) end",
        "    p.CFrame = transform",
        "    p.Color = Color3.fromRGB(color[1], color[2], color[3])",
        "    p.Material = Enum.Material[material]",
        "    p.Shape = Enum.PartType[shape]",
        "    p.TopSurface = Enum.SurfaceType.Smooth",
        "    p.BottomSurface = Enum.SurfaceType.Smooth",
        "    p.Parent = map",
        "    return p",
        "end",
        "-- Safe walkable floor and central asphalt avenue.",
        f"makePart('Story Map Ground', {{180, 2, 180}}, {{0, -1, 0}}, {{{plan['ground_color'][0]}, {plan['ground_color'][1]}, {plan['ground_color'][2]}}}, 'Grass', 'Block')",
        "makePart('Central Avenue', {14, 0.12, 150}, {0, 0.08, 0}, {42, 45, 55}, 'Asphalt', 'Block')",
        "makePart('West Sidewalk', {7, 0.16, 150}, {-10.5, 0.1, 0}, {175, 180, 190}, 'Concrete', 'Block')",
        "makePart('East Sidewalk', {7, 0.16, 150}, {10.5, 0.1, 0}, {175, 180, 190}, 'Concrete', 'Block')",
        "-- Dashed lane markings add depth and make the path easy to read.",
        "for z = -68, 68, 14 do makePart('Lane Marking', {0.45, 0.08, 5}, {0, 0.18, z}, {245, 215, 115}, 'Neon', 'Block') end",
        "-- Story-specific buildings, props, and set dressing.",
    ]
    for prop in plan["props"]:
        pos = ", ".join(map(str, prop["position"]))
        size = ", ".join(map(str, prop["size"]))
        color = ", ".join(map(str, prop["color"]))
        lines.append(
            f"makePart({lua_string(prop['name'])}, {{{size}}}, {{{pos}}}, {{{color}}}, "
            f"{lua_string(prop['material'])}, {lua_string(prop['shape'])})"
        )
    ambient = plan["ambient_color"]
    lines.extend([
        "-- Give the scene a polished evening look without external assets.",
        "Lighting.ClockTime = 17.5",
        "Lighting.Brightness = 2",
        f"Lighting.Ambient = Color3.fromRGB({ambient[0]}, {ambient[1]}, {ambient[2]})",
        f"Lighting.OutdoorAmbient = Color3.fromRGB({ambient[0]}, {ambient[1]}, {ambient[2]})",
        "local atmosphere = Lighting:FindFirstChildOfClass('Atmosphere')",
        "if not atmosphere then atmosphere = Instance.new('Atmosphere'); atmosphere.Parent = Lighting end",
        "atmosphere.Density = 0.22",
        "atmosphere.Offset = 0.1",
        f"print('Built {lua_string(plan['name'])} with {len(plan['props'])} story props in Workspace.')",
    ])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    if len(sys.argv) != 4:
        raise SystemExit("usage: build_story_map.py OLLAMA_RESPONSE.json OUTPUT.lua DURATION_SECONDS")
    source, destination = map(Path, sys.argv[1:3])
    duration = float(sys.argv[3])
    if not 60 <= duration <= 120:
        raise SystemExit("duration must be 60 to 120 seconds")
    try:
        plan = validate(decode_response(source), duration)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Invalid AI map plan ({exc}); using a complete Roblox city-plaza map.", file=sys.stderr)
        plan = validate(default_plan(), duration)
    emit_lua(plan, destination)
    destination.with_suffix(".json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    print(f"Created {destination}: {plan['name']} with {len(plan['props'])} 3D props.")


if __name__ == "__main__":
    main()
