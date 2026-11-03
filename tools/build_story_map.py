#!/usr/bin/env python3
"""Validate an AI map layout and emit a runnable Roblox Studio Lua map builder."""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

MATERIALS = {"Plastic", "SmoothPlastic", "Concrete", "Grass", "Slate", "Wood", "Metal", "Neon", "Glass", "Brick", "Asphalt"}
SHAPES = {"Block", "Ball", "Cylinder"}


def default_plan():
    return {
        "name": "Neon City Plaza",
        "theme": "A bright daytime Roblox city plaza with colorful shops, trees, and a central showcase stage.",
        "ground_color": [88, 166, 91],
        "ambient_color": [185, 205, 225],
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
                           or not -300 <= v <= 300 for v in vector)):
                return default_camera_shots(duration)
        if not isinstance(transition, str) or transition not in {"smooth", "snap"}:
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


def default_character_placements(usernames):
    positions = [[0, 0, 24], [-3, 0, 24], [3, 0, 24], [-6, 0, 29], [6, 0, 29], [0, 0, 34]]
    return [
        {"username": name, "role": "lead" if index == 0 else "supporting", "position": positions[index]}
        for index, name in enumerate(usernames[:6])
    ]


def normalize_character_placements(raw, usernames):
    if not usernames:
        return []
    defaults = default_character_placements(usernames)
    by_name = {}
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict) or not isinstance(item.get("username"), str):
                continue
            name = item["username"].casefold()
            pos = item.get("position")
            if (name not in {n.casefold() for n in usernames}
                    or not isinstance(pos, list) or len(pos) != 3
                    or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in pos)
                    or not -8 <= pos[0] <= 8 or not 0 <= pos[1] <= 3 or not 12 <= pos[2] <= 38):
                continue
            by_name[name] = [round(float(v), 2) for v in pos]
    placements = []
    for index, default in enumerate(defaults):
        name = default["username"]
        placements.append({
            "username": name,
            "role": "lead" if index == 0 else "supporting",
            "position": by_name.get(name.casefold(), default["position"]),
        })
    return placements


def validate(plan, duration=90, usernames=(), min_props=16):
    if not isinstance(plan, dict):
        raise ValueError("map plan must be an object")
    props = plan.get("props")
    if not isinstance(props, list) or len(props) < min_props:
        raise ValueError(f"map must contain at least {min_props} detailed props; there is no fixed upper cap")
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
    unique_prop_names = set()
    for index, prop in enumerate(props):
        if not isinstance(prop, dict):
            raise ValueError("every map prop must be an object")
        shape = prop.get("shape", "Block")
        material = prop.get("material", "SmoothPlastic")
        pos, size = prop.get("position"), prop.get("size")
        if not isinstance(shape, str) or shape not in SHAPES or not isinstance(material, str) or material not in MATERIALS:
            raise ValueError("map prop has an unsupported shape or material")
        if (not isinstance(pos, list) or len(pos) != 3
                or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not -250 <= v <= 250 for v in pos)):
            raise ValueError("prop position must be three coordinates from -250 to 250")
        if (not isinstance(size, list) or len(size) != 3
                or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not 0.5 <= v <= 120 for v in size)):
            raise ValueError("prop size must be three dimensions from 0.5 to 120")
        if abs(pos[0]) + size[0] / 2 > 320 or abs(pos[2]) + size[2] / 2 > 320:
            raise ValueError("prop footprint must fit on the 640-stud world platform")
        prop_name = prop.get("name", f"Map Prop {index + 1}")
        if not isinstance(prop_name, str):
            prop_name = f"Map Prop {index + 1}"
        prop_name = re.sub(r"[^A-Za-z0-9 _-]", "", prop_name).strip()[:40] or f"Map Prop {index + 1}"
        name_key = prop_name.casefold()
        if name_key in unique_prop_names:
            raise ValueError(f"map prop names must be unique: {prop_name!r}")
        unique_prop_names.add(name_key)
        clean_props.append({
            "name": prop_name, "shape": shape, "material": material,
            "position": [round(float(v), 2) for v in pos],
            "size": [round(float(v), 2) for v in size],
            "color": color(prop.get("color"), [120, 145, 180]),
        })
    return {
        "name": name, "theme": theme,
        "ground_color": color(plan.get("ground_color"), [88, 166, 91]),
        "ground_material": plan.get("ground_material") if isinstance(plan.get("ground_material"), str) and plan.get("ground_material") in MATERIALS else "Grass",
        "ambient_color": color(plan.get("ambient_color"), [185, 205, 225]),
        "props": clean_props,
        "camera_shots": normalize_camera_shots(plan.get("camera_shots"), duration),
        "character_placements": normalize_character_placements(plan.get("character_placements"), usernames),
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
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("duration", type=float)
    parser.add_argument("--json-only", action="store_true")
    parser.add_argument("--strict", action="store_true", help="fail instead of silently substituting the fallback map")
    parser.add_argument("--min-props", type=int, default=16, help="minimum AI-authored props required")
    parser.add_argument("--usernames", type=Path, help="JSON file containing the ordered Roblox cast")
    args = parser.parse_args()
    source, destination, duration = args.source, args.destination, args.duration
    json_only = args.json_only
    usernames = json.loads(args.usernames.read_text(encoding="utf-8")) if args.usernames else []
    if not isinstance(usernames, list) or any(not isinstance(name, str) for name in usernames):
        raise SystemExit("usernames file must be a JSON array of strings")
    if not 30 <= duration <= 60:
        raise SystemExit("duration must be 30 to 60 seconds")
    try:
        raw_plan = decode_response(source)
        if args.strict and (not isinstance(raw_plan, dict) or not isinstance(raw_plan.get("theme"), str) or not raw_plan["theme"].strip()):
            raise ValueError("AI map must include a non-empty prompt-specific theme description")
        plan = validate(raw_plan, duration, usernames, args.min_props)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        if args.strict:
            raise SystemExit(f"Invalid AI map plan: {exc}") from exc
        print(f"Invalid AI map plan ({exc}); using the complete fallback map.", file=sys.stderr)
        plan = validate(default_plan(), duration, usernames)
    json_path = destination if json_only else destination.with_suffix(".json")
    if not json_only:
        emit_lua(plan, destination)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    print(f"Created map data {json_path}: {plan['name']} with {len(plan['props'])} 3D props.")


if __name__ == "__main__":
    main()
