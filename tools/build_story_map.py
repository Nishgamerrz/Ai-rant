#!/usr/bin/env python3
"""Validate an AI map layout and emit a runnable Roblox Studio Lua map builder."""
from __future__ import annotations

import hashlib
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


def default_camera_shots(duration, usernames=()):
    """A mix of smooth camera sweeps and story-beat snap cuts for the rendered short.

    Long shorts (up to 180s) need more beats than a 30s clip, so the storyboard
    length scales with the requested duration instead of holding on one angle.
    """
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
    count = max(5, min(len(views), int(round(duration / 8)) + 2))
    chosen = views[:count]
    if chosen[-1][2] != "smooth":
        chosen[-1] = (chosen[-1][0], chosen[-1][1], "smooth")
    last = count - 1
    return [
        {"time": round(duration * index / last, 2), "position": pos, "target": target,
         "transition": "smooth" if index == 0 else mode,
         "focus_username": usernames[index % len(usernames)] if usernames else "world"}
        for index, (pos, target, mode) in enumerate(chosen)
    ]


def normalize_camera_shots(shots, duration, usernames=()):
    if not isinstance(shots, list) or not 4 <= len(shots) <= 24:
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
        clean.append({
            "time": round(float(time), 2),
            "position": [round(float(v), 2) for v in pos],
            "target": [round(float(v), 2) for v in target],
            "transition": transition,
            "focus_username": focus,
        })
        previous = time
    if clean[0]["time"] != 0:
        clean.insert(0, default_camera_shots(duration, usernames)[0])
    if clean[-1]["time"] < duration:
        last = dict(clean[-1])
        last["time"] = float(duration)
        last["transition"] = "smooth"
        clean.append(last)
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
        "character_placements": default_character_placements(usernames),
    }


def expand_plan(plan, target_props=3000):
    """Turn a compact AI landmark blueprint into a full, themed furnished build."""
    source_props = list(plan.get("props", []))
    if len(source_props) >= target_props:
        return {**plan, "props": source_props}

    building_words = {
        "building", "shop", "tower", "house", "school", "cafe", "store", "station", "temple",
        "castle", "museum", "hall", "market", "hotel", "factory", "restaurant", "library",
        "hospital", "arcade", "bakery", "office", "apartment", "mansion", "workshop", "palace",
        "warehouse", "inn", "laboratory", "lab", "theater", "theatre", "pavilion", "cottage",
    }
    component_words = {"wall", "roof", "door", "window", "frame", "floor", "stair", "chimney",
                       "foundation", "facade", "pillar", "column", "interior", "sill", "header"}
    building_cores = []
    keep_props = []
    for prop in source_props:
        words = set(re.findall(r"[a-z]+", prop.get("name", "").casefold()))
        size = prop.get("size", [0, 0, 0])
        is_building = (bool(words & building_words) and not bool(words & component_words)
                       and size[0] >= 10 and size[1] >= 6 and size[2] >= 8
                       and prop.get("shape") == "Block")
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
        add(f"{name} Welcome Rug", "Block", "SmoothPlastic", [x, rug_y, inner_z],
            [max(2, sx * 0.42), 0.22, max(2, sz * 0.28)], accent_color(plan, color))
        add(f"{name} Front Counter", "Block", "Wood", [x, bottom + 1.0, z + sz * 0.12],
            [max(2, sx * 0.36), 1.4, 1.0], wood)
        for side, sign in (("West", -1), ("East", 1)):
            table_x = x + sign * sx * 0.25
            add(f"{name} {side} Table", "Block", "Wood", [table_x, bottom + 1.05, inner_z],
                [max(1.5, sx * 0.16), 1.1, max(1.5, sz * 0.12)], tint(wood, 1.12))
            add(f"{name} {side} Chair", "Block", "SmoothPlastic", [table_x, bottom + 0.55, inner_z + sz * 0.13],
                [1.0, 1.0, 1.0], roof)
            add(f"{name} {side} Wall Shelf", "Block", "Wood", [x + sign * sx * 0.32, bottom + sy * 0.45, back + thickness],
                [max(1.5, sx * 0.15), 0.55, 1.0], wood)
        add(f"{name} Ceiling Light", "Ball", "Neon", [x, ceiling_y - 0.25, z], [1.0, 0.7, 1.0], accent_color(plan, color))
        add(f"{name} Entry Step", "Block", "Concrete", [x, bottom + 0.25, front + 0.9], [door_width + 1, 0.5, 1.4], tint(wall, 1.12))
        add(f"{name} Roof Sign", "Block", "Neon", [x, min(249, top + 1.1), z + sz * 0.25],
            [max(2, sx * 0.35), 0.8, 0.5], accent_color(plan, color))
        add(f"{name} Roof Trim Front", "Block", "SmoothPlastic", [x, top + 0.3, z + sz * 0.49],
            [sx, 0.45, 0.55], roof)

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
            x = sign * 16
            if not plaza_clear(x, z, 3.0, 2.2):
                continue
            add(f"{side} Plaza Bench Seat", "Block", "Wood", [x, 0.72, z], [5.5, 0.45, 1.5], [142, 91, 56])
            add(f"{side} Plaza Bench Back", "Block", "Wood", [x, 1.45, z - 0.55], [5.5, 1.05, 0.28], [112, 72, 48])
            for leg_x in (x - 2.15, x + 2.15):
                add(f"{side} Plaza Bench Leg", "Block", "Metal", [leg_x, 0.35, z], [0.28, 0.75, 1.2], [72, 83, 97])
        for z in (6, 50):
            x = sign * 18
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
    def align(value):
        return round(max(0.5, round(float(value) / 0.5) * 0.5), 2)

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
        clean_props.append({
            "name": prop_name, "shape": shape, "material": material,
            "position": [align(value) for value in pos],
            "size": [align(value) for value in size],
            "color": visible_prop_color(prop.get("color"), [120, 145, 180]),
            "physics": ("dynamic" if prop.get("physics") == "dynamic" and shape in {"Block", "Ball"}
                        and max(float(v) for v in size) <= 12 else "static"),
        })
    return {
        "name": name, "theme": theme,
        "ground_color": color(plan.get("ground_color"), [88, 166, 91]),
        "ground_material": plan.get("ground_material") if isinstance(plan.get("ground_material"), str) and plan.get("ground_material") in MATERIALS else "Grass",
        "ambient_color": color(plan.get("ambient_color"), [185, 205, 225]),
        "props": clean_props,
        "camera_shots": normalize_camera_shots(plan.get("camera_shots"), duration, usernames),
        "character_placements": normalize_character_placements(plan.get("character_placements"), usernames, visual_request),
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
        "local function makePart(name, size, position, color, material, shape, physicsMode)",
        "    local p = Instance.new('Part')",
        "    p.Name = name",
        "    p.Anchored = physicsMode ~= 'dynamic'",
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
        "-- Full 640-stud walkable ground plate; the blueprint and themed furnishing define the environment.",
        f"makePart('Story Map Ground', {{640, 2, 640}}, {{0, -1, 0}}, {{{plan['ground_color'][0]}, {plan['ground_color'][1]}, {plan['ground_color'][2]}}}, {lua_string(plan['ground_material'])}, 'Block')",
        "-- AI-planned landmarks plus procedurally furnished, theme-matched details.",
    ]
    for prop in plan["props"]:
        pos = ", ".join(map(str, prop["position"]))
        size = ", ".join(map(str, prop["size"]))
        color = ", ".join(map(str, prop["color"]))
        lines.append(
            f"makePart({lua_string(prop['name'])}, {{{size}}}, {{{pos}}}, {{{color}}}, "
            f"{lua_string(prop['material'])}, {lua_string(prop['shape'])}, {lua_string(prop.get('physics', 'static'))})"
        )
    ambient = plan["ambient_color"]
    theme_text = plan.get("theme", "").casefold()
    if any(word in theme_text for word in ("night", "midnight", "nocturnal", "moonlit")):
        clock_time = 20.5
    elif any(word in theme_text for word in ("sunrise", "dawn", "morning")):
        clock_time = 8.0
    else:
        clock_time = 13.5
    lines.extend([
        "-- Match Studio lighting to the user-selected world theme.",
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
    parser.add_argument("duration", type=float)
    parser.add_argument("--json-only", action="store_true")
    parser.add_argument("--strict", action="store_true", help="require a valid AI-authored landmark blueprint")
    parser.add_argument("--fallback", action="store_true", help="build a theme/story-based map without the local AI service")
    parser.add_argument("--theme", default="", help="explicit visual-theme cue for procedural fallback")
    parser.add_argument("--story", default="", help="story context for procedural fallback")
    parser.add_argument("--min-props", type=int, default=8, help="minimum unique AI landmark/building anchors")
    parser.add_argument("--target-props", type=int, default=3000, help="minimum furnished world Parts after deterministic expansion (1260=standard, 3000=dense, 5000=ultra)")
    parser.add_argument("--usernames", type=Path, help="JSON file containing the ordered Roblox cast")
    parser.add_argument("--story-topic", default="", help="explicit user request used to gate optional avatar-body effects")
    args = parser.parse_args()
    source, destination, duration = args.source, args.destination, args.duration
    usernames = json.loads(args.usernames.read_text(encoding="utf-8")) if args.usernames else []
    if not isinstance(usernames, list) or any(not isinstance(name, str) for name in usernames):
        raise SystemExit("usernames file must be a JSON array of strings")
    if not 30 <= duration <= 180:
        raise SystemExit("duration must be 30 to 180 seconds")
    if not 1200 <= args.target_props <= 8000:
        raise SystemExit("target-props must be between 1200 and 8000 furnished Parts")
    if args.fallback:
        raw_plan = procedural_fallback_plan(args.theme, args.story, duration, usernames)
        source_label = "theme/story procedural fallback"
        print("Local AI map service was unavailable; generating a detailed map from the user's theme and story instead.", file=sys.stderr)
    else:
        try:
            raw_plan = decode_response(source)
            if args.strict and (not isinstance(raw_plan, dict) or not isinstance(raw_plan.get("theme"), str) or not raw_plan["theme"].strip()):
                raise ValueError("AI map must include a non-empty prompt-specific theme description")
            source_label = "AI landmark blueprint"
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            if args.strict:
                raise SystemExit(f"Invalid AI map plan: {exc}") from exc
            print(f"Invalid AI map plan ({exc}); using the themed fallback map.", file=sys.stderr)
            raw_plan = procedural_fallback_plan(args.theme, args.story, duration, usernames)
            source_label = "theme/story procedural fallback"
    try:
        anchors = validate(raw_plan, duration, usernames, args.min_props, args.story_topic)
        plan = expand_plan(anchors, args.target_props)
        plan = validate(plan, duration, usernames, args.target_props, args.story_topic)
    except ValueError as exc:
        raise SystemExit(f"Could not construct a valid furnished world: {exc}") from exc
    json_path = destination if args.json_only else destination.with_suffix(".json")
    if not args.json_only:
        emit_lua(plan, destination)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    print(f"Created map data {json_path}: {plan['name']} with {len(plan['props'])} furnished 3D Parts ({source_label} + theme expansion).")


if __name__ == "__main__":
    main()
