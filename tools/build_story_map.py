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

MATERIALS = {"Plastic", "SmoothPlastic", "Concrete", "Grass", "Slate", "Wood", "Metal", "Neon", "Glass", "Brick", "Asphalt"}
SHAPES = {"Block", "Ball", "Cylinder"}

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
         "focus_username": usernames[index % len(usernames)] if usernames else "world",
         "framing": "face" if usernames and index in {max(1, last // 3), max(2, (2 * last) // 3)} else "auto",
         "face_distance": 2.45}
        for index, (pos, target, mode) in enumerate(chosen)
    ]


FACE_EXPRESSIONS = ("neutral", "happy", "sad", "surprised", "worried", "angry", "excited", "thinking")
FACE_FRAMINGS = {"auto", "wide", "face", "close", "closeup", "close-up"}


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
        framing = str(shot.get("framing", "auto") or "auto").strip().lower()
        if framing not in FACE_FRAMINGS:
            framing = "auto"
        shot_face_distance = shot.get("face_distance", 2.45)
        if isinstance(shot_face_distance, bool) or not isinstance(shot_face_distance, (int, float)):
            shot_face_distance = 2.45
        shot_face_distance = min(4.0, max(1.6, float(shot_face_distance)))
        clean.append({
            "time": round(float(time), 2),
            "position": [round(float(v), 2) for v in pos],
            "target": [round(float(v), 2) for v in target],
            "transition": transition,
            "focus_username": focus,
            "framing": framing,
            "face_distance": round(float(shot_face_distance), 2),
        })
        previous = time
    if clean[0]["time"] != 0:
        clean.insert(0, default_camera_shots(duration, usernames)[0])
    if clean[-1]["time"] < duration:
        last = dict(clean[-1])
        last["time"] = float(duration)
        last["transition"] = "smooth"
        last["framing"] = "auto"
        clean.append(last)
    # Roblox-style story shorts always land at least two face close-ups; if the
    # AI forgot them, promote the two most emotional mid-shots instead.
    face_indices = [index for index, shot in enumerate(clean) if shot["framing"] == "face"]
    if duration >= 30 and len(face_indices) < 2 and usernames:
        for index in (len(clean) // 3, (2 * len(clean)) // 3):
            if index < len(clean) and clean[index]["focus_username"] != "world":
                clean[index]["framing"] = "face"
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
        model = normalize_model(prop.get("model"))
        named_building = (bool(words & building_words) and not bool(words & component_words)
                          and size[0] >= 10 and size[1] >= 6 and size[2] >= 8
                          and prop.get("shape") == "Block")
        # A declared building model always becomes a real building, even when the
        # AI drew its anchor small or named it "Story Place".
        declared_building = (model in BUILDING_MODELS and prop.get("shape") in {"Block", "Cylinder"}
                             and min(size[0], size[2]) >= 6 and size[1] >= 4)
        is_building = named_building or declared_building
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
        # Glass inside, potted plants, facade vines and a real gable roof.
        furnish_interior(name, x, y, z, sx, sy, sz, bottom, floor_y, ceiling_y,
                         front, back, left, right, thickness, wall, wood, roof,
                         accent_color(plan, color))

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
        model = normalize_model(prop.get("model", prop.get("kind")))
        if model:
            clean_prop["model"] = model
        clean_props.append(clean_prop)
    return {
        "name": name, "theme": theme,
        "ground_color": color(plan.get("ground_color"), [88, 166, 91]),
        "ground_material": normalize_ground_material(plan.get("ground_material", plan.get("groundMaterial")), "Grass"),
        "ambient_color": color(plan.get("ambient_color", plan.get("ambient_light")), [185, 205, 225]),
        "props": clean_props,
        "camera_shots": normalize_camera_shots(plan.get("camera_shots"), duration, usernames),
        "face_expressions": normalize_face_expressions(plan.get("face_expressions"), duration, usernames),
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
    parser.add_argument("duration", type=duration_arg,
                        help="exact length: 144, 2:24, 2m24s")
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
