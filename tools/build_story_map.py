#!/usr/bin/env python3
"""Validate an AI map layout and emit a runnable Roblox Studio Lua map builder."""
from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from durations import check_duration, duration_arg  # noqa: E402

from effects_catalog import resolve as resolve_effect  # noqa: E402
from time_of_day import (  # noqa: E402
    CLOCK_TIMES, SCENE_TIME_CHOICES, TIME_OF_DAY_CHOICES, apply_scene_time_sequence,
    canonical_time_of_day, resolve_time_of_day, scene_time_sequence,
)

MATERIALS = {"Plastic", "SmoothPlastic", "Concrete", "Grass", "Slate", "Wood", "Metal", "Neon", "Glass", "Brick", "Asphalt"}

# Every shape the renderer can draw. The five Roblox part types are first, then
# the hand-built ones: a triangle (Wedge) was impossible before, so roofs, sails,
# ramps, kites and arrow signs could only be faked with thin blocks.
SHAPES = {
    "Block", "Ball", "Cylinder", "Wedge", "CornerWedge",
    "Cone", "Pyramid", "Prism", "Torus", "Ring", "Hemisphere", "Truss",
}
# Roblox has no Part with these five silhouettes, so the Studio project uses the
# nearest real part type and keeps the AI's intent in the name.
STUDIO_SHAPE_FALLBACK = {"Cone": "Cylinder", "Pyramid": "CornerWedge", "Prism": "Wedge",
                         "Torus": "Cylinder", "Ring": "Cylinder", "Hemisphere": "Ball",
                         "Truss": "Block"}

# The AI may declare what each anchor IS with "model". A building anchor is then
# expanded into a full furnished building (walls, gable roof, glass, furniture,
# plants, leaves) instead of staying one plain block, and a tree/bench/lamp/stall
# anchor becomes a real group of Parts.
BUILDING_MODELS = {
    "building", "house", "home", "shop", "store", "tower", "school", "cafe",
    "station", "temple", "market", "hall", "library", "museum", "lab",
    "laboratory", "bakery", "restaurant", "hotel", "clinic", "hospital",
    "workshop", "warehouse", "cottage", "palace", "castle",
}
GROUP_MODELS = {"tree", "plant", "bench", "lamp", "stall", "fence", "rock", "statue", "vehicle"}
ALL_MODELS = BUILDING_MODELS | GROUP_MODELS
MODEL_ALIASES = {
    "tree": "tree", "street tree": "tree", "oak": "tree", "pine": "tree", "palm": "tree",
    "bush": "plant", "shrub": "plant", "flower": "plant", "flowers": "plant", "garden": "plant",
    "planter": "plant", "hedge": "plant", "pot plant": "plant", "vine": "plant",
    "house": "house", "home": "house", "cottage": "house", "building": "building",
    "shop": "shop", "store": "shop", "kiosk": "stall", "market stall": "stall",
    "stall": "stall", "food stall": "stall", "counter": "stall",
    "bench": "bench", "seat": "bench", "street bench": "bench",
    "lamp": "lamp", "street lamp": "lamp", "lamppost": "lamp", "lantern": "lamp",
    "fence": "fence", "railing": "fence", "gate": "fence",
    "rock": "rock", "boulder": "rock", "stone": "rock",
    "statue": "statue", "monument": "statue", "fountain": "statue",
    "car": "vehicle", "bus": "vehicle", "cart": "vehicle", "truck": "vehicle",
}


def normalize_model(value) -> str:
    """Map any wording a model invents onto one of the build recipes."""
    if not isinstance(value, str):
        return ""
    key = " ".join(value.strip().casefold().replace("_", " ").replace("-", " ").split())
    if key in ALL_MODELS:
        return key
    if key in MODEL_ALIASES:
        return MODEL_ALIASES[key]
    head = key.split(" ")[0]
    if head in ALL_MODELS:
        return head
    return MODEL_ALIASES.get(head, "")

SHAPE_ALIASES = {
    "block": "Block", "part": "Block", "box": "Block", "cube": "Block", "rectangle": "Block",
    "ball": "Ball", "sphere": "Ball", "round": "Ball",
    "cylinder": "Cylinder", "tube": "Cylinder", "pillar": "Cylinder", "column": "Cylinder",
    "triangle": "Wedge", "wedge": "Wedge", "ramp": "Wedge", "slope": "Wedge", "roof": "Wedge",
    "prism": "Prism", "triangular prism": "Prism",
    "corner": "CornerWedge", "corner wedge": "CornerWedge", "cornerwedge": "CornerWedge",
    "cone": "Cone", "spike": "Cone", "tepee": "Cone",
    "pyramid": "Pyramid", "diamond": "Pyramid",
    "torus": "Torus", "donut": "Torus", "doughnut": "Torus",
    "ring": "Ring", "hoop": "Ring", "loop": "Ring",
    "hemisphere": "Hemisphere", "dome": "Hemisphere", "half ball": "Hemisphere",
    "truss": "Truss", "lattice": "Truss", "frame": "Truss", "scaffold": "Truss",
    "beam": "Block", "plane": "Block", "flat": "Block",
}
MATERIAL_ALIASES = {
    "smooth plastic": "SmoothPlastic", "smoothpl astic": "SmoothPlastic", "plastic": "Plastic",
    "smoothplastic": "SmoothPlastic", "grass": "Grass", "turf": "Grass", "lawn": "Grass",
    "brick": "Brick", "bricks": "Brick", "concrete": "Concrete", "cement": "Concrete",
    "wood": "Wood", "wooden": "Wood", "plank": "Wood", "timber": "Wood",
    "metal": "Metal", "metallic": "Metal", "steel": "Metal", "iron": "Metal",
    "neon": "Neon", "glow": "Neon", "glass": "Glass", "window": "Glass",
    "slate": "Slate", "stone": "Slate", "rock": "Slate",
    "asphalt": "Asphalt", "road": "Asphalt", "pavement": "Asphalt",
}


def normalize_shape(value, default="Block"):
    """Accept any spelling a model invents and return a real Roblox PartType."""
    if isinstance(value, str):
        key = " ".join(value.strip().casefold().replace("_", " ").replace("-", " ").split())
        if key in SHAPE_ALIASES:
            return SHAPE_ALIASES[key]
        for candidate in SHAPES:
            if candidate.casefold() == key.replace(" ", ""):
                return candidate
    return default


def normalize_material(value, default="SmoothPlastic"):
    """Accept `brick`, `Brick`, `smooth_plastic`, `Wood Planks`, ... alike."""
    if isinstance(value, str):
        key = " ".join(value.strip().casefold().replace("_", " ").replace("-", " ").split())
        if key in MATERIAL_ALIASES:
            return MATERIAL_ALIASES[key]
        compact = key.replace(" ", "")
        for candidate in MATERIALS:
            if candidate.casefold() == compact:
                return candidate
        # "Wood Planks", "Brick Wall", "Metal Fence": match the leading word.
        head = key.split(" ")[0]
        if head in MATERIAL_ALIASES:
            return MATERIAL_ALIASES[head]
        if key in MATERIALS:
            return key
    return default


def normalize_ground_material(value, default="Grass"):
    return normalize_material(value, default)



LIGHT_KINDS = {"Point", "Spot", "Surface"}
LIGHT_ALIASES = {
    "point": "Point", "pointlight": "Point", "bulb": "Point", "lamp": "Point",
    "spot": "Spot", "spotlight": "Spot", "beam": "Spot", "flashlight": "Spot",
    "surface": "Surface", "surfacelight": "Surface", "window": "Surface", "panel": "Surface",
}
# A light is a Part that also glows: the Part is the visible lamp, the light is the
# pool of colour it throws. Brightness and range are the two dials the AI asked to
# be able to raise and lower, and the colour is the third.
LIGHT_DEFAULTS = {"kind": "Point", "color": [255, 226, 156], "brightness": 1.6,
                  "range": 22.0, "angle": 90.0}


def normalize_light(value):
    """Return a bounded light, or None when the prop has no light."""
    if value is True:  # "light": true means "a plain lamp"
        value = {"kind": "Point"}
    if isinstance(value, str):
        if not value.strip():
            return None
        value = {"kind": value}
    if not isinstance(value, dict) or not value:
        return None
    if value.get("enabled") is False or value.get("on") is False:
        return None
    raw_kind = " ".join(str(value.get("kind", value.get("type", value.get("light", "Point")))).strip().casefold().split())
    kind = LIGHT_ALIASES.get(raw_kind, LIGHT_ALIASES.get(raw_kind.replace(" ", ""), ""))
    if kind not in LIGHT_KINDS:
        kind = "Point"

    def number(key, low, high, default):
        try:
            result = float(value.get(key, default))
        except (TypeError, ValueError):
            return default
        if result != result:
            return default
        return round(max(low, min(high, result)), 3)

    color = value.get("color") or value.get("colour")
    if not (isinstance(color, (list, tuple)) and len(color) == 3):
        color = (value.get("hex") or value.get("color_hex"))
        if isinstance(color, str):
            digits = color.strip().lstrip("#")
            if len(digits) == 6:
                try:
                    color = [int(digits[i:i + 2], 16) for i in (0, 2, 4)]
                except ValueError:
                    color = None
            else:
                color = None
        else:
            color = None
    try:
        color = [max(0, min(255, int(round(float(channel))))) for channel in color] if color else list(LIGHT_DEFAULTS["color"])
    except (TypeError, ValueError):
        color = list(LIGHT_DEFAULTS["color"])
    return {
        "kind": kind,
        "color": color,
        # Brightness, range and angle use Roblox's own units so the Studio export
        # and the MP4 agree: 0-5 brightness, 0-60 studs of range, 0-180 degrees.
        "brightness": number("brightness", 0.0, 5.0, LIGHT_DEFAULTS["brightness"]),
        "range": number("range", 0.0, 60.0, LIGHT_DEFAULTS["range"]),
        "angle": number("angle", 0.0, 180.0, LIGHT_DEFAULTS["angle"]),
    }


def normalize_effect(value):
    """Return a bounded particle effect, or None."""
    return resolve_effect(value)


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


def target_camera_count(duration):
    """Camera beat budget for the reference's brisk, roughly four-second rhythm."""
    return max(10, min(44, int(round(float(duration) / 4)) + 2))


def configure_plan_time_of_day(plan, requested="auto", context="", scene_time_notes=""):
    """Keep AI-authored global and per-scene hours, with a safe story fallback.

    ``auto`` prefers the AI's required global choice, then infers from the story
    and defaults to daylight. Valid shot overrides are always retained for the
    automatic workflow. An explicit CLI-only hour still acts as a global lock
    unless scene-time notes explicitly request changes.
    """
    notes = str(scene_time_notes or "").strip()[:500]
    requested_name = str(requested or "auto").strip().casefold()
    automatic = requested_name in {"", "auto"}
    ai_hour = canonical_time_of_day(plan.get("time_of_day"))
    resolved = (ai_hour if automatic and ai_hour else
                resolve_time_of_day(requested, " ".join((str(context or ""), notes))))
    plan["time_of_day"] = resolved
    shots = plan.get("camera_shots")
    if not isinstance(shots, list):
        shots = []
        plan["camera_shots"] = shots

    def has_scene_hours():
        return any(
            isinstance(shot, dict)
            and canonical_time_of_day(shot.get("time_of_day")) is not None
            for shot in shots
        )

    fallback_applied = False
    if not automatic and not notes:
        for shot in shots:
            if isinstance(shot, dict):
                shot.pop("time_of_day", None)
    elif not has_scene_hours():
        # If the AI omitted shot overrides, genuine time changes mentioned in
        # the story still provide an ordered deterministic fallback. Notes remain
        # supported for direct CLI callers, but are no longer a workflow input.
        fallback_text = notes or str(context or "")
        sequence = scene_time_sequence(fallback_text)
        if notes or len(set(sequence)) > 1:
            fallback_applied = apply_scene_time_sequence(shots, fallback_text)

    if notes:
        plan["scene_time_notes"] = notes
    else:
        plan.pop("scene_time_notes", None)
    plan["time_of_day_mode"] = "per_scene" if has_scene_hours() or fallback_applied else "global"
    return resolved, fallback_applied


def default_camera_shots(duration, usernames=()):
    """A reference-short rhythm: fresh angle or cutaway about every four seconds."""
    views = [
        ([0, 26, 60], [0, 4, 24], "smooth"),
        ([-13, 11, 45], [0, 4, 24], "smooth"),
        ([15, 9, 36], [6, 4, 24], "snap"),
        ([19, 12, 15], [0, 4, 24], "smooth"),
        ([-11, 8, 36], [0, 4, 24], "snap"),
        ([9, 9, 48], [0, 4, 24], "smooth"),
        ([-17, 13, 26], [0, 4, 24], "snap"),
        ([0, 18, 58], [0, 4, 24], "smooth"),
        ([-9, 7, 20], [4, 4, 24], "snap"),
        ([13, 15, 44], [0, 4, 24], "smooth"),
        ([6, 8, 22], [0, 4, 24], "snap"),
        ([-21, 16, 52], [0, 4, 24], "smooth"),
        ([10, 6, 30], [2, 4, 24], "snap"),
        ([0, 34, 92], [0, 4, 24], "smooth"),
        ([-7, 10, 32], [0, 4, 24], "snap"),
        ([17, 11, 40], [0, 4, 24], "smooth"),
    ]
    count = target_camera_count(duration)
    last = count - 1
    face_indices = {max(1, count // 6), count // 2, min(count - 2, (5 * count) // 6)}
    output = []
    for index in range(count):
        base_position, base_target, base_mode = views[index % len(views)]
        position, target = list(base_position), list(base_target)
        cycle = index // len(views)
        if cycle:
            # The fallback keeps changing its angle instead of repeating one
            # sixteen-shot loop in a long, reference-length short.
            angle = cycle * 0.37
            dx, dz = position[0] - target[0], position[2] - target[2]
            position[0] = target[0] + dx * math.cos(angle) - dz * math.sin(angle)
            position[2] = target[2] + dx * math.sin(angle) + dz * math.cos(angle)
            position[1] = max(5, min(40, position[1] + (cycle % 3 - 1) * 1.5))
        is_face = bool(usernames and index in face_indices)
        output.append({
            "time": round(duration * index / last, 2),
            "position": [round(value, 2) for value in position],
            "target": target,
            "transition": "smooth" if index == 0 or index == last else
                          ("snap" if index % 4 == 2 else base_mode),
            "focus_username": usernames[index % len(usernames)] if usernames else "world",
            "framing": "face" if is_face else "auto",
            "face_distance": FACE_DISTANCE_DEFAULT,
        })
    return output


FACE_EXPRESSIONS = ("neutral", "happy", "sad", "surprised", "worried", "angry", "excited", "thinking")
FACE_FRAMINGS = {"auto", "wide", "face", "close", "closeup", "close-up"}
FACE_DISTANCE_MIN = 2.8
FACE_DISTANCE_DEFAULT = 3.0
FACE_DISTANCE_MAX = 4.0


def default_face_expressions(duration, usernames=()):
    """A story-shaped feeling arc: hook, doubt, turn, relief, warm ending.

    The AI is asked to replace this with its own beat-perfect timeline; this
    default keeps the renderer's faces alive even if the model omits it.
    """
    beats = [
        (0.00, "neutral", 0.65), (0.10, "thinking", 0.70), (0.26, "worried", 0.80),
        (0.44, "surprised", 0.90), (0.58, "thinking", 0.60), (0.72, "happy", 0.85),
        (0.86, "excited", 0.90), (0.96, "happy", 1.00),
    ]
    lead = usernames[0] if usernames else ""
    return [
        {"time": round(duration * fraction, 2), "expression": expression,
         "intensity": intensity, "username": lead}
        for fraction, expression, intensity in beats
    ]


def normalize_face_expressions(entries, duration, usernames=()):
    """Keep the AI's expression switches on a sane, ordered, story-long timeline."""
    valid_names = {name.casefold(): name for name in usernames}
    cleaned = {}
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        expression = str(entry.get("expression", "")).strip().lower()
        if expression not in FACE_EXPRESSIONS:
            continue
        time = entry.get("time")
        if isinstance(time, bool) or not isinstance(time, (int, float)) or not 0 <= float(time) <= duration:
            continue
        intensity = entry.get("intensity", 0.8)
        if isinstance(intensity, bool) or not isinstance(intensity, (int, float)):
            intensity = 0.8
        username = str(entry.get("username", "") or "").strip()
        username = valid_names.get(username.casefold(), "") if username else ""
        cleaned[round(float(time), 2)] = {
            "time": round(float(time), 2),
            "expression": expression,
            "intensity": round(max(0.0, min(1.0, float(intensity))), 2),
            "username": username,
        }
    timeline = [cleaned[key] for key in sorted(cleaned)]
    if len(timeline) < 3:
        return default_face_expressions(duration, usernames)
    if timeline[0]["time"] > 0.5:
        timeline.insert(0, {"time": 0.0, "expression": "neutral", "intensity": 0.7,
                            "username": timeline[0]["username"]})
    return timeline[:40]


def densify_camera_shots(shots, duration):
    """Fill a sparse AI storyboard to the reference's brisk shot rhythm.

    Existing AI key shots (especially story-hour overrides and face frames) are
    retained. New beats bisect the longest gaps, interpolate framing positions,
    and introduce periodic snap cuts rather than letting a long video hold one
    angle for tens of seconds.
    """
    target = target_camera_count(duration)
    while len(shots) < target:
        gap_index = max(range(len(shots) - 1),
                        key=lambda index: shots[index + 1]["time"] - shots[index]["time"])
        a, b = shots[gap_index], shots[gap_index + 1]
        gap = float(b["time"]) - float(a["time"])
        if gap <= 0.02:
            break
        time = round((float(a["time"]) + float(b["time"])) / 2, 2)
        if time <= float(a["time"]) or time >= float(b["time"]):
            break
        blend = (time - float(a["time"])) / gap
        near = a if blend < 0.5 else b
        shot = {
            "time": time,
            "position": [round(float(a["position"][axis]) * (1 - blend)
                                + float(b["position"][axis]) * blend, 2) for axis in range(3)],
            "target": [round(float(a["target"][axis]) * (1 - blend)
                             + float(b["target"][axis]) * blend, 2) for axis in range(3)],
            "transition": "snap" if (len(shots) % 4 == 2) else "smooth",
            "focus_username": near["focus_username"],
            "framing": "auto",
            "face_distance": near["face_distance"],
        }
        shots.insert(gap_index + 1, shot)
    return shots


def normalize_camera_shots(shots, duration, usernames=()):
    if not isinstance(shots, list) or not 4 <= len(shots) <= 48:
        return default_camera_shots(duration, usernames)
    clean, previous = [], -1.0
    valid_names = {name.casefold(): name for name in usernames}
    for index, shot in enumerate(shots):
        if not isinstance(shot, dict):
            return default_camera_shots(duration, usernames)
        time, pos, target = shot.get("time"), shot.get("position"), shot.get("target")
        transition = shot.get("transition", "smooth")
        if (isinstance(time, bool) or not isinstance(time, (int, float))
                or not 0 <= time <= duration or time <= previous):
            return default_camera_shots(duration, usernames)
        for vector in (pos, target):
            if (not isinstance(vector, list) or len(vector) != 3
                    or any(isinstance(v, bool) or not isinstance(v, (int, float))
                           or not -300 <= v <= 300 for v in vector)):
                return default_camera_shots(duration, usernames)
        if not isinstance(transition, str) or transition not in {"smooth", "snap"}:
            transition = "smooth"
        focus = shot.get("focus_username", shot.get("focus", ""))
        if isinstance(focus, str) and focus.casefold() in {"world", "none"}:
            focus = "world"
        elif isinstance(focus, str) and focus.casefold() in valid_names:
            focus = valid_names[focus.casefold()]
        else:
            focus = usernames[index % len(usernames)] if usernames else "world"
        framing = str(shot.get("framing", "auto") or "auto").strip().lower()
        if framing not in FACE_FRAMINGS:
            framing = "auto"
        elif framing in {"close", "closeup", "close-up"}:
            framing = "face"
        shot_face_distance = shot.get("face_distance", FACE_DISTANCE_DEFAULT)
        if isinstance(shot_face_distance, bool) or not isinstance(shot_face_distance, (int, float)):
            shot_face_distance = FACE_DISTANCE_DEFAULT
        shot_face_distance = min(FACE_DISTANCE_MAX, max(FACE_DISTANCE_MIN, float(shot_face_distance)))
        normalized_shot = {
            "time": round(float(time), 2),
            "position": [round(float(v), 2) for v in pos],
            "target": [round(float(v), 2) for v in target],
            "transition": transition,
            "focus_username": focus,
            "framing": framing,
            "face_distance": round(float(shot_face_distance), 2),
        }
        shot_hour = shot.get("time_of_day")
        if isinstance(shot_hour, str) and shot_hour.casefold() in SCENE_TIME_CHOICES:
            normalized_shot["time_of_day"] = shot_hour.casefold()
        clean.append(normalized_shot)
        previous = time
    if clean[0]["time"] != 0:
        clean.insert(0, default_camera_shots(duration, usernames)[0])
    if clean[-1]["time"] < duration:
        last = dict(clean[-1])
        last["time"] = float(duration)
        last["transition"] = "smooth"
        last["framing"] = "auto"
        clean.append(last)
    clean = densify_camera_shots(clean, duration)
    # Reference-style shorts revisit the cast at a few emotional beats; if the
    # AI forgot the close-ups, promote three well-spaced shots without cropping
    # closer than the renderer's safe 2.8-4 stud range.
    face_indices = [index for index, shot in enumerate(clean) if shot["framing"] == "face"]
    if duration >= 30 and len(face_indices) < 3 and usernames:
        targets = [max(1, len(clean) // 5), len(clean) // 2,
                   min(len(clean) - 2, (4 * len(clean)) // 5)]
        targets.extend(range(len(clean)))
        for index in dict.fromkeys(targets):
            if len(face_indices) >= 3:
                break
            if (index not in face_indices and clean[index]["focus_username"] != "world"):
                clean[index]["framing"] = "face"
                clean[index]["face_distance"] = FACE_DISTANCE_DEFAULT
                face_indices.append(index)
    # The sample's fast rhythm relies on deliberate cuts as well as smooth moves.
    for index in range(2, len(clean), 4):
        if clean[index]["transition"] != "snap":
            clean[index]["transition"] = "snap"
    return clean


def decode_response(path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    response = payload.get("response", "") if isinstance(payload, dict) else ""
    if isinstance(payload, dict) and isinstance(payload.get("message"), dict):
        response = payload["message"].get("content", response)
    try:
        plan = json.loads(response)
    except (json.JSONDecodeError, TypeError):
        plan = {}
    return plan


THEME_CUE_PLACEHOLDERS = {"", "auto", "auto from story", "auto from the story", "ai decides"}


def derive_theme(theme_cue="", story="", topic="", plan=None):
    """A specific theme sentence for a plan whose own theme came back empty.

    The blueprint is one JSON document produced over many minutes. A model can
    drop a single required field - usually "theme" - and rejecting the whole
    document over that sentence threw away a forty-minute plan and started the
    expensive request again. The story already says what the world looks like,
    so use it.
    """
    cue = str(theme_cue or "").strip()
    if cue and cue.casefold() not in THEME_CUE_PLACEHOLDERS:
        return re.sub(r"[\r\n]+", " ", cue)[:160]
    for text in (story, topic):
        clean = " ".join(str(text or "").split())
        if len(clean) > 12:
            first = re.split(r"(?<=[.!?])\s", clean)[0]
            return (first or clean)[:160].rstrip(" .,") + "."
    name = ""
    if isinstance(plan, dict):
        name = str(plan.get("name") or "").strip()
    return f"The world of {name}." if name else "A story-shaped Roblox world built from the narration."


def repair_blueprint(plan, theme_cue="", story="", topic=""):
    """Fill the small required fields a model forgets; return (plan, fixes).

    Only genuinely unusable documents are rejected: anything that is not an
    object, or that has no props at all. Everything else is repaired, and every
    repair is reported so the log says what happened.
    """
    fixes = []
    if not isinstance(plan, dict):
        return plan, fixes
    if not isinstance(plan.get("theme"), str) or not plan["theme"].strip():
        plan["theme"] = derive_theme(theme_cue, story, topic, plan)
        fixes.append(f'added the missing "theme": {plan["theme"]}')
    if not isinstance(plan.get("name"), str) or not plan["name"].strip():
        plan["name"] = "Story World"
        fixes.append('added the missing "name": Story World')
    if not isinstance(plan.get("props"), list) or not plan["props"]:
        return plan, fixes
    return plan, fixes


def default_character_placements(usernames):
    positions = [[0, 0, 24], [-3, 0, 24], [3, 0, 24], [-6, 0, 29], [6, 0, 29], [0, 0, 34]]
    return [
        {"username": name, "role": "lead" if index == 0 else "supporting", "position": positions[index]}
        for index, name in enumerate(usernames[:6])
    ]


def requested_avatar_effects(topic):
    """Return only body effects explicitly requested in the user's story/topic text."""
    raw_topic = str(topic or "")
    text = raw_topic.casefold()
    requests = []
    number_requested = (
        re.search(r"\b(?:strength|power|level)\s+(?:numbers?|scores?|stats?)\b", text)
        or re.search(r"\b(?:numbers?|scores?)\b.{0,45}\b(?:above|over|on|at|in|head|body|chest|arm|leg|avatar|character)\b", text)
        or re.search(r"\b(?:put|show|display|add|place|write|attach|wear)\b.{0,45}\b(?:numbers?|scores?)\b", text)
    )
    if number_requested:
        fixed_number = re.search(r"\b(?:numbers?|scores?)\s*(?:is|of|:|=)?\s*(\d{1,3})\b", text)
        requests.append(("number", int(fixed_number.group(1))) if fixed_number else "number")
    for kind, pattern in (("scar", r"\bscars?\b|\bscarred\b"),
                          ("tattoo", r"\btattoos?\b"),
                          ("birthmark", r"\bbirthmarks?\b"),
                          ("badge", r"\bbadges?\b"),
                          ("emblem", r"\bemblems?\b"),
                          ("symbol", r"\bsymbols?\b")):
        if re.search(pattern, text):
            requests.append(kind)
    if re.search(r"\b(?:write|print|put|show|display|add)\b.{0,35}\b(?:text|word|lettering)\b", text):
        match = re.search(r"[\"“”']([^\"“”']{1,18})[\"“”']", raw_topic)
        if match:
            value = re.sub(r"[^A-Za-z0-9 _-]", "", match.group(1)).strip()[:18]
            if value:
                requests.append(("text", value))
    return requests


def avatar_effect_attachment(topic, kind):
    text = str(topic or "").casefold()
    kind_words = {
        "number": r"numbers?|scores?|strength|power|level",
        "text": r"text|word|lettering",
        "scar": r"scarred|scars|scar",
        "tattoo": r"tattoos?", "birthmark": r"birthmarks?", "badge": r"badges?",
        "emblem": r"emblems?", "symbol": r"symbols?",
    }
    clauses = re.split(r"[,;]|\band\b|\bwhile\b", text)
    clause = next((part for part in clauses if re.search(rf"\b(?:{kind_words.get(kind, kind)})\b", part)), text)
    if "left arm" in clause:
        return "left_arm"
    if "right arm" in clause:
        return "right_arm"
    if "left leg" in clause:
        return "left_leg"
    if "right leg" in clause:
        return "right_leg"
    if re.search(r"\b(?:chest|torso|shirt|body)\b", clause):
        return "torso"
    if re.search(r"\b(?:arm|wrist|hand)\b", clause):
        return "left_arm"
    if re.search(r"\b(?:leg|ankle|foot)\b", clause):
        return "left_leg"
    if re.search(r"\b(?:head|face|forehead|cheek)\b", clause) or kind in {"number", "scar"}:
        return "head"
    return "torso"


def normalize_character_placements(raw, usernames, visual_request=""):
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
    requests = requested_avatar_effects(visual_request)
    placements = []
    used_numbers = set()
    for index, default in enumerate(defaults):
        name = default["username"]
        effects = []
        if requests:
            digest = hashlib.sha256(name.casefold().encode("utf-8")).digest()
            number = 10 + int.from_bytes(digest[:4], "big") % 90
            while number in used_numbers:
                number = 10 + ((number - 9) % 90)
            used_numbers.add(number)
            for request in requests:
                kind, value = request if isinstance(request, tuple) else (request, None)
                effect = {"kind": kind, "attachment": avatar_effect_attachment(visual_request, kind)}
                if kind == "number":
                    effect["value"] = value if isinstance(value, int) else number
                elif value is not None:
                    effect["value"] = value
                effects.append(effect)
        placement = {
            "username": name,
            "role": "lead" if index == 0 else "supporting",
            "position": by_name.get(name.casefold(), default["position"]),
        }
        if effects:
            placement["visual_effects"] = effects
        placements.append(placement)
    return placements


def theme_family(text):
    text = str(text or "").casefold()
    if any(word in text for word in ("underwater", "ocean", "reef", "coral", "sea", "marine")):
        return "reef"
    if any(word in text for word in ("space", "moon", "planet", "galaxy", "cosmic", "star")):
        return "space"
    if any(word in text for word in ("snow", "ice", "winter", "arctic", "frozen")):
        return "snow"
    if any(word in text for word in ("forest", "jungle", "woodland", "garden", "park")):
        return "forest"
    if any(word in text for word in ("desert", "egypt", "ancient", "sand", "dune")):
        return "desert"
    if any(word in text for word in ("castle", "medieval", "kingdom", "knight", "fantasy")):
        return "castle"
    if any(word in text for word in ("city", "town", "school", "market", "shop", "street", "cafe")):
        return "town"
    return "storybook"


def _fallback_palette(family):
    return {
        "reef": ([45, 125, 150], [140, 210, 225], [50, 190, 190], [245, 125, 185]),
        "space": ([47, 52, 91], [155, 170, 230], [90, 105, 195], [65, 225, 255]),
        "snow": ([150, 185, 215], [215, 235, 250], [105, 160, 205], [235, 245, 255]),
        "forest": ([68, 128, 77], [180, 215, 170], [75, 160, 95], [225, 165, 80]),
        "desert": ([172, 125, 72], [230, 195, 135], [198, 145, 72], [75, 170, 185]),
        "castle": ([91, 91, 125], [185, 180, 195], [125, 115, 155], [230, 175, 80]),
        "town": ([105, 145, 115], [195, 215, 225], [85, 145, 195], [245, 170, 80]),
        "storybook": ([92, 135, 125], [190, 210, 220], [100, 155, 185], [235, 155, 95]),
    }[family]


def procedural_fallback_plan(theme, story, duration, usernames=()):
    """Create a theme-aware map blueprint if the local model service is unavailable."""
    cue = str(theme or "").strip()
    story = str(story or "").strip()
    cue_family, story_family = theme_family(cue), theme_family(story)
    family = cue_family if cue and cue_family != "storybook" else story_family
    names = {"reef": ("Reef", "Pearl Market", "Tide Hall", "Coral Workshop"),
             "space": ("Cosmic", "Orbit Market", "Moon Hall", "Star Workshop"),
             "snow": ("Snowfall", "Frost Market", "Aurora Hall", "Pine Workshop"),
             "forest": ("Wildwood", "Forest Market", "Canopy Hall", "Moss Workshop"),
             "desert": ("Sunstone", "Oasis Market", "Dune Hall", "Sands Workshop"),
             "castle": ("Kingdom", "Royal Market", "Castle Hall", "Banner Workshop"),
             "town": ("Storybook", "Story Market", "Town Hall", "Studio Workshop"),
             "storybook": ("Storybook", "Wonder Market", "Story Hall", "Story Workshop")}[family]
    ground, ambient, primary, accent = _fallback_palette(family)
    props = []
    building_specs = [
        (names[1], [-42, 8, -62], [34, 16, 30], primary),
        (names[2], [42, 10, -62], [36, 20, 32], accent),
        (names[3], [0, 8, 82], [32, 16, 28], primary),
    ]
    for name, position, size, color in building_specs:
        props.append({"name": name, "shape": "Block", "material": "Brick",
                      "position": position, "size": size, "color": color, "physics": "static"})
    landmark_specs = [
        ("Story Gathering Stage", [0, 1.2, -8], [26, 2.4, 18], accent, "SmoothPlastic"),
        (f"{names[0]} Gateway", [0, 7, -26], [18, 14, 3], primary, "Slate"),
        (f"{names[0]} Story Beacon", [0, 8, 24], [5, 16, 5], accent, "Neon"),
        ("Story Choice Fountain", [-20, 2.5, 6], [10, 5, 10], primary, "Slate"),
        ("Story Meeting Pavilion", [20, 5, 8], [14, 10, 14], accent, "SmoothPlastic"),
        ("North Story Landmark", [0, 9, -125], [16, 18, 16], primary, "Slate"),
        ("South Story Landmark", [0, 7, 150], [14, 14, 14], accent, "SmoothPlastic"),
        ("West Story Arch", [-125, 6, 0], [18, 12, 4], primary, "Brick"),
        ("East Story Arch", [125, 6, 0], [18, 12, 4], accent, "Brick"),
        ("West Welcome Sign", [-18, 5, 45], [8, 10, 1], accent, "Wood"),
        ("East Welcome Sign", [18, 5, 45], [8, 10, 1], primary, "Wood"),
        ("Story Plaza Rug", [0, 0.25, 54], [26, 0.5, 12], accent, "SmoothPlastic"),
        ("Story Moment Orb", [0, 12, -8], [6, 6, 6], accent, "Neon"),
        ("West Story Planter", [-28, 1.5, 38], [8, 3, 8], primary, "Concrete"),
        ("East Story Planter", [28, 1.5, 38], [8, 3, 8], primary, "Concrete"),
        ("West Rest Bench", [-35, 1.5, 26], [10, 1, 3], accent, "Wood"),
        ("East Rest Bench", [35, 1.5, 26], [10, 1, 3], accent, "Wood"),
        ("Story Crossroads Marker", [0, 2, -42], [4, 4, 4], primary, "Metal"),
    ]
    for name, position, size, color, material in landmark_specs:
        props.append({"name": name, "shape": "Block", "material": material,
                      "position": position, "size": size, "color": color, "physics": "static"})
    if cue and story:
        plan_theme = f"{cue}; story context: {story[:110]}"[:180]
    elif cue:
        plan_theme = cue[:180]
    else:
        plan_theme = f"Story-inspired {names[0].casefold()} world following this plot: {story[:100]}".strip()[:180]
    return {
        "name": f"{names[0]} Story World",
        "theme": plan_theme,
        "ground_material": "Slate" if family in {"reef", "space", "castle"} else "Grass",
        "ground_color": ground,
        "ambient_color": ambient,
        "props": props,
        "camera_shots": default_camera_shots(duration, usernames),
        "face_expressions": default_face_expressions(duration, usernames),
        "character_placements": default_character_placements(usernames),
    }


def expand_plan(plan, target_props=3000):
    """Turn a compact AI landmark blueprint into a full, themed furnished build."""
    source_props = list(plan.get("props", []))
    if len(source_props) >= target_props:
        return {**plan, "props": source_props}

    building_words = {
        "building", "shop", "tower", "house", "home", "school", "cafe", "store", "station", "temple",
        "castle", "museum", "hall", "market", "hotel", "factory", "restaurant", "library",
        "hospital", "arcade", "bakery", "office", "apartment", "mansion", "workshop", "palace",
        "warehouse", "inn", "laboratory", "lab", "theater", "theatre", "pavilion", "cottage",
        "hut", "villa", "barn", "church", "chapel", "clinic", "salon", "bistro", "diner", "pub",
        "lodge", "shelter", "garage", "hangar", "dorm", "hostel", "villas", "houses", "homes",
    }
    component_words = {"wall", "roof", "door", "window", "frame", "floor", "stair", "chimney",
                       "foundation", "facade", "pillar", "column", "interior", "sill", "header"}
    building_cores = []
    keep_props = []
    for prop in source_props:
        words = set(re.findall(r"[a-z]+", prop.get("name", "").casefold()))
        size = prop.get("size", [0, 0, 0])
        model = normalize_model(prop.get("model"))
        # Names like "Cozy Home" or "Sunset Villa" don't contain "building" but
        # are obviously houses — normalize the name itself so they still become
        # hollow houses instead of a single solid brick.
        name_model = normalize_model(prop.get("name", ""))
        named_model_building = name_model in BUILDING_MODELS
        named_building = ((bool(words & building_words) or named_model_building)
                          and not bool(words & component_words)
                          and size[0] >= 10 and size[1] >= 6 and size[2] >= 8
                          and prop.get("shape") == "Block")
        # A declared building model always becomes a real building, even when the
        # AI drew its anchor small or named it "Story Place".
        declared_building = (model in BUILDING_MODELS and prop.get("shape") in {"Block", "Cylinder"}
                             and min(size[0], size[2]) >= 6 and size[1] >= 4)
        is_building = named_building or declared_building or named_model_building
        (building_cores if is_building else keep_props).append(prop)

    expanded = list(keep_props)
    used_names = {prop["name"].casefold() for prop in expanded}
    family = theme_family(plan.get("theme", ""))
    base, _ambient, primary, accent = _fallback_palette(family)
    building_name_sets = {
        "reef": ["Tide Market", "Pearl Hall", "Coral Workshop"],
        "space": ["Orbit Market", "Moon Hall", "Star Workshop"],
        "snow": ["Frost Market", "Aurora Hall", "Pine Workshop"],
        "forest": ["Forest Market", "Canopy Hall", "Moss Workshop"],
        "desert": ["Oasis Market", "Dune Hall", "Sands Workshop"],
        "castle": ["Royal Market", "Castle Hall", "Banner Workshop"],
        "town": ["Story Market", "Town Hall", "Studio Workshop"],
        "storybook": ["Wonder Market", "Story Hall", "Story Workshop"],
    }
    candidate_sites = [(-82, -78), (82, -78), (0, 112), (-132, 72), (132, 72),
                       (0, -158), (-165, -80), (165, -80), (-100, 155), (100, 155)]
    existing_anchors = source_props[:]
    for name in building_name_sets[family]:
        if len(building_cores) >= 3:
            break
        if any(core["name"].casefold() == name.casefold() for core in building_cores):
            continue
        selected = None
        for cx, cz in candidate_sites:
            if any(abs(cx - anchor["position"][0]) < 28 + anchor["size"][0] / 2
                   and abs(cz - anchor["position"][2]) < 24 + anchor["size"][2] / 2
                   for anchor in existing_anchors):
                continue
            selected = (cx, cz)
            break
        if selected is None:
            continue
        cx, cz = selected
        color = primary if len(building_cores) % 2 == 0 else accent
        building_cores.append({"name": name, "shape": "Block", "material": "Brick",
                               "position": [cx, 8, cz], "size": [34, 16, 30],
                               "color": color, "physics": "static"})
        existing_anchors.append(building_cores[-1])

    def add(name, shape, material, position, size, color, physics="static"):
        name = re.sub(r"[^A-Za-z0-9 _-]", "", str(name)).strip()[:40] or "Story Detail"
        base_name, suffix = name, 2
        while name.casefold() in used_names:
            tail = f" {suffix}"
            name = base_name[:40 - len(tail)] + tail
            suffix += 1
        def snap(value, low, high):
            return round(min(high, max(low, round(float(value) / 0.5) * 0.5)), 2)

        try:
            p = [snap(position[0], -250, 250), snap(position[1], 0.25, 250), snap(position[2], -250, 250)]
            s = [snap(value, 0.5, 64) for value in size]
            c = [max(0, min(255, int(value))) for value in color]
            # Same brightness floor as validate(): no expanded detail may be a
            # near-black slab that swallows the character on screen.
            luminance = 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
            if luminance < 104:
                blend = min(1.0, (104 - luminance) / 104)
                target = [176, 186, 200]
                c = [round(channel * (1 - blend * 0.9) + target[i] * (blend * 0.9))
                     for i, channel in enumerate(c)]
        except (TypeError, ValueError, IndexError):
            return False
        if (len(p) != 3 or len(s) != 3 or len(c) != 3 or not -250 <= p[0] <= 250
                or not 0 <= p[1] <= 250 or not -250 <= p[2] <= 250
                or abs(p[0]) + s[0] / 2 > 320 or abs(p[2]) + s[2] / 2 > 320):
            return False
        expanded.append({"name": name, "shape": shape, "material": material,
                         "position": p, "size": s, "color": c, "physics": physics})
        used_names.add(name.casefold())
        return True

    def tint(color, factor):
        return [max(0, min(255, round(channel * factor))) for channel in color]

    leaf_greens = ([64, 138, 74], [88, 166, 91], [46, 112, 62], [120, 186, 96])
    pot_terracotta = [176, 104, 76]
    # ------------------------------------------------------------ group models
    # One anchor in the AI plan becomes a whole furnished group here, so a "tree"
    # is a trunk plus a leafy canopy, a "bench" has a back and legs, a "stall" has
    # an awning and goods, and a "plant" is a pot with leaves that spill over.
    group_offsets = [(-11, -9), (11, -9), (-11, 9), (11, 9), (0, -13), (0, 13)]
    groups_made = 0

    def leaves(name, x, y, z, scale, color_seed=0, count=4, place=None):
        """Leaf clusters that give a canopy its shape instead of one ball."""
        put_leaf = place or add
        for index in range(count):
            reach = scale * (0.55 if index else 0.0)
            leaf = leaf_greens[(color_seed + index) % len(leaf_greens)]
            put_leaf(f"{name} Leaf Cluster {index + 1}", "Ball", "Grass",
                [x + reach * 0.9 * (1 if index % 2 else -1),
                 y + scale * (0.18 if index else 0.34),
                 z + reach * 0.9 * (1 if index % 3 else -1)],
                [scale * 1.05, scale * 0.85, scale * 1.05], leaf)

    def build_group(prop):
        """Expand one tree/plant/bench/lamp/stall/fence/rock/statue anchor."""
        nonlocal groups_made

        def put(name, shape, material, position, size, color, physics="static"):
            # Group detail must never grow into the cast lane, or it hides the
            # faces the camera closes in on.
            if abs(position[0]) < 20 and 4 <= position[2] <= 54:
                return False
            return add(name, shape, material, position, size, color, physics)

        name = prop["name"]
        x, y, z = prop["position"]
        sx, sy, sz = prop["size"]
        color = list(prop.get("color") or [120, 145, 180])
        model = normalize_model(prop.get("model"))
        footprint = max(sx, sz)
        if not model:
            # No declaration: fall back to a sensible model from the name so a
            # "Palm" or "Lantern" still becomes a group rather than a lone block.
            model = normalize_model(name)
            if model not in GROUP_MODELS:
                return False
        if model == "tree":
            trunk_h = max(4.0, sy * 0.62)
            put(f"{name} Trunk", "Cylinder", "Wood", [x, trunk_h / 2 + y, z],
                [max(1.0, footprint * 0.16), trunk_h, max(1.0, footprint * 0.16)], [104, 72, 47])
            for branch in range(2):
                put(f"{name} Branch {branch + 1}", "Cylinder", "Wood",
                    [x + (1.1 if branch else -1.1), y + trunk_h * 0.82,
                     z + (0.9 if branch else -0.9)],
                    [0.7, trunk_h * 0.42, 0.7], [112, 78, 51])
            leaves(f"{name} Canopy", x, y + trunk_h, z, max(3.0, footprint * 0.62),
                   groups_made, 5, put)
            for spot in range(3):
                put(f"{name} Fallen Leaf {spot + 1}", "Block", "Grass",
                    [x + (spot - 1) * 1.6, y + 0.12, z + (spot - 1) * 1.3],
                    [1.1, 0.14, 0.8], leaf_greens[spot % len(leaf_greens)])
        elif model == "plant":
            put(f"{name} Planter", "Cylinder", "Concrete", [x, y + 0.75, z],
                [max(1.4, footprint * 0.5), 1.5, max(1.4, footprint * 0.5)], pot_terracotta)
            put(f"{name} Soil", "Cylinder", "Slate", [x, y + 1.5, z],
                [max(1.1, footprint * 0.4), 0.3, max(1.1, footprint * 0.4)], [82, 66, 54])
            leaves(f"{name} Leaves", x, y + 1.7, z, max(1.4, footprint * 0.55),
                   groups_made, 3, put)
            for stem in range(2):
                put(f"{name} Stem {stem + 1}", "Block", "Grass",
                    [x + (0.5 if stem else -0.5), y + 2.4, z],
                    [0.2, 1.8, 0.2], leaf_greens[(groups_made + stem) % len(leaf_greens)])
        elif model == "bench":
            put(f"{name} Seat", "Block", "Wood", [x, y + 1.1, z],
                [max(3.0, sx), 0.35, max(1.4, sz)], [148, 102, 64])
            put(f"{name} Backrest", "Block", "Wood", [x, y + 1.9, z - sz * 0.42],
                [max(3.0, sx), 1.2, 0.3], [124, 84, 52])
            for leg in (-1, 1):
                put(f"{name} Leg {leg + 2}", "Block", "Metal", [x + leg * sx * 0.38, y + 0.55, z],
                    [0.28, 1.1, 1.1], [72, 83, 97])
        elif model == "lamp":
            post_h = max(5.0, sy)
            put(f"{name} Post", "Cylinder", "Metal", [x, y + post_h / 2, z],
                [0.42, post_h, 0.42], [74, 86, 103])
            put(f"{name} Lantern", "Ball", "Neon", [x, y + post_h + 0.6, z],
                [1.1, 1.1, 1.1], [255, 226, 150])
            put(f"{name} Base", "Cylinder", "Concrete", [x, y + 0.2, z],
                [1.2, 0.4, 1.2], [120, 130, 140])
        elif model == "stall":
            put(f"{name} Counter", "Block", "Wood", [x, y + 1.0, z],
                [max(4.0, sx), 1.6, max(2.4, sz)], [142, 96, 58])
            put(f"{name} Awning", "Block", "SmoothPlastic", [x, y + 3.2, z],
                [max(4.6, sx * 1.1), 0.3, max(2.8, sz * 1.1)], [222, 96, 96])
            for pole in (-1, 1):
                put(f"{name} Pole {pole + 2}", "Cylinder", "Metal",
                    [x + pole * sx * 0.45, y + 1.7, z + sz * 0.42], [0.22, 3.4, 0.22], [96, 104, 116])
            for crate in range(2):
                put(f"{name} Produce Crate {crate + 1}", "Block", "Wood",
                    [x + (crate - 0.5) * sx * 0.35, y + 2.0, z - sz * 0.15],
                    [1.2, 0.6, 1.2], [166, 128, 84])
                put(f"{name} Produce {crate + 1}", "Ball", "SmoothPlastic",
                    [x + (crate - 0.5) * sx * 0.35, y + 2.5, z - sz * 0.15],
                    [1.0, 0.9, 1.0], [[226, 120, 84], [140, 190, 96]][crate % 2])
        elif model == "fence":
            span = max(4.0, sx)
            for post_index in range(4):
                px = x - span / 2 + span * post_index / 3
                put(f"{name} Post {post_index + 1}", "Block", "Wood", [px, y + 1.1, z],
                    [0.28, 2.2, 0.28], [116, 84, 54])
            for rail in (0.8, 1.7):
                put(f"{name} Rail {int(rail * 10)}", "Block", "Wood", [x, y + rail, z],
                    [span, 0.22, 0.22], [132, 96, 60])
        elif model == "rock":
            put(f"{name} Base", "Ball", "Slate", [x, y + sy * 0.3, z],
                [max(2.0, sx), max(1.2, sy * 0.6), max(2.0, sz)], tint(color, 0.82))
            for bump in range(3):
                put(f"{name} Stone {bump + 1}", "Ball", "Slate",
                    [x + (bump - 1) * 1.5, y + sy * 0.55, z + (1 if bump % 2 else -1) * 1.1],
                    [max(1.2, sx * 0.45), max(1.0, sy * 0.4), max(1.2, sz * 0.45)],
                    tint(color, 0.9 + bump * 0.05))
        elif model == "statue":
            put(f"{name} Plinth", "Block", "Concrete", [x, y + 0.8, z],
                [max(2.6, sx * 0.8), 1.6, max(2.6, sz * 0.8)], [150, 156, 164])
            put(f"{name} Figure", "Block", "SmoothPlastic", [x, y + 3.0, z],
                [max(1.2, sx * 0.35), 3.0, max(1.2, sz * 0.35)], color)
            put(f"{name} Head", "Ball", "SmoothPlastic", [x, y + 4.9, z],
                [1.1, 1.1, 1.1], tint(color, 1.08))
        elif model == "vehicle":
            put(f"{name} Body", "Block", "SmoothPlastic", [x, y + 1.2, z],
                [max(3.2, sx), 1.6, max(2.0, sz)], color)
            put(f"{name} Cabin", "Block", "Glass", [x, y + 2.3, z - sz * 0.05],
                [max(2.2, sx * 0.6), 1.2, max(1.6, sz * 0.8)], [150, 210, 235])
            for wheel in (-1, 1):
                for end in (-1, 1):
                    put(f"{name} Wheel {wheel + 2}{end + 2}", "Cylinder", "Slate",
                        [x + end * sx * 0.34, y + 0.5, z + wheel * sz * 0.52],
                        [0.9, 0.5, 0.9], [56, 62, 70])
        else:
            return False
        groups_made += 1
        return True

    def furnish_interior(name, x, y, z, sx, sy, sz, bottom, floor_y, ceiling_y, front, back, left, right, thickness, wall, wood, roof, accent):
        """Glass, plants and leaves so a finished building is not an empty box."""
        # A glass display case and an interior glass partition: the AI plan asks
        # for shops and houses with glass inside, so the build actually has it.
        add(f"{name} Glass Display Case", "Block", "Glass",
            [x - sx * 0.22, bottom + 1.5, z + sz * 0.2],
            [max(1.6, sx * 0.18), 2.4, max(1.0, sz * 0.12)], [150, 214, 238])
        add(f"{name} Glass Interior Partition", "Block", "Glass",
            [x + sx * 0.18, floor_y + max(1.4, sy * 0.34), z - sz * 0.18],
            [max(1.8, sx * 0.2), max(2.0, sy * 0.5), 0.14], [142, 206, 232])
        add(f"{name} Glass Pane Above Door", "Block", "Glass",
            [x, floor_y + max(1.2, sy * 0.3), front + thickness / 2],
            [max(1.2, sx * 0.12), max(0.8, sy * 0.12), 0.12], [146, 210, 236])
        # Potted plants on the floor and along the sill.
        for index, (px, pz) in enumerate(((x - sx * 0.32, z + sz * 0.28),
                                          (x + sx * 0.32, z + sz * 0.28))):
            add(f"{name} Interior Plant Pot {index + 1}", "Cylinder", "Concrete",
                [px, bottom + 0.7, pz], [1.1, 1.4, 1.1], [176, 104, 76])
            leaves(f"{name} Interior Plant {index + 1}", px, bottom + 1.4, pz,
                   max(1.1, min(2.2, sx * 0.1)), index + 1, 3)
        # Climbing leaves over the facade, hanging from the roof edge.
        for vine in range(3):
            vx = left + (right - left) * (vine + 1) / 4
            add(f"{name} Facade Vine {vine + 1}", "Block", "Grass",
                [vx, floor_y + max(1.2, sy * 0.28), front + thickness],
                [0.22, max(2.0, sy * 0.5), 0.22], leaf_greens[vine % len(leaf_greens)])
            add(f"{name} Facade Leaf {vine + 1}", "Ball", "Grass",
                [vx, floor_y + max(1.0, sy * 0.2), front + thickness],
                [0.9, 0.7, 0.5], leaf_greens[(vine + 2) % len(leaf_greens)])
        # A stepped gable roof: blocks that taper upward read as a real roof.
        steps = 4
        for step in range(steps):
            share = (steps - step) / steps
            add(f"{name} Gable Roof {step + 1}", "Block", "SmoothPlastic",
                [x, ceiling_y + 0.45 + step * max(0.5, sy * 0.055), z],
                [sx * 1.04 * share, max(0.4, sy * 0.05), sz * 1.04 * share],
                tint(roof, 0.96 + step * 0.03))
        add(f"{name} Roof Ridge Cap", "Block", "SmoothPlastic",
            [x, ceiling_y + 0.5 + steps * max(0.5, sy * 0.055), z],
            [max(1.4, sx * 0.12), max(0.5, sy * 0.06), max(1.0, sz * 0.1)], tint(roof, 1.1))
        add(f"{name} Chimney", "Block", "Brick",
            [x + sx * 0.3, ceiling_y + max(1.4, sy * 0.22), z - sz * 0.3],
            [max(1.2, sx * 0.1), max(2.4, sy * 0.34), max(1.2, sz * 0.1)], tint(wall, 0.9))
        add(f"{name} Window Box", "Block", "Wood",
            [x - sx * 0.26, bottom + max(1.4, sy * 0.24), front + thickness * 1.6],
            [max(1.4, sx * 0.16), 0.4, 0.6], wood)
        leaves(f"{name} Window Box Flowers", x - sx * 0.26,
               bottom + max(1.6, sy * 0.26), front + thickness * 1.6,
               max(0.8, min(1.4, sx * 0.07)), groups_made, 3)
        add(f"{name} Doorstep Plant", "Cylinder", "Concrete",
            [x + sx * 0.22, bottom + 0.6, front + 1.2], [1.0, 1.2, 1.0], [176, 104, 76])
        leaves(f"{name} Doorstep Leaves", x + sx * 0.22, bottom + 1.2, front + 1.2,
               max(0.9, min(1.6, sx * 0.08)), 2, 3)

    left_to_place = [prop for prop in keep_props
                     if normalize_model(prop.get("model")) in GROUP_MODELS
                     or (not normalize_model(prop.get("model")) and
                         normalize_model(prop.get("name")) in GROUP_MODELS)]
    for prop in left_to_place:
        made_before = groups_made
        if build_group(prop):
            # The anchor itself is replaced by its group, not kept as a plain block.
            keep_props = [item for item in keep_props if item is not prop]
            expanded = [item for item in expanded if item is not prop]
            used_names.discard(str(prop.get("name", "")).casefold())
        groups_made = made_before

    for building in building_cores:
        name = building["name"]
        x, y, z = building["position"]
        sx, sy, sz = building["size"]
        color = building["color"]
        wall = tint(color, 0.72)
        roof = tint(color, 1.16)
        glass = [135, 213, 238]
        wood = [103, 69, 47]
        thickness = max(0.6, min(1.1, min(sx, sz) * 0.055))
        left, right = x - sx / 2 + thickness, x + sx / 2 - thickness
        front, back = z + sz / 2 - thickness / 2, z - sz / 2 + thickness / 2
        bottom, top = max(0.2, y - sy / 2), y + sy / 2
        floor_y, ceiling_y = bottom + thickness, top - thickness
        wall_height = max(3.0, ceiling_y - floor_y)
        wall_center = floor_y + wall_height / 2
        add(f"{name} Interior Floor", "Block", "Concrete", [x, bottom + thickness / 2, z],
            [sx - thickness, thickness, sz - thickness], tint(wall, 0.88))
        add(f"{name} Furnished Roof", "Block", "SmoothPlastic", [x, top - thickness / 2, z],
            [sx, thickness, sz], roof)
        add(f"{name} Rear Wall", "Block", "Brick", [x, wall_center, back], [sx, wall_height, thickness], wall)
        add(f"{name} Left Wall", "Block", "Brick", [left, wall_center, z], [thickness, wall_height, sz], wall)
        add(f"{name} Right Wall", "Block", "Brick", [right, wall_center, z], [thickness, wall_height, sz], wall)

        inner_width = max(4.0, right - left - thickness * 2)
        door_width = min(3.2, max(1.5, inner_width * 0.19))
        window_width = min(3.4, max(1.5, inner_width * 0.16))
        door_height = min(wall_height * 0.8, 5.4)
        window_height = min(wall_height * 0.42, 3.0)
        opening_data = [
            (x - inner_width * 0.29, window_width, "window"),
            (x, door_width, "door"),
            (x + inner_width * 0.29, window_width, "window"),
        ]
        spans = []
        cursor = left
        for center, width, _kind in opening_data:
            span_right = center - width / 2
            if span_right - cursor >= 0.6:
                spans.append((cursor, span_right))
            cursor = center + width / 2
        if right - cursor >= 0.6:
            spans.append((cursor, right))
        for index, (span_left, span_right) in enumerate(spans, 1):
            add(f"{name} Front Pier {index}", "Block", "Brick",
                [(span_left + span_right) / 2, wall_center, front], [span_right - span_left, wall_height, thickness], wall)
        for center, width, kind in opening_data:
            if kind == "door":
                add(f"{name} Wood Entrance Door", "Block", "Wood",
                    [center, floor_y + door_height / 2, front + thickness / 2], [width * 0.92, door_height, 0.3], wood)
                add(f"{name} Door Header", "Block", "Brick",
                    [center, floor_y + (door_height + wall_height) / 2, front], [width, max(0.6, wall_height - door_height), thickness], wall)
            else:
                sill_y = floor_y + min(1.6, wall_height * 0.22)
                pane_y = sill_y + window_height / 2
                add(f"{name} Window Sill", "Block", "SmoothPlastic", [center, sill_y, front + thickness / 2],
                    [width + 0.5, 0.35, 0.3], roof)
                add(f"{name} Glass Window", "Block", "Glass", [center, pane_y, front + thickness / 2],
                    [width, window_height, 0.14], glass)
                for side, dx in (("Left", -width / 2), ("Right", width / 2)):
                    add(f"{name} {side} Window Frame", "Block", "Wood",
                        [center + dx, pane_y, front + thickness / 2], [0.18, window_height + 0.3, 0.22], wood)
                add(f"{name} Window Top Rail", "Block", "Wood", [center, pane_y + window_height / 2, front + thickness / 2],
                    [width + 0.2, 0.18, 0.22], wood)

        inner_z = z - sz * 0.08
        rug_y = bottom + thickness + 0.18
        # Dense, hollow interior: rug + layered rugs, counter, tables, shelves, cabinets, sofas, bookcases — many times inside so it reads as fully furnished.
        add(f"{name} Welcome Rug", "Block", "SmoothPlastic", [x, rug_y, inner_z],
            [max(2, sx * 0.42), 0.22, max(2, sz * 0.28)], accent_color(plan, color))
        add(f"{name} Second Rug Layer", "Block", "SmoothPlastic", [x, rug_y + 0.04, inner_z - sz * 0.02],
            [max(1.5, sx * 0.28), 0.18, max(1.5, sz * 0.18)], tint(accent_color(plan, color), 1.08))
        add(f"{name} Front Counter", "Block", "Wood", [x, bottom + 1.0, z + sz * 0.12],
            [max(2, sx * 0.36), 1.4, 1.0], wood)
        for side, sign in (("West", -1), ("East", 1)):
            table_x = x + sign * sx * 0.25
            add(f"{name} {side} Table", "Block", "Wood", [table_x, bottom + 1.05, inner_z],
                [max(1.5, sx * 0.16), 1.1, max(1.5, sz * 0.12)], tint(wood, 1.12))
            add(f"{name} {side} Chair", "Block", "SmoothPlastic", [table_x, bottom + 0.55, inner_z + sz * 0.13],
                [1.0, 1.0, 1.0], roof)
            add(f"{name} {side} Chair Back", "Block", "Wood", [table_x, bottom + 1.15, inner_z + sz * 0.18],
                [1.0, 0.55, 0.22], wood)
            add(f"{name} {side} Wall Shelf", "Block", "Wood", [x + sign * sx * 0.32, bottom + sy * 0.45, back + thickness],
                [max(1.5, sx * 0.15), 0.55, 1.0], wood)
            # Shelf decor: books / vases on each shelf
            add(f"{name} {side} Shelf Books", "Block", "SmoothPlastic",
                [x + sign * sx * 0.32, bottom + sy * 0.45 + 0.45, back + thickness],
                [max(1.0, sx * 0.12), 0.5, 0.7], [196, 96, 92] if sign < 0 else [92, 132, 196])
            add(f"{name} {side} Table Lamp Base", "Cylinder", "Metal",
                [table_x, bottom + 1.75, inner_z], [0.42, 0.7, 0.42], [176, 178, 184])
            add(f"{name} {side} Table Lamp Shade", "Ball", "Neon",
                [table_x, bottom + 2.25, inner_z], [0.85, 0.65, 0.85], [255, 232, 168])
            expanded[-1]["light"] = {"kind": "Point", "color": [255, 232, 168], "brightness": 1.4, "range": 18.0, "angle": 90.0}
        # Ceiling light is now a real PointLight — the warm decorative glow that makes the hollow shell readable inside.
        add(f"{name} Ceiling Light", "Ball", "Neon", [x, ceiling_y - 0.35, z], [1.2, 0.75, 1.2], [255, 236, 190])
        expanded[-1]["light"] = {"kind": "Point", "color": [255, 236, 190], "brightness": 2.8, "range": 32.0, "angle": 90.0}
        # Hanging pendant over counter
        add(f"{name} Hanging Pendant", "Ball", "Neon", [x, ceiling_y - 1.2, z + sz * 0.08], [0.9, 0.9, 0.9], [255, 226, 156])
        expanded[-1]["light"] = {"kind": "Point", "color": [255, 226, 156], "brightness": 1.8, "range": 22.0, "angle": 90.0}
        add(f"{name} Pendant Cord", "Cylinder", "Metal", [x, ceiling_y - 0.65, z + sz * 0.08], [0.12, 1.1, 0.12], [96, 104, 116])
        # Wall sconces — decorative lights on left/right interior walls, many times
        for side, sign in (("West", -1), ("East", 1)):
            sconce_x = x + sign * (sx * 0.43)
            add(f"{name} Wall Sconce {side}", "Ball", "Neon", [sconce_x, floor_y + wall_height * 0.62, z - sz * 0.12], [0.7, 0.7, 0.7], [255, 220, 160])
            expanded[-1]["light"] = {"kind": "Point", "color": [255, 220, 160], "brightness": 1.2, "range": 16.0, "angle": 90.0}
            add(f"{name} Sconce Plate {side}", "Cylinder", "Metal", [sconce_x - sign * 0.18, floor_y + wall_height * 0.62, z - sz * 0.12], [0.5, 0.5, 0.5], [120, 130, 140])
        # Fairy string lights across the ceiling perimeter — many small Point lights for a festive hollow house
        for idx in range(3):
            fx = x - sx * 0.32 + idx * (sx * 0.64 / 2)
            add(f"{name} Fairy Light {idx + 1}", "Ball", "Neon", [fx, ceiling_y - 0.18, z + sz * 0.18], [0.45, 0.45, 0.45], [255, 228, 168])
            expanded[-1]["light"] = {"kind": "Point", "color": [255, 228, 168], "brightness": 0.9, "range": 12.0, "angle": 90.0}
        # Corner floor lamp
        add(f"{name} Corner Floor Lamp Base", "Cylinder", "Metal", [x - sx * 0.35, bottom + 1.0, z - sz * 0.32], [0.35, 2.0, 0.35], [74, 86, 103])
        add(f"{name} Corner Floor Lamp Shade", "Cylinder", "Neon", [x - sx * 0.35, bottom + 2.2, z - sz * 0.32], [1.0, 0.7, 1.0], [255, 236, 178])
        expanded[-1]["light"] = {"kind": "Point", "color": [255, 236, 178], "brightness": 1.6, "range": 20.0, "angle": 90.0}
        # Dense extra furniture to make it fully furnished: cabinets, sofa, bookcase, sideboard, many plants
        add(f"{name} Back Wall Cabinet", "Block", "Wood", [x, bottom + 1.1, back + 1.0], [max(2.5, sx * 0.32), 1.8, 1.1], wood)
        add(f"{name} Back Wall Cabinet Top", "Block", "SmoothPlastic", [x, bottom + 2.05, back + 1.0], [max(2.6, sx * 0.33), 0.2, 1.2], tint(wood, 1.12))
        add(f"{name} Lounge Sofa", "Block", "SmoothPlastic", [x + sx * 0.28, bottom + 0.85, z - sz * 0.22], [max(2.2, sx * 0.22), 1.1, max(1.8, sz * 0.18)], [140, 160, 190])
        add(f"{name} Sofa Cushion Left", "Block", "SmoothPlastic", [x + sx * 0.28 - 0.6, bottom + 1.15, z - sz * 0.22], [0.7, 0.5, 1.0], [176, 190, 220])
        add(f"{name} Sofa Cushion Right", "Block", "SmoothPlastic", [x + sx * 0.28 + 0.6, bottom + 1.15, z - sz * 0.22], [0.7, 0.5, 1.0], [176, 190, 220])
        add(f"{name} Bookshelf Tall", "Block", "Wood", [left + 0.9, bottom + sy * 0.32, z - sz * 0.18], [0.9, max(3.0, sy * 0.68), max(2.0, sz * 0.22)], [150, 112, 78])
        for shelf_i in range(3):
            add(f"{name} Bookshelf Books {shelf_i + 1}", "Block", "SmoothPlastic",
                [left + 0.9, bottom + 1.0 + shelf_i * 1.1, z - sz * 0.18], [0.7, 0.45, 1.2],
                [[188, 92, 88], [92, 132, 188], [214, 176, 96]][shelf_i])
        add(f"{name} Sideboard", "Block", "Wood", [x - sx * 0.28, bottom + 0.95, z + sz * 0.32], [max(1.8, sx * 0.18), 1.0, 1.0], tint(wood, 0.92))
        add(f"{name} Sideboard Lamp", "Ball", "Neon", [x - sx * 0.28, bottom + 1.75, z + sz * 0.32], [0.65, 0.65, 0.65], [255, 232, 168])
        expanded[-1]["light"] = {"kind": "Point", "color": [255, 232, 168], "brightness": 1.1, "range": 14.0, "angle": 90.0}
        # More plants inside — many times
        for p_idx, (px, pz) in enumerate(((x - sx * 0.32, z - sz * 0.28), (x + sx * 0.32, z - sz * 0.28), (x, z - sz * 0.32))):
            add(f"{name} Indoor Plant Pot Extra {p_idx + 1}", "Cylinder", "Concrete", [px, bottom + 0.7, pz], [0.9, 1.2, 0.9], [176, 104, 76])
            leaves(f"{name} Indoor Plant Extra {p_idx + 1}", px, bottom + 1.35, pz, max(1.0, min(1.8, sx * 0.09)), p_idx + 5, 3)
        # Wall art / posters inside
        for art_i, col in enumerate(([236, 176, 96], [140, 196, 236])):
            add(f"{name} Wall Art {art_i + 1}", "Block", "SmoothPlastic",
                [x + (-1 if art_i == 0 else 1) * sx * 0.38, floor_y + wall_height * 0.58, back + 0.18],
                [1.6, 1.2, 0.12], col)
        add(f"{name} Entry Step", "Block", "Concrete", [x, bottom + 0.25, front + 0.9], [door_width + 1, 0.5, 1.4], tint(wall, 1.12))
        add(f"{name} Roof Sign", "Block", "Neon", [x, min(249, top + 1.1), z + sz * 0.25],
            [max(2, sx * 0.35), 0.8, 0.5], accent_color(plan, color))
        add(f"{name} Roof Trim Front", "Block", "SmoothPlastic", [x, top + 0.3, z + sz * 0.49],
            [sx, 0.45, 0.55], roof)
        # Glass inside, potted plants, facade vines and a real gable roof.
        furnish_interior(name, x, y, z, sx, sy, sz, bottom, floor_y, ceiling_y,
                         front, back, left, right, thickness, wall, wood, roof,
                         accent_color(plan, color))
        # Additional decorative ceiling cove light strip inside — warm glow along the ceiling edge
        add(f"{name} Cove Light Strip", "Block", "Neon", [x, ceiling_y - 0.14, z], [sx * 0.88, 0.14, sz * 0.88], [255, 228, 168])
        expanded[-1]["light"] = {"kind": "Point", "color": [255, 228, 168], "brightness": 1.0, "range": 26.0, "angle": 90.0}

    # Build a walkable, furnished central plaza instead of leaving the cast on an empty patch.
    paving_material = "Slate" if family in {"castle", "space", "snow"} else "Concrete"
    paving = [186, 195, 202] if family == "snow" else [146, 153, 164]
    paving_alt = [min(255, c + 18) for c in paving]

    def plaza_clear(x, z, half_x=3.5, half_z=3.5):
        return not any(abs(x - b["position"][0]) < b["size"][0] / 2 + half_x
                       and abs(z - b["position"][2]) < b["size"][2] / 2 + half_z
                       for b in building_cores)

    plaza_index = 0
    for z in (4, 12, 20, 28, 36, 44, 52):
        for x in (-28, -20, -12, -4, 4, 12, 20, 28):
            if plaza_clear(x, z, 3.8, 3.8):
                tile_color = paving if plaza_index % 3 else paving_alt
                add("Plaza Paving Tile", "Block", paving_material, [x, 0.08, z], [7.8, 0.16, 7.8], tile_color)
                plaza_index += 1

    # Benches, planted beds and lamp posts dress the plaza perimeter without blocking the cast lane.
    for side, sign in (("West", -1), ("East", 1)):
        for z in (14, 38):
            # Just outside the cast lane: a bench back at x=16 stood between the
            # camera and the faces the close-ups are framed on.
            x = sign * 22
            if not plaza_clear(x, z, 3.0, 2.2):
                continue
            add(f"{side} Plaza Bench Seat", "Block", "Wood", [x, 0.72, z], [5.5, 0.45, 1.5], [142, 91, 56])
            add(f"{side} Plaza Bench Back", "Block", "Wood", [x, 1.45, z - 0.55], [5.5, 1.05, 0.28], [112, 72, 48])
            for leg_x in (x - 2.15, x + 2.15):
                add(f"{side} Plaza Bench Leg", "Block", "Metal", [leg_x, 0.35, z], [0.28, 0.75, 1.2], [72, 83, 97])
        for z in (6, 50):
            x = sign * 24
            if plaza_clear(x, z, 1.8, 1.8):
                add(f"{side} Plaza Lamp Post", "Cylinder", "Metal", [x, 3.4, z], [0.48, 6.8, 0.48], [74, 86, 103])
                add(f"{side} Plaza Lantern", "Ball", "Neon", [x, 6.9, z], [1.1, 1.1, 1.1], accent)
        for z in (2, 50):
            x = sign * 25
            if plaza_clear(x, z, 2.0, 2.0):
                add(f"{side} Plaza Flower Bed", "Block", "Concrete", [x, 0.48, z], [4.2, 0.9, 3.2], [115, 127, 137])
                for offset, bloom in ((-1.15, accent), (0, primary), (1.15, [241, 158, 105])):
                    add(f"{side} Plaza Flower", "Ball", "SmoothPlastic", [x + offset, 1.12, z], [1.25, 1.15, 1.25], bloom)

    motif_palette = {
        "reef": [("Sea Floor Stone", "Ball", "Slate", [12, 2, 10], base), ("Coral Stem", "Block", "Neon", [1.2, 5, 1.2], primary),
                 ("Coral Bloom", "Ball", "SmoothPlastic", [3.6, 3.6, 3.6], [245, 125, 185]), ("Kelp Blade", "Block", "Grass", [0.8, 4.2, 0.8], [65, 155, 90]),
                 ("Pearl Light", "Ball", "Neon", [1.5, 1.5, 1.5], accent), ("Reef Rock", "Ball", "Slate", [4.5, 2.5, 3.5], tint(base, 0.8)),
                 ("Anemone", "Ball", "SmoothPlastic", [2.5, 2.5, 2.5], accent), ("Coral Marker", "Block", "SmoothPlastic", [1, 3, 1], primary)],
        "space": [("Landing Pad", "Block", "Slate", [12, 0.8, 12], base), ("Star Crystal", "Block", "Neon", [2, 7, 2], accent),
                  ("Moon Rock", "Ball", "Slate", [4, 3, 4], tint(base, 0.78)), ("Beacon", "Block", "Neon", [1.5, 5, 1.5], primary),
                  ("Orbit Orb", "Ball", "Neon", [2, 2, 2], accent), ("Solar Panel", "Block", "Metal", [5, 0.5, 3], [75, 95, 150]),
                  ("Signal Stone", "Block", "SmoothPlastic", [2, 3, 2], primary), ("Comet Fragment", "Ball", "SmoothPlastic", [2.6, 1.6, 2.2], accent)],
        "snow": [("Snow Mound", "Ball", "SmoothPlastic", [10, 2, 8], base), ("Ice Spire", "Block", "Glass", [1.5, 6, 1.5], accent),
                 ("Pine Trunk", "Block", "Wood", [1.2, 4, 1.2], [100, 73, 52]), ("Pine Crown", "Ball", "Grass", [5, 5, 5], primary),
                 ("Frost Orb", "Ball", "Neon", [1.6, 1.6, 1.6], accent), ("Frozen Rock", "Ball", "Slate", [3.5, 2, 3], [180, 215, 235]),
                 ("Snow Lantern", "Block", "Neon", [1, 3, 1], accent), ("Ice Marker", "Block", "Glass", [1.2, 3.5, 1.2], primary)],
        "forest": [("Garden Stone", "Ball", "Slate", [7, 1.5, 5], base), ("Old Tree Trunk", "Block", "Wood", [1.4, 5, 1.4], [108, 77, 49]),
                   ("Leaf Canopy", "Ball", "Grass", [6, 5, 6], primary), ("Flower Patch", "Ball", "SmoothPlastic", [3, 1.2, 3], accent),
                   ("Mushroom", "Block", "Wood", [1, 1.8, 1], [230, 100, 90]), ("Forest Lantern", "Block", "Neon", [1, 3, 1], accent),
                   ("Fallen Log", "Block", "Wood", [5, 1, 1], [125, 86, 53]), ("Moss Stone", "Ball", "Grass", [3.2, 2, 3], [70, 145, 82])],
        "desert": [("Sandstone Base", "Block", "Concrete", [10, 1, 10], base), ("Dune Rock", "Ball", "Slate", [5, 2.5, 4], tint(base, 1.16)),
                   ("Sun Obelisk", "Block", "Concrete", [1.8, 6, 1.8], primary), ("Oasis Water", "Ball", "Glass", [4, 1.2, 4], [65, 180, 195]),
                   ("Torch Pillar", "Block", "Neon", [1, 4, 1], accent), ("Palm Trunk", "Block", "Wood", [1.2, 5, 1.2], [120, 83, 48]),
                   ("Palm Crown", "Ball", "Grass", [4.5, 2, 4.5], primary), ("Ancient Marker", "Block", "Brick", [2, 3, 1], accent)],
        "castle": [("Stone Paving", "Block", "Slate", [10, 0.8, 10], base), ("Castle Column", "Block", "Concrete", [1.5, 6, 1.5], primary),
                   ("Banner Post", "Block", "Wood", [0.8, 5, 0.8], [105, 78, 50]), ("Royal Banner", "Block", "Neon", [3.5, 3, 0.4], accent),
                   ("Guarding Orb", "Ball", "Neon", [1.5, 1.5, 1.5], accent), ("Stone Block", "Block", "Slate", [3, 2, 3], tint(base, 0.78)),
                   ("Wall Torch", "Block", "Neon", [1, 3, 1], accent), ("Crown Marker", "Block", "SmoothPlastic", [2.5, 3, 2.5], primary)],
        "town": [("Planter", "Block", "Concrete", [7, 1.2, 7], base), ("Street Tree Trunk", "Block", "Wood", [1.2, 4.5, 1.2], [110, 77, 49]),
                 ("Street Tree Crown", "Ball", "Grass", [5, 5, 5], primary), ("Bench", "Block", "Wood", [6, 1, 2], [145, 99, 62]),
                 ("Street Lamp", "Block", "Neon", [1.1, 5, 1.1], accent), ("Shop Sign", "Block", "SmoothPlastic", [4, 2, 0.5], primary),
                 ("Welcome Bollard", "Block", "Concrete", [1.2, 2.5, 1.2], accent), ("Flower Pot", "Ball", "SmoothPlastic", [2.2, 2.2, 2.2], accent)],
        "storybook": [("Story Stone", "Ball", "Slate", [8, 2, 7], base), ("Wonder Pillar", "Block", "SmoothPlastic", [1.5, 5, 1.5], primary),
                      ("Magic Orb", "Ball", "Neon", [2.2, 2.2, 2.2], accent), ("Colorful Tree", "Block", "Wood", [1.2, 4, 1.2], [112, 78, 48]),
                      ("Tree Crown", "Ball", "Grass", [5, 4.5, 5], primary), ("Story Bench", "Block", "Wood", [5, 1, 2], [145, 99, 62]),
                      ("Story Lantern", "Block", "Neon", [1, 3.2, 1], accent), ("Wonder Marker", "Ball", "SmoothPlastic", [2.5, 2.5, 2.5], accent)],
    }[family]
    base_motif_offsets = [(0, 0, 0), (-5, -3, 0), (5, -3, 0), (-4, 4, 0), (4, 4, 0), (0, -5, 0), (0, 3, 0), (0, 0, 5)]
    # Extra rings of themed clusters let one site carry several aligned motif
    # groups, so 5-10x denser worlds stay evenly spread instead of stacking.
    extra_rings = [
        [(-7, 0, 0), (7, 0, 0), (0, 7, 0), (0, -7, 0), (-6, -6, 0), (6, -6, 0), (-6, 6, 0), (6, 6, 0)],
        [(-9, 2, 0), (9, 2, 0), (-2, 9, 0), (2, -9, 0), (-8, -2, 0), (8, -2, 0), (-2, -8, 0), (2, 8, 0)],
        [(-11, -4, 0), (11, -4, 0), (-4, 11, 0), (4, -11, 0), (-10, 5, 0), (10, 5, 0), (5, -10, 0), (-5, 10, 0)],
    ]
    motif_offsets = list(base_motif_offsets)
    for ring in extra_rings:
        motif_offsets.extend(ring)
    # 13x13, 40-stud-spaced motif sites provide enough distinct clusters for the
    # requested 3x world-detail target without piling geometry near spawn.
    x_sites = list(range(-240, 241, 40))
    z_sites = list(range(-240, 241, 40))
    candidate_sites = [
        (x, z) for z in z_sites for x in x_sites
        if not (-35 <= x <= 35 and -2 <= z <= 62)
        and not any(abs(x - bx) < max(18, b["size"][0] / 2 + 10)
                    and abs(z - bz) < max(18, b["size"][2] / 2 + 10)
                    for b in building_cores for bx, bz in [(b["position"][0], b["position"][2])])
    ]
    # Farthest-point ordering spreads theme clusters across the full world rather
    # than filling only the first few rows of the grid when the Part target is met.
    site_order = []
    remaining = list(candidate_sites)
    while remaining:
        if not site_order:
            selected = min(remaining, key=lambda site: (site[0] ** 2 + (site[1] - 24) ** 2, site[1], site[0]))
        else:
            selected = max(remaining, key=lambda site: (min((site[0] - old[0]) ** 2 + (site[1] - old[1]) ** 2
                                                             for old in site_order), -site[1], -site[0]))
        site_order.append(selected)
        remaining.remove(selected)

    scale_variants = (0.84, 1.0, 1.12)
    tint_variants = (0.88, 1.0, 1.10)
    for x, z in site_order:
        if len(expanded) >= target_props:
            break
        site_id = f"{x + 250:03d}-{z + 250:03d}"
        for motif_index, (dx, dz, _dy) in enumerate(motif_offsets):
            # Cycle the palette across every offset ring so a single site can
            # carry several aligned, tinted motif groups instead of only eight.
            label, shape, material, size, color = motif_palette[motif_index % len(motif_palette)]
            lower_label = label.casefold()
            lift = (4.0 if any(word in lower_label for word in ("crown", "canopy")) else
                    2.0 if any(word in lower_label for word in ("orb", "bloom", "anemone", "flower")) else
                    0.7 if any(word in lower_label for word in ("stem", "spire", "blade", "pillar", "beacon", "post", "column", "obelisk", "lantern")) else 0.0)
            ring = motif_index // len(motif_palette)
            variant = (x // 55 + z // 55 + motif_index + ring) % len(scale_variants)
            scale_factor = scale_variants[variant]
            # Rings sit inside one 40-stud site, so extra rings are capped to a
            # 6-stud footprint. That keeps every motif group aligned and
            # non-overlapping instead of z-fighting with its neighbour.
            footprint_cap = 12.0 if ring == 0 else 6.0
            varied_size = [round(max(0.5, min(footprint_cap, dimension * scale_factor)), 2)
                           for dimension in size]
            varied_color = tint(color, tint_variants[(variant + 1) % len(tint_variants)])
            position = [x + dx, varied_size[1] / 2 + lift, z + dz]
            add(f"{label} Site {site_id}", shape, material, position, varied_size, varied_color)
            if len(expanded) >= target_props:
                break

    if len(expanded) < target_props:
        raise ValueError(f"theme expansion created only {len(expanded)} props; expected {target_props}")
    return {**plan, "props": expanded}


def accent_color(plan, fallback):
    ambient = plan.get("ambient_color") or fallback
    return [max(0, min(255, round((int(channel) + int(fallback[index])) / 2)))
            for index, channel in enumerate(ambient)]


def validate(plan, duration=90, usernames=(), min_props=16, visual_request=""):
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

    MIN_LUMINANCE = 104

    def visible_prop_color(value, default):
        """Lift dark map colors so nothing renders as an unlit black slab in 3D."""
        rgb = list(color(value, default))
        luminance = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
        if luminance < MIN_LUMINANCE:
            target = [176, 186, 200]
            blend = min(1.0, (MIN_LUMINANCE - luminance) / max(1, MIN_LUMINANCE))
            rgb = [round(channel * (1 - blend * 0.9) + target[i] * (blend * 0.9)) for i, channel in enumerate(rgb)]
        return rgb

    # Everything snaps to a 0.5-stud grid: coplanar faces then line up exactly
    # instead of flickering/z-fighting, which is what "not aligned" looked like.
    # Positions must keep their sign - clamping them at +0.5 moved every prop with
    # a negative X or Z onto the origin, so whole worlds collapsed into one pile of
    # blocks around the cast. Only a size has a 0.5 minimum.
    def align(value, minimum=None):
        snapped = round(float(value) / 0.5) * 0.5
        if minimum is not None:
            snapped = max(minimum, snapped)
        return round(snapped, 2)

    clean_props = []
    unique_prop_names = set()
    for index, prop in enumerate(props):
        if not isinstance(prop, dict):
            raise ValueError("every map prop must be an object")
        # Models drift into their own key names ("type" instead of "shape",
        # lowercase "brick", "dimensions"). Accept the aliases instead of throwing
        # away a blueprint the model spent many minutes writing.
        raw_shape = prop.get("shape", prop.get("type", prop.get("part_type", prop.get("partType"))))
        raw_material = prop.get("material", prop.get("Material"))
        shape = normalize_shape(raw_shape, "Block")
        material = normalize_material(raw_material, "SmoothPlastic")
        pos = prop.get("position", prop.get("Position"))
        size = prop.get("size", prop.get("dimensions", prop.get("Dimension")))
        if (not isinstance(pos, list) or len(pos) != 3
                or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in pos)
                or not -250 <= pos[0] <= 250 or not 0 <= pos[1] <= 250
                or not -250 <= pos[2] <= 250):
            raise ValueError("prop position must use X/Z from -250 to 250 and a nonnegative Y height up to 250")
        if (not isinstance(size, list) or len(size) != 3
                or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not 0.5 <= v <= 64 for v in size)):
            raise ValueError("prop size must be three dimensions from 0.5 to 64")
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
        clean_prop = {
            "name": prop_name, "shape": shape, "material": material,
            "position": [align(value) for value in pos],
            "size": [align(value, 0.5) for value in size],
            "color": visible_prop_color(prop.get("color"), [120, 145, 180]),
            "physics": ("dynamic" if prop.get("physics") == "dynamic" and shape in {"Block", "Ball"}
                        and max(float(v) for v in size) <= 12 else "static"),
        }
        # Keep the declared model so the expansion step can build a whole house,
        # tree, bench or stall from one anchor instead of a bare block.
        if prop.get("shell"):
            # Floor / walls / ceiling: the review pass must never delete these.
            clean_prop["shell"] = True
        model = normalize_model(prop.get("model", prop.get("kind")))
        if model:
            clean_prop["model"] = model
        light = normalize_light(prop.get("light", prop.get("lights")))
        if light:
            clean_prop["light"] = light
        effect = normalize_effect(prop.get("effect", prop.get("particles", prop.get("fx"))))
        if effect:
            clean_prop["effect"] = effect
        clean_props.append(clean_prop)
    # A hundred dynamic lights would black out the software renderer, so only the
    # first MAX_LIGHTS keep their light; the rest stay ordinary Parts. Effects are
    # cheap but each one is a particle system, so they are capped too.
    MAX_LIGHTS, MAX_EFFECTS = 40, 60
    lights = effects = 0
    for prop in clean_props:
        if "light" in prop:
            lights += 1
            if lights > MAX_LIGHTS:
                prop.pop("light")
        if "effect" in prop:
            effects += 1
            if effects > MAX_EFFECTS:
                prop.pop("effect")
    normalized_plan = {
        "name": name, "theme": theme,
        "ground_color": color(plan.get("ground_color"), [88, 166, 91]),
        "ground_material": normalize_ground_material(plan.get("ground_material", plan.get("groundMaterial")), "Grass"),
        "ambient_color": color(plan.get("ambient_color", plan.get("ambient_light")), [185, 205, 225]),
        "props": clean_props,
        "camera_shots": normalize_camera_shots(plan.get("camera_shots"), duration, usernames),
        "face_expressions": normalize_face_expressions(plan.get("face_expressions"), duration, usernames),
        "character_placements": normalize_character_placements(plan.get("character_placements"), usernames, visual_request),
    }
    global_hour = canonical_time_of_day(plan.get("time_of_day"))
    if global_hour:
        normalized_plan["time_of_day"] = global_hour
    return normalized_plan


# ---------------------------------------------------------------------------
# INTERIOR MODE
#
# A story set in a cramped bedroom was rendered as an open 640-stud world with a
# workshop wall 100 studs away: no room, no walls, no ceiling - just outside.
# When scene_mode says the scene is indoors, the anchors are pulled into a real
# room, furniture-sized, and a deterministic shell (floor, four walls, ceiling,
# door, window, skirting) is added so the video always shows an inside.
# ---------------------------------------------------------------------------
ROOM_CENTRE_Z = 24.0
INTERIOR_MAX_PROPS = 900


def interior_room(size="small"):
    """(width, depth, height) of the room the cast stands in."""
    return {"tiny": (26.0, 26.0, 10.0), "small": (34.0, 34.0, 11.0),
            "medium": (44.0, 44.0, 13.0)}.get(str(size).lower(), (34.0, 34.0, 11.0))


def fit_anchors_to_room(anchors, room):
    """Pull every AI anchor inside the room and shrink buildings to furniture."""
    width, depth, height = room
    half_x, half_z = width / 2 - 2.0, depth / 2 - 2.0
    z_min, z_max = ROOM_CENTRE_Z - half_z, ROOM_CENTRE_Z + half_z
    fitted = []
    for anchor in anchors:
        prop = dict(anchor)
        sx, sy, sz = (list(prop.get("size") or [4, 4, 4]) + [4, 4, 4])[:3]
        # A 34-stud "workshop" is not furniture: cap it, keep its proportions.
        cap_x, cap_z = width * 0.45, depth * 0.45
        scale = min(1.0, cap_x / max(1.0, float(sx)), cap_z / max(1.0, float(sz)))
        sx, sz = round(max(1.0, float(sx) * scale) * 2) / 2, round(max(1.0, float(sz) * scale) * 2) / 2
        sy = round(min(float(sy), height - 2.0) * 2) / 2
        x = float((prop.get("position") or [0, 0, 0])[0])
        z = float((prop.get("position") or [0, 0, 0])[2])
        # Keep the cast lane (the close-up space in front of the cast) clear.
        if abs(x) < 20 and 4 <= z <= 54:
            x = half_x if x >= 0 else -half_x
        x = max(-half_x, min(half_x, x))
        z = max(z_min, min(z_max, z))
        prop["position"] = [round(x * 2) / 2, round(max(0.5, min(height / 2, abs(sy) / 2)) * 2) / 2,
                            round(z * 2) / 2]
        prop["size"] = [sx, sy, sz]
        prop["physics"] = "static"
        # A building model inside a room would expand into walls and a roof.
        if str(prop.get("model") or "").lower() in BUILDING_MODELS:
            prop["model"] = "furniture"
        fitted.append(prop)
    return fitted


def room_shell(plan, room):
    """Floor, ceiling, four walls with a real doorway and window, skirting, rug."""
    width, depth, height = room
    thickness = 0.5
    half_x, half_z = width / 2, depth / 2
    z0 = ROOM_CENTRE_Z
    floor_color = list(plan.get("floor_color") or [156, 120, 86])
    wall_color = list(plan.get("wall_color") or [206, 196, 178])
    accent = list(plan.get("accent_color") or [90, 140, 200])
    sky = list(plan.get("ground_color") or [150, 190, 225])
    used = {str(prop.get("name", "")).casefold() for prop in plan.get("props", [])}
    parts = []

    def add(name, shape, material, position, size, color):
        base, suffix = name, 2
        while name.casefold() in used:
            name = f"{base} {suffix}"
            suffix += 1
        used.add(name.casefold())
        parts.append({
            "name": name, "shape": shape, "material": material,
            "position": [round(v * 2) / 2 for v in position],
            "size": [round(max(0.5, v) * 2) / 2 for v in size],
            "color": [int(c) for c in color], "physics": "static", "shell": True,
        })

    # Floor top sits at Y=0.2 so the cast stands on it and rugs can sit on top.
    add("Room Floor", "Block", "Wood", [0, 0.1, z0], [width, 0.2, depth], floor_color)
    add("Room Ceiling", "Block", "SmoothPlastic", [0, height + thickness / 2, z0],
        [width, thickness, depth], [232, 228, 220])
    back_z = z0 + half_z + thickness / 2
    front_z = z0 - half_z - thickness / 2
    # Side walls are inset by half a stud so the corners do not overlap the
    # back/front walls (the review pass drops any part that does).
    add("Room Wall Left", "Block", "SmoothPlastic", [-half_x - thickness / 2, height / 2, z0],
        [thickness, height, depth - 1.0], wall_color)
    add("Room Wall Right", "Block", "SmoothPlastic", [half_x + thickness / 2, height / 2, z0],
        [thickness, height, depth - 1.0], wall_color)
    # Back wall with a window opening: two side pieces, a header and a sill piece.
    window_width, window_height = min(9.0, width * 0.4), min(5.0, height * 0.45)
    window_centre_y = height * 0.62
    shoulder = max(1.0, (width - window_width) / 2)
    for index, offset in enumerate((-(window_width / 2 + shoulder / 2),
                                    window_width / 2 + shoulder / 2)):
        add(f"Room Wall Back {index + 1}", "Block", "SmoothPlastic",
            [offset, height / 2, back_z], [shoulder, height, thickness], wall_color)
    add("Room Wall Back Header", "Block", "SmoothPlastic",
        [0, window_centre_y + window_height / 2 + (height - window_centre_y - window_height / 2) / 2,
         back_z],
        [window_width, max(1.0, height - window_centre_y - window_height / 2), thickness], wall_color)
    add("Room Wall Back Sill", "Block", "SmoothPlastic",
        [0, (window_centre_y - window_height / 2) / 2, back_z],
        [window_width, max(1.0, window_centre_y - window_height / 2), thickness], wall_color)
    # Glass in the opening, sky board behind it: a bright view, never an open sky.
    add("Room Window Glass", "Block", "Glass", [0, window_centre_y, back_z],
        [window_width, window_height, 0.2], [196, 226, 240])
    add("Room Sky Through Window", "Block", "SmoothPlastic",
        [0, window_centre_y, back_z + 1.5], [window_width + 4.0, window_height + 3.0, 0.4], sky)
    add("Room Window Sill", "Block", "Wood", [0, window_centre_y - window_height / 2 - 0.3,
                                              back_z - 0.6],
        [window_width + 1.0, 0.4, 1.4], [190, 158, 120])
    # Front wall with a doorway gap, and the door itself.
    door_width, door_height = min(6.0, width * 0.28), min(8.5, height * 0.82)
    shoulder = max(1.0, (width - door_width) / 2)
    for index, offset in enumerate((-(door_width / 2 + shoulder / 2),
                                    door_width / 2 + shoulder / 2)):
        add(f"Room Front Wall {index + 1}", "Block", "SmoothPlastic",
            [offset, height / 2, front_z], [shoulder, height, thickness], wall_color)
    add("Room Front Wall Header", "Block", "SmoothPlastic",
        [0, door_height + (height - door_height) / 2, front_z],
        [door_width, max(1.0, height - door_height), thickness], wall_color)
    add("Room Door", "Block", "Wood", [0, door_height / 2, front_z],
        [door_width - 1.0, door_height - 1.0, 0.5], [150, 104, 66])
    # Skirting and rug sit on top of the floor, clear of the walls.
    for side, label in ((-1, "Left"), (1, "Right")):
        add(f"Room Skirting {label}", "Block", "Wood", [side * (half_x - 0.3), 0.4, z0],
            [0.5, 0.8, depth - 2.0], [150, 110, 78])
    add("Room Rug", "Block", "SmoothPlastic", [-half_x * 0.45, 0.35, z0 + 1.5],
        [max(7.0, width * 0.4), 0.2, max(6.0, depth * 0.32)], accent)
    add("Room Ceiling Light", "Ball", "Neon", [0, height - 1.0, z0 - 2.0],
        [1.6, 1.0, 1.6], [255, 236, 190])
    parts[-1]["light"] = {"kind": "Point", "color": [255, 236, 190], "brightness": 3.0,
                          "range": 34.0}
    return parts


def _overlaps(a, b):
    """Same tolerance the review pass uses, so nothing it sees is dropped later."""
    for axis in (0, 2):
        gap = abs(a["position"][axis] - b["position"][axis])
        if gap >= (a["size"][axis] + b["size"][axis]) / 2 - 0.05:
            return False
    low = min(a["position"][1] - a["size"][1] / 2, b["position"][1] - b["size"][1] / 2)
    high = max(a["position"][1] + a["size"][1] / 2, b["position"][1] + b["size"][1] / 2)
    return high - low < (a["size"][1] + b["size"][1]) / 2 * 1.35


def resolve_overlaps(parts, room):
    """Nudge (or drop) any part the review pass would otherwise delete.

    Hand-placed furniture can clash with a wall by a stud; rather than let the
    review pass quietly delete the wardrobe, slide it along its wall until it
    fits. Returns (kept, dropped_names).
    """
    width, depth, height = room
    half_x, half_z = width / 2, depth / 2
    z0 = ROOM_CENTRE_Z
    kept, dropped = [], []
    offsets = [(0.0, 0.0)]
    for step in (0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0):
        offsets.extend([(step, 0.0), (-step, 0.0), (0.0, step), (0.0, -step),
                        (step, step), (-step, -step), (step, -step), (-step, step)])
    for part in parts:
        x, y, z = part["position"]
        sx, sy, sz = part["size"]
        placed = None
        for dx, dz in offsets:
            candidate = {**part, "position": [round((x + dx) * 2) / 2, y, round((z + dz) * 2) / 2]}
            cx, cz = candidate["position"][0], candidate["position"][2]
            if not (-half_x - 0.5 <= cx - sx / 2 and cx + sx / 2 <= half_x + 0.5):
                continue
            if not (z0 - half_z - 0.5 <= cz - sz / 2 and cz + sz / 2 <= z0 + half_z + 0.5):
                continue
            if part.get("shell") and (dx or dz):
                continue   # walls and floor never move
            if any(_overlaps(candidate, other) for other in kept):
                continue
            placed = candidate
            break
        if placed is None:
            dropped.append(part["name"])
            continue
        kept.append(placed)
    return kept, dropped


def furnish_room(plan, room):
    """Real furniture, sized and placed for this room (never plaza decor)."""
    width, depth, height = room
    hx, hz = width / 2, depth / 2
    z0 = ROOM_CENTRE_Z
    wood = [170, 124, 84]
    dark_wood = [138, 98, 66]
    linen = [246, 244, 238]
    blanket_left = [122, 156, 206]
    blanket_right = [206, 142, 128]
    used = {str(prop.get("name", "")).casefold() for prop in plan.get("props", [])}
    parts = []

    def add(name, shape, material, position, size, color):
        base, suffix = name, 2
        while name.casefold() in used:
            name = f"{base} {suffix}"
            suffix += 1
        used.add(name.casefold())
        parts.append({"name": name, "shape": shape, "material": material,
                      "position": [round(v * 2) / 2 for v in position],
                      "size": [round(max(0.5, v) * 2) / 2 for v in size],
                      "color": [int(c) for c in color], "physics": "static"})

    def bed(label, cx, cz, bed_width, bed_length, blanket, bunk=False):
        """A bed with frame, mattress, pillow and blanket - the story prop that matters."""
        # A bunk bed only exists when the ceiling leaves room for the upper bunk.
        bunk = bunk and height >= 11.0
        top = 4.4 if bunk else 1.1
        add(f"{label} Frame", "Block", "Wood", [cx, top, cz],
            [bed_width, 0.5, bed_length], dark_wood)
        for dx in (-bed_width / 2 + 0.4, bed_width / 2 - 0.4):
            for dz in (-bed_length / 2 + 0.4, bed_length / 2 - 0.4):
                post_top = (4.4 + 3.4) if bunk else 4.4
                add(f"{label} Post", "Block", "Wood", [cx + dx, post_top / 2, cz + dz],
                    [0.5, post_top, 0.5], dark_wood)
        add(f"{label} Mattress", "Block", "SmoothPlastic",
            [cx, top + 0.75, cz], [bed_width - 0.6, 1.0, bed_length - 0.6], linen)
        add(f"{label} Pillow", "Block", "SmoothPlastic",
            [cx, top + 1.4, cz + bed_length / 2 - 1.4],
            [max(1.5, bed_width - 2.0), 0.5, 1.8], [252, 250, 246])
        add(f"{label} Blanket", "Block", "SmoothPlastic",
            [cx, top + 1.3, cz - bed_length / 4],
            [max(1.5, bed_width - 0.8), 0.4, bed_length / 2], blanket)
        if bunk:
            upper = top + 3.4
            add(f"{label} Upper Bunk", "Block", "Wood",
                [cx, upper, cz], [bed_width, 0.5, bed_length], dark_wood)
            add(f"{label} Upper Mattress", "Block", "SmoothPlastic",
                [cx, upper + 0.75, cz], [bed_width - 0.6, 1.0, bed_length - 0.6], linen)
            add(f"{label} Upper Pillow", "Block", "SmoothPlastic",
                [cx, upper + 1.4, cz + bed_length / 2 - 1.4],
                [max(1.5, bed_width - 2.0), 0.5, 1.8], [252, 250, 246])
            add(f"{label} Ladder", "Block", "Wood",
                [cx + bed_width / 2, top + 2.0, cz - bed_length / 2 + 1.4],
                [0.4, 4.0, 0.4], dark_wood)
            for step in range(3):
                add(f"{label} Ladder Step {step + 1}", "Block", "Wood",
                    [cx + bed_width / 2, top + 0.8 + step * 1.1, cz - bed_length / 2 + 1.4],
                    [1.2, 0.3, 0.4], dark_wood)
            add(f"{label} Guard Rail", "Block", "Wood",
                [cx, upper + 1.0, cz - bed_length / 2 + 0.8],
                [bed_width, 0.4, 0.4], dark_wood)

    # Bunk bed on the left, second bed on the right: two brothers, one room.
    bed("Bunk Bed", -hx + 3.2, z0 + hz - 6.5, min(5.2, hx * 0.5), min(9.0, hz * 0.8),
        blanket_left, bunk=True)
    bed("Second Bed", hx - 3.4, z0 + hz - 7.0, min(5.0, hx * 0.5), min(8.0, hz * 0.75),
        blanket_right)
    # Nightstand with a lamp between the beds.
    stand_x, stand_z = -hx + 3.0, z0 + hz - 13.0
    add("Nightstand", "Block", "Wood", [stand_x, 1.3, stand_z], [2.5, 2.6, 2.5], wood)
    add("Nightstand Drawer", "Block", "Wood", [stand_x, 1.6, stand_z - 1.35],
        [2.0, 0.8, 0.3], [210, 176, 138])
    add("Nightstand Lamp Base", "Cylinder", "Metal", [stand_x, 3.0, stand_z],
        [0.8, 0.8, 0.8], [176, 178, 184])
    add("Nightstand Lamp Shade", "Cylinder", "Neon", [stand_x, 3.9, stand_z],
        [1.6, 1.2, 1.6], [255, 236, 178])
    parts[-1]["light"] = {"kind": "Point", "color": [255, 236, 178],
                          "brightness": 1.6, "range": 20.0}
    # Desk + chair against the right wall, in front of the beds.
    desk_x, desk_z = hx - 2.4, z0 - hz + max(5.0, depth * 0.22)
    add("Desk Top", "Block", "Wood", [desk_x, 2.6, desk_z], [2.6, 0.4, 5.0], wood)
    for dz in (-2.0, 2.0):
        add(f"Desk Leg {1 if dz < 0 else 2}", "Block", "Wood",
            [desk_x, 1.3, desk_z + dz], [0.4, 2.6, 0.4], dark_wood)
    add("Desk Lamp", "Cylinder", "Neon", [desk_x + 0.6, 3.6, desk_z + 1.6],
        [0.9, 1.6, 0.9], [255, 232, 180])
    add("Desk Chair Seat", "Block", "Wood", [desk_x - 2.0, 1.5, desk_z],
        [1.8, 0.4, 1.8], dark_wood)
    add("Desk Chair Back", "Block", "Wood", [desk_x - 2.7, 2.6, desk_z],
        [0.4, 2.2, 1.8], dark_wood)
    add("Homework Books", "Block", "SmoothPlastic", [desk_x, 2.95, desk_z - 1.2],
        [1.4, 0.3, 1.0], [200, 96, 92])
    add("Pencil Cup", "Cylinder", "SmoothPlastic", [desk_x + 0.7, 3.1, desk_z - 0.4],
        [0.7, 0.9, 0.7], [96, 132, 200])
    # Wardrobe against the back wall, left of the window.
    add("Wardrobe", "Block", "Wood", [-hx + 3.4, height * 0.38, z0 + hz - 1.2],
        [3.6, height * 0.75, 1.8], [156, 112, 78])
    add("Wardrobe Door Left", "Block", "Wood", [-hx + 2.5, height * 0.38, z0 + hz - 2.2],
        [1.5, height * 0.68, 0.2], [176, 132, 96])
    add("Wardrobe Door Right", "Block", "Wood", [-hx + 4.3, height * 0.38, z0 + hz - 2.2],
        [1.5, height * 0.68, 0.2], [176, 132, 96])
    # Bookshelf right of the window, and a plant in the corner.
    add("Bookshelf", "Block", "Wood", [hx - 2.6, height * 0.36, z0 + hz - 1.2],
        [3.4, height * 0.7, 1.4], [162, 120, 86])
    for shelf in range(3):
        add(f"Bookshelf Row {shelf + 1}", "Block", "SmoothPlastic",
            [hx - 2.6, 1.4 + shelf * 2.2, z0 + hz - 1.9],
            [2.8, 0.9, 0.3], [[188, 92, 88], [92, 132, 188], [214, 176, 96]][shelf])
    add("Plant Pot", "Cylinder", "SmoothPlastic", [-hx + 1.4, 0.8, z0 - hz + 2.2],
        [1.6, 1.6, 1.6], [188, 120, 92])
    add("Plant Leaves", "Ball", "Grass", [-hx + 1.4, 2.9, z0 - hz + 2.2],
        [3.0, 2.8, 3.0], [104, 168, 96])
    # Toy chest, slippers, clock, posters and curtains: the room reads as lived in.
    add("Toy Chest", "Block", "Wood", [hx - 2.4, 1.1, z0 - hz + 2.4],
        [3.0, 2.2, 2.2], [176, 132, 92])
    add("Toy Chest Lid", "Block", "Wood", [hx - 2.4, 2.35, z0 - hz + 2.4],
        [3.2, 0.3, 2.4], [148, 108, 74])
    add("Slippers Left", "Block", "SmoothPlastic", [-hx + 5.0, 0.3, z0 - hz + 5.5],
        [1.0, 0.4, 1.8], [210, 150, 160])
    add("Slippers Right", "Block", "SmoothPlastic", [-hx + 6.2, 0.3, z0 - hz + 5.8],
        [1.0, 0.4, 1.8], [210, 150, 160])
    add("Wall Clock", "Block", "SmoothPlastic", [hx * 0.55, height * 0.72, z0 + hz - 0.4],
        [2.2, 2.2, 0.4], [248, 246, 240])
    for index, (wall_x, wall_z) in enumerate(((-hx + 0.3, z0 - hz + 7.0),
                                              (-hx + 0.3, z0 + hz - 9.5),
                                              (hx - 0.3, z0 - 3.0))):
        add(f"Wall Poster {index + 1}", "Block", "SmoothPlastic", [wall_x, height * 0.6, wall_z],
            [0.2, 3.0, 2.2], [[236, 176, 96], [140, 196, 236], [208, 140, 196]][index])
    for side in (-1, 1):
        add(f"Curtain {1 if side < 0 else 2}", "Block", "SmoothPlastic",
            [side * 5.2, height * 0.62, z0 + hz - 0.7], [1.8, 5.6, 0.5],
            [150, 122, 186])
    add("Curtain Rod", "Block", "Metal", [0, height * 0.87, z0 + hz - 0.7],
        [11.0, 0.3, 0.3], [176, 178, 184])
    # A sealed room is lit by its own lamps, not by the sun outside: two more warm
    # point lights keep the walls, beds and faces readable in the render.
    for index, (lx, lz) in enumerate(((-hx * 0.55, z0 + hz * 0.55), (hx * 0.55, z0 - hz * 0.5))):
        add(f"Room Lamp Glow {index + 1}", "Ball", "Neon", [lx, height - 2.2, lz],
            [1.2, 1.2, 1.2], [255, 238, 198])
        parts[-1]["light"] = {"kind": "Point", "color": [255, 238, 198], "brightness": 2.2,
                              "range": 30.0}
    return parts


def room_details(room, existing=()):
    """Small lived-in detail so the room reads as a real place on camera."""
    width, depth, height = room
    hx, hz = width / 2, depth / 2
    z0 = ROOM_CENTRE_Z
    used = {str(prop.get("name", "")).casefold() for prop in existing}
    parts = []

    def add(name, shape, material, position, size, color):
        base, suffix = name, 2
        while name.casefold() in used:
            name = f"{base} {suffix}"
            suffix += 1
        used.add(name.casefold())
        parts.append({"name": name, "shape": shape, "material": material,
                      "position": [round(v * 2) / 2 for v in position],
                      "size": [round(max(0.5, v) * 2) / 2 for v in size],
                      "color": [int(c) for c in color], "physics": "static"})

    # Ceiling beams: the line that makes the top of the room read on camera.
    for index in range(3):
        add(f"Ceiling Beam {index + 1}", "Block", "Wood",
            [0, height - 0.35, z0 - hz + 4.0 + index * (depth - 8.0) / 2],
            [width - 1.0, 0.5, 0.8], [168, 128, 92])
    add("Window Sill Books", "Block", "SmoothPlastic", [0, height * 0.62 - 1.0,
                                                       z0 + hz - 1.0],
        [3.0, 1.2, 0.5], [188, 92, 88])
    # Door handle and hinges.
    add("Door Handle", "Ball", "Metal", [1.9, 4.2, z0 - hz + 0.1],
        [0.6, 0.6, 0.6], [214, 198, 120])
    add("Door Hinge Top", "Block", "Metal", [-2.4, 7.0, z0 - hz + 0.2],
        [0.5, 0.6, 0.4], [180, 184, 190])
    add("Door Hinge Bottom", "Block", "Metal", [-2.4, 1.8, z0 - hz + 0.2],
        [0.5, 0.6, 0.4], [180, 184, 190])
    add("Doormat", "Block", "SmoothPlastic", [0, 0.2, z0 - hz + 3.0],
        [4.5, 0.2, 2.0], [120, 132, 150])
    # Books, cushions, clock and clutter around the beds and desk.
    book_colors = ([196, 96, 92], [92, 132, 196], [214, 176, 96], [110, 170, 120])
    for index in range(5):
        add(f"Shelf Book {index + 1}", "Block", "SmoothPlastic",
            [hx - 3.6, 2.0, z0 + hz - 2.2 - index * 0.7],
            [1.6, 1.8, 0.6], book_colors[index % len(book_colors)])
    add("Bed Cushion", "Block", "SmoothPlastic", [-hx + 3.4, 3.4, z0 + hz - 4.4],
        [2.2, 0.8, 1.6], [236, 208, 150])
    add("Second Bed Cushion", "Block", "SmoothPlastic", [hx - 3.2, 2.6, z0 + hz - 5.0],
        [2.0, 0.8, 1.4], [180, 210, 236])
    add("Alarm Clock", "Block", "SmoothPlastic", [-hx + 3.0, 3.1, z0 + hz - 12.0],
        [1.2, 0.9, 0.6], [232, 120, 110])
    add("Backpack", "Block", "SmoothPlastic", [-hx + 1.6, 1.1, z0 - hz + 3.4],
        [1.8, 2.2, 1.4], [96, 128, 186])
    add("Water Glass", "Cylinder", "Glass", [-hx + 3.6, 3.2, z0 + hz - 13.6],
        [0.7, 1.0, 0.7], [190, 226, 240])
    add("Sock Left", "Block", "SmoothPlastic", [-hx + 6.6, 0.2, z0 + hz - 3.0],
        [0.8, 0.4, 1.6], [242, 240, 236])
    add("Sock Right", "Block", "SmoothPlastic", [-hx + 7.8, 0.2, z0 + hz - 2.2],
        [0.8, 0.4, 1.6], [242, 240, 236])
    # Fairy lights along the back wall: warm point lights, capped by validate().
    for index in range(6):
        x = -hx + 4.0 + index * (width - 8.0) / 5
        add(f"Fairy Light {index + 1}", "Ball", "Neon",
            [x, height * 0.9, z0 + hz - 1.0], [0.6, 0.6, 0.6], [255, 228, 168])
        parts[-1]["light"] = {"kind": "Point", "color": [255, 228, 168],
                             "brightness": 0.7, "range": 10.0}
    return parts


def merge_room_props(plan, room, room_parts):
    """Keep the AI's own props where they fit, on top of the built room."""
    width, depth, height = room
    hx, hz = width / 2, depth / 2
    z0 = ROOM_CENTRE_Z
    kept = list(room_parts)
    acting_x, acting_z_min, acting_z_max = min(hx * 0.62, 8.0), z0 - 5.0, z0 + 5.0
    used = {prop["name"].casefold() for prop in kept}
    for prop in plan.get("props") or []:
        sx, sy, sz = (list(prop.get("size") or [2, 2, 2]) + [2, 2, 2])[:3]
        sx, sz = min(sx, width - 3.0), min(sz, depth - 3.0)
        sy = min(sy, height - 2.0)

        def fits(px, py, pz):
            if abs(px) + sx / 2 > hx - 0.5 or abs(pz - z0) + sz / 2 > hz - 0.5:
                return False
            if py - sy / 2 < 0.2 or py + sy / 2 > height - 0.5:
                return False
            if abs(px) < acting_x and acting_z_min < pz < acting_z_max and py - sy / 2 < 3.0:
                return False
            candidate = {"position": [px, py, pz], "size": [sx, sy, sz]}
            return not any(_overlaps(candidate, other) for other in kept)

        candidates = [(prop["position"][0], prop["position"][1], prop["position"][2])]
        # Free slots along the walls: the trophy / poster / toy the AI wrote about
        # survives instead of being thrown away for overlapping a bed.
        if min(sx, sy, sz) <= 1.2 and max(sy, sz) >= 2.0:      # wall-mounted
            for side in (-1, 1):
                for offset in range(-int(hz) + 2, int(hz) - 1, 2):
                    candidates.append((side * (hx - 0.5), height * 0.62, z0 + offset))
        for side in (-1, 1):
            for offset in range(-int(hx) + 2, int(hx) - 1, 2):
                candidates.append((side * (hx - 0.9 - sx / 2), sy / 2 + 0.1, z0 + offset))
            for offset in range(-int(hz) + 2, int(hz) - 1, 2):
                candidates.append((offset, sy / 2 + 0.1, z0 + side * (hz - 0.9 - sz / 2)))
        placement = next((slot for slot in candidates if fits(*slot)), None)
        if placement is None:
            continue
        name, suffix = prop["name"], 2
        while name.casefold() in used:
            name = f"{prop['name']} {suffix}"
            suffix += 1
        used.add(name.casefold())
        kept.append({**prop, "name": name[:40], "size": [sx, sy, sz],
                     "position": [round(v * 2) / 2 for v in placement]})
    return kept


def arrange_cast(plan, room, usernames=()):
    """Keep the cast close together inside a room.

    Portrait 9:16 has a narrow horizontal field of view: brothers standing six
    studs apart in a 26-stud room cannot share a frame from any wall, so one of
    them ends up outside every shot. A room scenes brings them within ~2 studs of
    each other and steps them back from the camera.
    """
    width, depth, height = room
    z0 = ROOM_CENTRE_Z
    people = [person for person in plan.get("character_placements") or []]
    if not people:
        people = [{"username": name, "role": "lead" if index == 0 else "supporting"}
                  for index, name in enumerate(usernames)]
    spread = min(4.5, width * 0.16)
    if len(people) == 1:
        offsets = [0.0]
    else:
        offsets = [-spread / 2 + spread * index / (len(people) - 1)
                   for index in range(len(people))]
    depth_step = min(1.5, depth * 0.06)
    placed = []
    for index, person in enumerate(people):
        placed.append({**person,
                       "position": [round(offsets[index] * 2) / 2, 0,
                                    round((z0 + depth_step * (index % 2)) * 2) / 2]})
    plan["character_placements"] = placed
    return plan


def view_coverage(plan, position, target, fov_degrees=42.0, samples=(12, 20),
                  aspect=9.0 / 16.0):
    """What fills the frame from this camera: room, cast, furniture... or open sky.

    A pure-maths ray cast (no renderer): the same perspective the short uses, one
    ray per sample pixel, nearest axis-aligned box wins. 'sky' means a ray hit
    nothing at all - the outdoor look that ruined run #109.
    """
    parts = list(plan.get("props") or [])
    boxes = [{"position": part["position"], "size": part["size"],
              "name": part.get("name", "")} for part in parts]
    for person in plan.get("character_placements") or []:
        px, _, pz = person.get("position") or [0, 0, 0]
        boxes.append({"position": [px, 2.6, pz], "size": [2.4, 5.2, 1.4],
                      "name": "CAST " + str(person.get("username", ""))})

    def normalise(vector):
        length = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / length for value in vector]

    forward = normalise([target[axis] - position[axis] for axis in range(3)])
    right = normalise([forward[1] * 0.0 + forward[2] * 1.0, 0.0,
                       -forward[0] * 1.0 + forward[1] * 0.0])
    if math.sqrt(sum(value * value for value in right)) < 0.2:
        right = [1.0, 0.0, 0.0]
    right = normalise(right)
    up = normalise([right[1] * forward[2] - right[2] * forward[1],
                    right[2] * forward[0] - right[0] * forward[2],
                    right[0] * forward[1] - right[1] * forward[0]])
    up = [-value for value in up]          # screen up, not down
    tan_half = math.tan(math.radians(fov_degrees) / 2)

    counts = {"sky": 0, "cast": 0, "room": 0, "furniture": 0}
    for iy in range(samples[1]):
        for ix in range(samples[0]):
            ndc_x = ((ix + 0.5) / samples[0] * 2 - 1) * tan_half * aspect
            ndc_y = (1 - (iy + 0.5) / samples[1] * 2) * tan_half
            direction = normalise([forward[axis] + right[axis] * ndc_x + up[axis] * ndc_y
                                   for axis in range(3)])
            nearest, nearest_name = None, ""
            for box in boxes:
                entry, exit_ = 0.001, 1e9
                for axis in range(3):
                    low = box["position"][axis] - box["size"][axis] / 2
                    high = box["position"][axis] + box["size"][axis] / 2
                    delta = direction[axis]
                    if abs(delta) < 1e-9:
                        if position[axis] < low or position[axis] > high:
                            entry, exit_ = 2, 1
                            break
                        continue
                    t1 = (low - position[axis]) / delta
                    t2 = (high - position[axis]) / delta
                    entry = max(entry, min(t1, t2))
                    exit_ = min(exit_, max(t1, t2))
                    if entry > exit_:
                        break
                if entry <= exit_ and (nearest is None or entry < nearest):
                    nearest, nearest_name = entry, box["name"]
            if nearest is None:
                counts["sky"] += 1
            elif nearest_name.startswith("CAST"):
                counts["cast"] += 1
            elif nearest_name.startswith("Room "):
                counts["room"] += 1
            else:
                counts["furniture"] += 1
    total = samples[0] * samples[1]
    return {key: round(value / total, 3) for key, value in counts.items()}


def room_camera_slots(room):
    """Corner and side slots inside the room, used to rescue a blocked shot."""
    width, depth, height = room
    hx, hz = width / 2 - 1.6, depth / 2 - 1.6
    z0 = ROOM_CENTRE_Z
    slots = []
    for y in (min(height - 1.5, 5.6), min(height - 1.5, height * 0.86)):
        for sx in (-1, 1):
            for sz in (-1, 1):
                slots.append([sx * hx, y, z0 + sz * hz])
        slots.append([0.0, y, z0 - hz])
        slots.append([0.0, y, z0 + hz])
    return slots


def repair_blocked_shots(plan, room, report):
    """If a lamp or a bed hides the cast, move that camera to a free slot."""
    shots = plan.get("camera_shots") or []
    for shot, entry in zip(shots, report):
        if entry["cast"] >= 0.10 and entry["sky"] <= 0.02:
            continue
        best_coverage, best_position = entry, list(shot["position"])
        for slot in room_camera_slots(room):
            coverage = view_coverage(plan, slot, shot["target"])
            if coverage["sky"] > 0.02:
                continue
            if coverage["cast"] > best_coverage["cast"]:
                best_coverage, best_position = coverage, slot
        if best_position != list(shot["position"]):
            shot["position"] = [round(value, 2) for value in best_position]
            entry.update(best_coverage)
            entry["camera"] = shot["position"]
            entry["repaired"] = True
    return plan, report


def interior_view_report(plan):
    """Per-shot coverage of the finished interior plan (printed for the run log)."""
    report = []
    for shot in plan.get("camera_shots") or []:
        coverage = view_coverage(plan, shot["position"], shot["target"])
        report.append({"time": shot.get("time"), "framing": shot.get("framing"),
                       "camera": shot["position"], **coverage})
    return report


def interior_camera_shots(cast, room, duration, usernames=(), hour_overrides=()):
    """Camera plan that stays inside the room and still reads as a film.

    The AI's original camera positions may be replaced to keep shots inside the
    room, but named scene-hour overrides survive at the nearest generated beat.
    """
    width, depth, height = room
    hx, hz = width / 2 - 2.2, depth / 2 - 2.2
    z0 = ROOM_CENTRE_Z
    eye = min(height - 1.5, 5.2)
    names = [str(name) for name in usernames if str(name)]
    first = names[0] if names else "normal"
    second_name = names[1] if len(names) > 1 else first
    lead = cast[0] if cast else [0, 0, z0]
    second = cast[1] if len(cast) > 1 else [lead[0] + 4, 0, lead[2] + 1]
    lx, lz = float(lead[0]), float(lead[2])
    sx, sz = float(second[0]), float(second[2])

    def face(person_x, person_z, from_x, from_z):
        """A camera a few studs in front of a head, inside the room."""
        return [max(-hx, min(hx, person_x + from_x)), min(height - 1.5, 5.4),
                max(z0 - hz, min(z0 + hz, person_z + from_z))]


    shots = [
        # 1. Establishing: front corner of the room, walls + ceiling + floor in frame.
        (0.0, [-hx, min(height - 2.5, 7.2), z0 - hz], [lx, 4.2, lz], first,
         "smooth", "wide", FACE_DISTANCE_DEFAULT),
        # 2. Two-shot from the front, cast centred.
        (0.10, [0.0, eye, z0 - hz * 0.85], [(lx + sx) / 2, 4.4, (lz + sz) / 2], first,
         "smooth", "auto", FACE_DISTANCE_DEFAULT),
        # 3. Face close-up on the lead, inside the room, with a little more headroom.
        (0.20, face(lx, lz, 1.7, -2.0), [lx, 4.9, lz], first, "snap", "face", FACE_DISTANCE_DEFAULT),
        # 4. Side angle from the left wall (sees the bunk bed).
        (0.30, [-hx, min(height - 2.0, 5.6), z0 + hz * 0.5], [0.0, 4.2, z0], first,
         "smooth", "auto", FACE_DISTANCE_DEFAULT),
        # 5. Face close-up on the second brother.
        (0.40, face(sx, sz, -1.7, -2.0), [sx, 4.9, sz], second_name,
         "snap", "face", FACE_DISTANCE_DEFAULT),
        # 6. Over-the-shoulder from behind the lead, looking at the second.
        (0.50, [lx + 1.4, min(height - 1.6, 5.6), min(z0 + hz, lz + 2.8)], [sx, 4.3, sz],
         first, "smooth", "close", FACE_DISTANCE_DEFAULT),
        # 7. Wide from the back corner, looking down across the beds at the cast.
        (0.60, [hx, min(height - 1.8, 6.8), z0 + hz], [lx, 3.6, lz], first,
         "smooth", "wide", FACE_DISTANCE_DEFAULT),
        # 8. Low angle from the floor: dramatic, still inside.
        (0.70, [min(hx, lx + 3.2), 3.2, max(z0 - hz, lz - 3.4)], [lx, 5.0, lz], first,
         "snap", "auto", FACE_DISTANCE_DEFAULT),
        # 9. Air shot from the ceiling corner, bed + cast in frame.
        (0.80, [-hx * 0.7, height - 1.5, z0 + hz * 0.7], [lx, 3.0, lz + 1.5], first,
         "smooth", "auto", FACE_DISTANCE_DEFAULT),
        # 10. Final two-shot from the front, both brothers in frame and warm.
        (0.90, [(lx + sx) / 2, 5.0, max(z0 - hz, min(lz, sz) - 7.0)],
         [(lx + sx) / 2, 4.4, (lz + sz) / 2], first, "snap", "auto", FACE_DISTANCE_DEFAULT),
    ]
    shots[-1] = (1.0,) + tuple(shots[-1][1:])
    scene_hours = []
    for shot in hour_overrides or ():
        if not isinstance(shot, dict) or not isinstance(shot.get("time_of_day"), str):
            continue
        hour = shot["time_of_day"].casefold()
        try:
            at = float(shot.get("time"))
        except (TypeError, ValueError):
            continue
        if hour in SCENE_TIME_CHOICES and 0 <= at <= duration:
            scene_hours.append((at, hour, shot.get("transition")))
    scene_hours.sort(key=lambda item: item[0])
    # Keep the final plan within the AI schema's cap while leaving enough
    # generated camera beats to represent every named lighting change.
    scene_hours = scene_hours[:48]
    count = min(48, max(target_camera_count(duration), len(scene_hours)))
    face_slots = {max(1, count // 5), count // 2, min(count - 2, (4 * count) // 5)}
    output = []
    for index in range(count):
        progress = index / (count - 1) * (len(shots) - 1)
        left_index = int(progress)
        right_index = min(len(shots) - 1, left_index + 1)
        blend = progress - left_index
        left, right = shots[left_index], shots[right_index]
        position = [left[1][axis] * (1 - blend) + right[1][axis] * blend for axis in range(3)]
        target = [left[2][axis] * (1 - blend) + right[2][axis] * blend for axis in range(3)]
        focus = left[3] if blend < 0.5 else right[3]
        nearest = left if blend < 0.5 else right
        framing = nearest[5] if nearest[5] != "face" else "auto"
        if index in face_slots:
            focus = first if index != count // 2 else second_name
            person_x, person_z = (lx, lz) if focus == first else (sx, sz)
            position = face(person_x, person_z, 1.7, -2.0)
            target = [person_x, 4.9, person_z]
            framing = "face"
        transition = "smooth" if index in {0, count - 1} else (
            "snap" if index % 4 == 2 or nearest[4] == "snap" else "smooth")
        output.append({
            "time": round(duration * index / (count - 1), 2),
            # X stays within the side walls, Y between floor and ceiling, Z within
            # the front and back walls - every shot is taken from inside the room.
            "position": [round(max(-hx, min(hx, position[0])), 2),
                         round(max(3.0, min(height - 1.5, position[1])), 2),
                         round(max(z0 - hz, min(z0 + hz, position[2])), 2)],
            "target": [round(v, 2) for v in target],
            "focus_username": focus, "transition": transition,
            "framing": framing, "face_distance": FACE_DISTANCE_DEFAULT,
        })
    previous_slot = -1
    for override_index, (at, hour, transition) in enumerate(scene_hours):
        desired = int(round(min(duration, max(0.0, at)) / max(float(duration), 0.01) * (count - 1)))
        low = previous_slot + 1
        high = count - (len(scene_hours) - override_index)
        slot = min(high, max(low, desired))
        output[slot]["time_of_day"] = hour
        if 0 < slot < count - 1 and transition in ("smooth", "snap"):
            output[slot]["transition"] = transition
        previous_slot = slot
    return output


def clamp_cameras_to_room(plan, room):
    """Keep every camera inside the room: no shot from outside or above the roof."""
    width, depth, height = room
    half_x, half_z = width / 2 - 2.0, depth / 2 - 2.0
    for shot in plan.get("camera_shots") or []:
        position = list(shot.get("position") or [0, 0, 0])
        target = list(shot.get("target") or [0, 0, 0])
        position[0] = max(-half_x, min(half_x, float(position[0])))
        position[1] = max(3.0, min(height - 1.5, float(position[1])))
        position[2] = max(ROOM_CENTRE_Z - half_z, min(ROOM_CENTRE_Z + half_z, float(position[2])))
        target[0] = max(-half_x, min(half_x, float(target[0])))
        target[1] = max(2.0, min(height - 1.0, float(target[1])))
        target[2] = max(ROOM_CENTRE_Z - half_z, min(ROOM_CENTRE_Z + half_z, float(target[2])))
        # Keep face framing at least a few studs away: readable expression, not an extreme crop.
        if str(shot.get("framing")) == "face":
            dx, dy, dz = (target[0] - position[0], target[1] - position[1],
                          target[2] - position[2])
            span = max(0.001, (dx * dx + dy * dy + dz * dz) ** 0.5)
            need = float(shot.get("face_distance") or FACE_DISTANCE_DEFAULT)
            if span < need:
                scale = need / span
                position = [target[0] - dx * scale, target[1] - dy * scale,
                            target[2] - dz * scale]
                position[1] = max(3.0, min(height - 1.5, position[1]))
        shot["position"] = [round(v, 2) for v in position]
        shot["target"] = [round(v, 2) for v in target]
    return plan


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
        "local function makePart(name, size, position, color, material, shape, physicsMode, light, effect)",
        "    local p = Instance.new('Part')",
        "    p.Name = name",
        "    p.Anchored = physicsMode ~= 'dynamic'",
        "    p.Size = Vector3.new(size[1], size[2], size[3])",
        "    local transform = CFrame.new(position[1], position[2], position[3])",
        "    if shape == 'Cylinder' then transform = transform * CFrame.Angles(0, 0, math.rad(90)) end",
        "    p.CFrame = transform",
        "    p.Color = Color3.fromRGB(color[1], color[2], color[3])",
        "    p.Material = Enum.Material[material]",
        "-- Roblox has five part types; the hand-built silhouettes borrow the",
        "-- nearest one so the Studio build always runs.",
        "    local partTypes = {Cone = 'Cylinder', Pyramid = 'CornerWedge', Prism = 'Wedge', Torus = 'Cylinder', Ring = 'Cylinder', Hemisphere = 'Ball', Truss = 'Block'}",
        "    p.Shape = Enum.PartType[partTypes[shape] or shape]",
        "    p.TopSurface = Enum.SurfaceType.Smooth",
        "    p.BottomSurface = Enum.SurfaceType.Smooth",
        "    if light then",
        "        local source = Instance.new(light.kind == 'Spot' and 'SpotLight' or (light.kind == 'Surface' and 'SurfaceLight' or 'PointLight'))",
        "        source.Color = Color3.fromRGB(light.color[1], light.color[2], light.color[3])",
        "        source.Brightness = light.brightness",
        "        source.Range = light.range",
        "        if source:IsA('SpotLight') then source.Angle = light.angle end",
        "        source.Parent = p",
        "    end",
        "    if effect then",
        "        local emitter = Instance.new('ParticleEmitter')",
        "        emitter.Name = effect.family .. ' Effect'",
        "        emitter.Color = ColorSequence.new(Color3.fromRGB(effect.color[1], effect.color[2], effect.color[3]))",
        "        emitter.Rate = math.max(1, math.floor(effect.rate * 60))",
        "        emitter.Lifetime = NumberRange.new(effect.life * 0.7, effect.life)",
        "        emitter.Speed = NumberRange.new(effect.speed * 0.6, effect.speed)",
        "        emitter.SpreadAngle = Vector2.new(effect.spread * 90, effect.spread * 90)",
        "        emitter.Size = NumberSequence.new(effect.size)",
        "        emitter.Acceleration = Vector3.new(0, effect.gravity * 10, 0)",
        "        emitter.LightEmission = effect.twinkle and 0.8 or 0.2",
        "        emitter.Parent = p",
        "    end",
        "    p.Parent = map",
        "    return p",
        "end",
        "-- Full 640-stud walkable ground plate; the blueprint and themed furnishing define the environment.",
        f"makePart('Story Map Ground', {{640, 2, 640}}, {{0, -1, 0}}, {{{plan['ground_color'][0]}, {plan['ground_color'][1]}, {plan['ground_color'][2]}}}, {lua_string(plan['ground_material'])}, 'Block')",
        "-- AI-planned landmarks plus procedurally furnished, theme-matched details.",
    ]
    for prop in plan["props"]:
        pos = ", ".join(map(str, prop["position"]))
        size = ", ".join(map(str, prop["size"]))
        color = ", ".join(map(str, prop["color"]))
        light = prop.get("light")
        effect = prop.get("effect")
        light_lua = ("{" + f"kind = {lua_string(light['kind'])}, color = {{{', '.join(map(str, light['color']))}}}, "
                     f"brightness = {light['brightness']}, range = {light['range']}, angle = {light['angle']}" + "}"
                     ) if light else "nil"
        effect_lua = ("{" + f"family = {lua_string(effect['family'])}, color = {{{', '.join(map(str, effect['color']))}}}, "
                      f"rate = {effect['rate']}, size = {effect['size']}, speed = {effect['speed']}, "
                      f"life = {effect['life']}, gravity = {effect['gravity']}, spread = {effect['spread']}, "
                      f"twinkle = {'true' if effect.get('twinkle') else 'false'}"+ "}"
                      ) if effect else "nil"
        lines.append(
            f"makePart({lua_string(prop['name'])}, {{{size}}}, {{{pos}}}, {{{color}}}, "
            f"{lua_string(prop['material'])}, {lua_string(prop['shape'])}, "
            f"{lua_string(prop.get('physics', 'static'))}, {light_lua}, {effect_lua})"
        )
    ambient = plan["ambient_color"]
    time_of_day = resolve_time_of_day(plan.get("time_of_day", "auto"), plan.get("theme", ""))
    clock_time = CLOCK_TIMES[time_of_day]
    lines.extend([
        "-- Match Studio lighting to the same user-selected hour as the rendered MP4.",
        f"map:SetAttribute('TimeOfDay', {lua_string(time_of_day)})",
        f"Lighting.ClockTime = {clock_time}",
        "Lighting.Brightness = 2",
        f"Lighting.Ambient = Color3.fromRGB({ambient[0]}, {ambient[1]}, {ambient[2]})",
        f"Lighting.OutdoorAmbient = Color3.fromRGB({ambient[0]}, {ambient[1]}, {ambient[2]})",
        "local atmosphere = Lighting:FindFirstChildOfClass('Atmosphere')",
        "if not atmosphere then atmosphere = Instance.new('Atmosphere'); atmosphere.Parent = Lighting end",
        "atmosphere.Density = 0.22",
        "atmosphere.Offset = 0.1",
        f"print('Built {lua_string(plan['name'])} with {len(plan['props'])} furnished world Parts in Workspace.')",
    ])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("duration", type=duration_arg,
                        help="exact length: 144, 2:24, 2m24s")
    parser.add_argument("--json-only", action="store_true")
    parser.add_argument("--strict", action="store_true", help="require a valid AI-authored landmark blueprint")
    parser.add_argument("--fallback", action="store_true", help="build a theme/story-based map without the local AI service")
    parser.add_argument("--theme", default="", help="explicit visual-theme cue for procedural fallback")
    parser.add_argument("--time-of-day", choices=TIME_OF_DAY_CHOICES, default="auto",
                        help="coherent lighting hour: auto, dawn, day, sunset or night")
    parser.add_argument("--scene-time-notes", default="",
                        help="optional user direction for hour changes across scenes/shots")
    parser.add_argument("--story", default="", help="story context for procedural fallback")
    parser.add_argument("--min-props", type=int, default=8, help="minimum unique AI landmark/building anchors")
    parser.add_argument("--target-props", type=int, default=3000, help="minimum furnished world Parts after deterministic expansion (1260=standard, 3000=dense, 5000=ultra)")
    parser.add_argument("--usernames", type=Path, help="JSON file containing the ordered Roblox cast")
    parser.add_argument("--story-topic", default="", help="explicit user request used to gate optional avatar-body effects")
    parser.add_argument("--interior", nargs="?", const="small", default="",
                        help="the scene happens inside a room: tiny|small|medium (default small). "
                             "Pulls every prop inside the room and adds floor/walls/ceiling/door/window.")
    parser.add_argument("--scene-mode", choices=["auto", "interior", "outdoor"], default="",
                        help="let tools/scene_mode.py decide (auto) or force a mode")
    args = parser.parse_args()
    source, destination, duration = args.source, args.destination, args.duration
    usernames = json.loads(args.usernames.read_text(encoding="utf-8")) if args.usernames else []
    if not isinstance(usernames, list) or any(not isinstance(name, str) for name in usernames):
        raise SystemExit("usernames file must be a JSON array of strings")
    duration = check_duration(duration)
    if not 1200 <= args.target_props <= 8000:
        raise SystemExit("target-props must be between 1200 and 8000 furnished Parts")
    if args.fallback:
        raw_plan = procedural_fallback_plan(args.theme, args.story, duration, usernames)
        source_label = "theme/story procedural fallback"
        print("Local AI map service was unavailable; generating a detailed map from the user's theme and story instead.", file=sys.stderr)
    else:
        try:
            raw_plan = decode_response(source)
            if args.strict:
                if not isinstance(raw_plan, dict) or not isinstance(raw_plan.get("props"), list) or not raw_plan["props"]:
                    raise ValueError("the AI blueprint contained no props")
                raw_plan, fixes = repair_blueprint(raw_plan, args.theme, args.story, args.story_topic)
                for note in fixes:
                    print(f"Repaired the AI blueprint instead of rejecting it: {note}.", file=sys.stderr)
            source_label = "AI landmark blueprint"
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            if args.strict:
                raise SystemExit(f"Invalid AI map plan: {exc}") from exc
            print(f"Invalid AI map plan ({exc}); using the themed fallback map.", file=sys.stderr)
            raw_plan = procedural_fallback_plan(args.theme, args.story, duration, usernames)
            source_label = "theme/story procedural fallback"
    # A story that happens in a room must be rendered in a room: the mode comes
    # from --scene-mode/--interior, and defaults to the story's own words.
    interior_size = (args.interior or "").strip()
    if args.scene_mode == "interior" and not interior_size:
        interior_size = "small"
    if args.scene_mode == "auto" or (not interior_size and not args.scene_mode):
        from scene_mode import detect as detect_scene
        narration_text = ""
        try:
            narration_text = Path("dist/narration.txt").read_text(encoding="utf-8")
        except OSError:
            pass
        decided = detect_scene(args.story_topic or args.theme, narration_text)
        if decided["mode"] == "interior":
            interior_size = interior_size or decided["size"]
            print(f"Interior scene ({decided['reason']}): building a real room, not an open map.",
                  file=sys.stderr)
    if args.scene_mode == "outdoor":
        interior_size = ""
    try:
        anchors = validate(raw_plan, duration, usernames, args.min_props, args.story_topic)
        room = interior_room(interior_size) if interior_size else None
        if room:
            # Indoor scenes are built as a room: no open world, no landmark buildings,
            # no plaza decor. The AI's own props become furniture, then floor, walls,
            # ceiling, door and window are added, and furniture fills the room.
            anchors = {**anchors, "props": fit_anchors_to_room(anchors.get("props") or [], room)}
            shell = room_shell(anchors, room)
            furniture = furnish_room(anchors, room)
            details = room_details(room, shell + furniture)
            # The builder, not the later review pass, decides what fits: anything
            # that would be deleted for overlapping is slid along a wall instead.
            room_parts, dropped = resolve_overlaps(shell + furniture + details, room)
            plan = {**anchors, "props": merge_room_props(anchors, room, room_parts)}
            if dropped:
                print(f"Interior build: dropped {len(dropped)} part(s) that cannot fit "
                      f"({', '.join(dropped[:6])}).", file=sys.stderr)
            plan = arrange_cast(plan, room, usernames)
            cast = [[person["position"][0], 0, person["position"][2]]
                    for person in plan.get("character_placements") or []]
            plan["camera_shots"] = interior_camera_shots(
                cast, room, duration, usernames, anchors.get("camera_shots") or [])
            plan["name"] = str(plan.get("name") or "Story Room")[:48]
        else:
            plan = expand_plan(anchors, args.target_props)
        # A room holds a roomful of furniture, not a 1260-Part city: the density
        # target belongs to open worlds.
        density = min(args.target_props, INTERIOR_MAX_PROPS) if room else args.target_props
        required = args.min_props if room else max(args.min_props, density)
        plan = validate(plan, duration, usernames, required, args.story_topic)
        if room:
            # validate() re-normalises cameras; keep them inside the room afterwards.
            plan = clamp_cameras_to_room(plan, room)
            plan["interior"] = {"width": room[0], "depth": room[1], "height": room[2],
                               "centre_z": ROOM_CENTRE_Z}
            print(f"Interior build: {len(plan['props'])} Parts in a "
                  f"{room[0]:.0f}x{room[1]:.0f}x{room[2]:.0f} stud room.", file=sys.stderr)
            coverage = interior_view_report(plan)
            plan, coverage = repair_blocked_shots(plan, room, coverage)
            plan["interior_view"] = coverage
            for entry in coverage:
                print(f"  camera t={entry['time']:>6} {str(entry['framing']):5} "
                      f"sky {entry['sky'] * 100:4.1f}%  cast {entry['cast'] * 100:4.1f}%  "
                      f"room {entry['room'] * 100:4.1f}%  furniture "
                      f"{entry['furniture'] * 100:4.1f}%", file=sys.stderr)
            if any(entry["sky"] > 0.02 for entry in coverage):
                print("Warning: a camera can see past the room walls; keeping it closer to "
                      "the cast.", file=sys.stderr)
    except ValueError as exc:
        raise SystemExit(f"Could not construct a valid furnished world: {exc}") from exc
    time_context = " ".join(str(value or "") for value in (
        plan.get("theme", ""), args.theme, args.story, args.story_topic))
    resolved_hour, sequence_applied = configure_plan_time_of_day(
        plan, args.time_of_day, time_context, args.scene_time_notes)
    if sequence_applied:
        print("Applied the requested scene-hour sequence to the procedural camera fallback.")
    print(f"Resolved scene lighting: {resolved_hour} ({CLOCK_TIMES[resolved_hour]:g}:00 Roblox ClockTime).")
    json_path = destination if args.json_only else destination.with_suffix(".json")
    if not args.json_only:
        emit_lua(plan, destination)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    print(f"Created map data {json_path}: {plan['name']} with {len(plan['props'])} furnished 3D Parts ({source_label} + theme expansion).")


if __name__ == "__main__":
    main()
