#!/usr/bin/env python3
"""Repeatedly review and re-align a generated story map.

The AI blueprint is written in one shot, so it always contains a few parts that
overlap, drift off the grid, sit in the cast lane, or are too dark to read. This
tool is the "look at it again" pass: it runs the same deterministic review over
the whole world several times and reports every correction it made, so the
rendered MP4 and the Studio place use one clean, aligned, brightly lit world.

Usage:
    python tools/realign_story_map.py dist/Roblox_Story_Map.json --passes 3
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

GRID = 0.5
MIN_LUMINANCE = 104
MAX_SPAN = 64.0
PLATFORM = 320.0
# The cast acts in this lane; nothing tall may be built here or it will cross the lens.
CAST_LANE = {"x": 20.0, "z_min": 4.0, "z_max": 54.0, "headroom": 8.5}
DEFAULT_CAST_POSITIONS = [[0, 0, 24], [-3, 0, 24], [3, 0, 24], [-6, 0, 29], [6, 0, 29], [0, 0, 34]]


def snap(value, low, high, step=GRID):
    """Clamp into range and snap onto the grid so parts line up exactly."""
    return round(min(high, max(low, round(float(value) / step) * step)), 2)


def brighten(color):
    rgb = [max(0, min(255, int(channel))) for channel in color]
    luminance = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
    if luminance >= MIN_LUMINANCE:
        return rgb
    blend = min(1.0, (MIN_LUMINANCE - luminance) / MIN_LUMINANCE)
    target = [176, 186, 200]
    return [round(channel * (1 - blend * 0.9) + target[i] * (blend * 0.9))
            for i, channel in enumerate(rgb)]


def camera_clear(position, size):
    """True when a part would sit in front of the camera or cross the cast lane."""
    x, y, z = position
    sx, sy, sz = size
    half_height = sy / 2
    if max(sx, sy, sz) > MAX_SPAN:
        return False
    blocks_cast = y - half_height < CAST_LANE["headroom"] and y + half_height > 2
    in_lane = abs(x) < CAST_LANE["x"] and CAST_LANE["z_min"] - 2 < z < CAST_LANE["z_max"] + 2
    return not (blocks_cast and in_lane)


def overlaps(a, b):
    """Axis-aligned overlap with a small tolerance so touching faces are allowed."""
    for axis in (0, 2):
        gap = abs(a["position"][axis] - b["position"][axis])
        if gap >= (a["size"][axis] + b["size"][axis]) / 2 - 0.05:
            return False
    low = min(a["position"][1] - a["size"][1] / 2, b["position"][1] - b["size"][1] / 2)
    high = max(a["position"][1] + a["size"][1] / 2, b["position"][1] + b["size"][1] / 2)
    return high - low < (a["size"][1] + b["size"][1]) / 2 * 1.35


def unique_name(name, used):
    cleaned = re.sub(r"[^A-Za-z0-9 _-]", "", str(name)).strip()[:40] or "Story Detail"
    if cleaned.casefold() not in used:
        used.add(cleaned.casefold())
        return cleaned
    index = 2
    while True:
        tail = f" {index}"
        candidate = cleaned[: 40 - len(tail)] + tail
        if candidate.casefold() not in used:
            used.add(candidate.casefold())
            return candidate
        index += 1


def review_pass(plan, report):
    """One full review of the world. Returns a corrected plan."""
    props = [prop for prop in plan.get("props", []) if isinstance(prop, dict)]
    used_names: set[str] = set()
    kept = []
    for prop in props:
        try:
            position = [snap(prop["position"][0], -250, 250),
                        snap(prop["position"][1], 0.25, 250, GRID / 2),
                        snap(prop["position"][2], -250, 250)]
            size = [snap(value, 0.5, MAX_SPAN) for value in prop["size"]]
        except (KeyError, IndexError, TypeError, ValueError):
            report["dropped_invalid_parts"] += 1
            continue
        if abs(position[0]) + size[0] / 2 > PLATFORM or abs(position[2]) + size[2] / 2 > PLATFORM:
            report["dropped_off_platform_parts"] += 1
            continue
        if not camera_clear(position, size):
            report["dropped_camera_blockers"] += 1
            continue
        candidate = {**prop, "position": position, "size": size,
                     "color": brighten(prop.get("color") or [150, 165, 190])}
        if any(overlaps(candidate, other) for other in kept[-60:]):
            report["dropped_overlapping_parts"] += 1
            continue
        candidate["name"] = unique_name(prop.get("name", ""), used_names)
        kept.append(candidate)
    report["passed_parts"] = len(kept)

    # Keep the cast standing on clean paving and out of any solid geometry.
    placements = plan.get("character_placements") or []
    for index, person in enumerate(placements):
        fallback = DEFAULT_CAST_POSITIONS[index % len(DEFAULT_CAST_POSITIONS)]
        try:
            position = person.get("position") or fallback
            x = snap(position[0], -16, 16)
            z = snap(position[2], CAST_LANE["z_min"] + 2, CAST_LANE["z_max"] - 2)
        except (IndexError, TypeError, ValueError):
            x, z = fallback[0], fallback[2]
        person["position"] = [x, 0, z]
    for person in placements:
        for other in kept:
            if (abs(person["position"][0] - other["position"][0]) < other["size"][0] / 2 + 2.5
                    and abs(person["position"][2] - other["position"][2]) < other["size"][2] / 2 + 2.5
                    and other["position"][1] - other["size"][1] / 2 < 3):
                other["hazard"] = True
    kept = [prop for prop in kept if not prop.get("hazard")]
    for prop in kept:
        prop.pop("hazard", None)

    plan = {**plan, "props": kept, "character_placements": placements}
    plan["ground_color"] = brighten(plan.get("ground_color") or [126, 182, 120])
    plan["ambient_color"] = brighten(plan.get("ambient_color") or [190, 210, 235])
    report["world_parts"] = len(kept)
    return plan


def clean_camera_shots(plan, report):
    """Every shot must look at a real character and keep the camera out of geometry."""
    shots = plan.get("camera_shots") or []
    placements = plan.get("character_placements") or []
    names = [str(person.get("username", "")) for person in placements]
    solids = [prop for prop in plan.get("props", [])
              if prop.get("physics") != "dynamic" and prop["size"][1] >= 2.5]
    duration = float(plan.get("duration") or (shots[-1]["time"] if shots else 30.0))
    fixed = []
    for index, shot in enumerate(shots):
        try:
            target = [float(value) for value in shot["target"]]
            position = [float(value) for value in shot["position"]]
        except (KeyError, TypeError, ValueError):
            report["dropped_invalid_shots"] += 1
            continue
        focus = str(shot.get("focus_username", ""))
        if focus not in names:
            focus = names[index % len(names)] if names else "world"
        if focus in names:
            person = placements[names.index(focus)]
            target = [person["position"][0], 4.0, person["position"][2]]
        position[1] = max(4.0, position[1])
        # Pull the camera back/up if it would sit inside a wall.
        for _ in range(8):
            inside = any(
                abs(position[0] - prop["position"][0]) <= prop["size"][0] / 2 + 2.5
                and abs(position[1] - prop["position"][1]) <= prop["size"][1] / 2 + 2.5
                and abs(position[2] - prop["position"][2]) <= prop["size"][2] / 2 + 2.5
                for prop in solids
            )
            if not inside:
                break
            direction = [position[0] - target[0], position[2] - target[2]]
            length = math.hypot(*direction) or 1.0
            position[0] += direction[0] / length * 2.0
            position[2] += direction[1] / length * 2.0
            position[1] += 1.5
            report["lifted_camera_shots"] += 1
        if not shot.get("transition") in {"smooth", "snap"}:
            shot["transition"] = "smooth"
        fixed.append({"time": round(min(duration, float(shot.get("time", 0))), 2),
                      "position": [round(value, 2) for value in position],
                      "target": [round(value, 2) for value in target],
                      "transition": shot["transition"], "focus_username": focus})
    if fixed:
        fixed[0]["time"] = 0.0
        fixed.sort(key=lambda item: item["time"])
        if fixed[-1]["time"] < duration:
            last = dict(fixed[-1])
            last["time"] = duration
            fixed.append(last)
    plan["camera_shots"] = fixed
    report["camera_shots"] = len(fixed)
    return plan


DECOR = [
    ("Plaza Planter", "Block", "Concrete", [4.0, 1.0, 4.0], [168, 178, 190]),
    ("Paving Slab", "Block", "Concrete", [6.0, 0.4, 6.0], [196, 202, 210]),
    ("Garden Bench Seat", "Block", "Wood", [5.0, 0.6, 1.6], [156, 110, 72]),
    ("Garden Lamp Post", "Cylinder", "Metal", [0.7, 5.0, 0.7], [120, 132, 150]),
    ("Lamp Glow", "Ball", "Neon", [1.2, 1.2, 1.2], [255, 232, 168]),
    ("Street Tree Trunk", "Block", "Wood", [1.2, 4.0, 1.2], [138, 100, 66]),
    ("Street Tree Crown", "Ball", "Grass", [5.0, 4.4, 5.0], [118, 190, 108]),
    ("Flower Bed", "Block", "Brick", [4.4, 0.5, 3.0], [206, 168, 140]),
    ("Flower Bloom", "Ball", "SmoothPlastic", [1.3, 1.2, 1.3], [244, 168, 196]),
    ("Market Crate", "Block", "Wood", [2.2, 1.8, 2.2], [176, 136, 92]),
    ("Plaza Fountain Rim", "Cylinder", "Concrete", [7.0, 1.2, 7.0], [190, 198, 208]),
    ("Plaza Fountain Water", "Cylinder", "Glass", [5.4, 0.5, 5.4], [150, 214, 240]),
]


def top_up(plan, target, report):
    """Add aligned decorative Parts until the reviewed world reaches its density target."""
    props = list(plan.get("props", []))
    if len(props) >= target:
        return plan
    used = {prop["name"].casefold() for prop in props}
    index = 0
    step = 8.0
    limit = 244.0
    z = 8.0
    while len(props) < target and z <= limit:
        x = -limit
        while len(props) < target and x <= limit:
            if (not (abs(x) < CAST_LANE["x"] + 4 and CAST_LANE["z_min"] - 4 < z < CAST_LANE["z_max"] + 4)):
                label, shape, material, size, color = DECOR[index % len(DECOR)]
                position = [snap(x, -250, 250), snap(size[1] / 2, 0.25, 250), snap(z, -250, 250)]
                candidate = {"name": label, "shape": shape, "material": material,
                             "position": position, "size": list(size),
                             "color": brighten(color), "physics": "static"}
                if camera_clear(position, size) and not any(overlaps(candidate, other) for other in props[-90:]):
                    candidate["name"] = unique_name(label, used)
                    props.append(candidate)
                    index += 1
            x += step
        z += step
    plan["props"] = props
    report["added_decor_parts"] = len(props)
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("map", type=Path)
    parser.add_argument("--passes", type=int, default=3, help="how many review/re-align passes to run")
    parser.add_argument("--report", type=Path, help="optional JSON report of every correction")
    parser.add_argument("--duration", type=float, help="short length in seconds (defaults to the plan)")
    parser.add_argument("--target-parts", type=int, default=0,
                        help="top up with aligned decorative Parts until the world reaches this size")
    args = parser.parse_args()

    plan = json.loads(args.map.read_text(encoding="utf-8"))
    if args.duration:
        plan["duration"] = float(args.duration)
    totals: dict[str, int] = {}
    history = []
    for index in range(max(1, args.passes)):
        report = {key: 0 for key in (
            "dropped_invalid_parts", "dropped_off_platform_parts", "dropped_camera_blockers",
            "dropped_overlapping_parts", "dropped_invalid_shots", "lifted_camera_shots", "added_decor_parts")}
        before = len(plan.get("props", []))
        plan = review_pass(plan, report)
        plan = clean_camera_shots(plan, report)
        if args.target_parts:
            plan = top_up(plan, args.target_parts, report)
        report["pass"] = index + 1
        report["parts_before"] = before
        report["parts_after"] = len(plan.get("props", []))
        history.append(report)
        for key, value in report.items():
            if isinstance(value, int) and key != "pass":
                totals[key] = totals.get(key, 0) + value
        if index and report["parts_after"] == report["parts_before"] and not any(
                report[key] for key in ("dropped_overlapping_parts", "lifted_camera_shots")):
            break

    plan["review_passes"] = history
    args.map.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    summary = {
        "passes": len(history),
        "final_parts": len(plan.get("props", [])),
        "camera_shots": len(plan.get("camera_shots", [])),
        "totals": totals,
        "history": history,
    }
    if args.report:
        args.report.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"Map review finished after {summary['passes']} pass(es): "
          f"{summary['final_parts']} aligned, brightly lit Parts, "
          f"{summary['camera_shots']} clean camera shots, "
          f"{totals.get('dropped_camera_blockers', 0)} camera blockers removed, "
          f"{totals.get('lifted_camera_shots', 0)} camera fixes.")
    if summary["final_parts"] < 100:
        raise SystemExit("the reviewed map lost too many Parts; the blueprint needs regeneration")
    return 0


if __name__ == "__main__":
    sys.exit(main())
