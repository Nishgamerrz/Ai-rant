#!/usr/bin/env python3
"""Decide whether the story happens INSIDE a room, and size that room.

Run #109 told the real story ("two brothers keep each other awake in their
cramped bedroom") and then built a 640-stud open map with a workshop wall at
X=100: the video showed an outdoor world with no room in it, because every world
this workflow ever built was an open-air landmark map. A bedroom story needs a
bedroom - four walls, a ceiling, a door, a window, furniture - and a camera that
stays inside it.

This tool reads the user's topic and the finished narration and answers:

    mode=interior|outdoor, width, depth, height, reason

Usage:
    python tools/scene_mode.py --topic "..." --narration dist/narration.txt \
        --github-env "$GITHUB_ENV"
"""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

# Rooms the camera stands inside. Word-boundary matched so "bedroom" counts but
# "classrooms are cool in this city" style prose is still handled by count.
INTERIOR_ROOMS = (
    "bedroom", "bed room", "living room", "kitchen", "bathroom", "classroom",
    "attic", "basement", "cellar", "garage", "dorm", "dormitory", "office",
    "study", "lounge", "hallway", "corridor", "stairwell", "closet", "cupboard",
    "treehouse", "tree house", "tent", "cabin", "hut", "igloo", "cave", "cell",
    "spaceship", "space ship", "rocket cabin", "submarine", "elevator", "lift",
    "bus", "train carriage", "train", "car interior", "van", "shop", "store",
    "cafe", "café", "restaurant", "bakery", "library", "laboratory", "lab",
    "workshop", "class room", "dining room", "bedrooms",
)

# Words that mean the story is a "somewhere in this world" story after all.
OUTDOOR_WORDS = (
    "street", "city", "town", "village", "forest", "jungle", "beach", "desert",
    "mountain", "island", "ocean", "sea", "sky", "field", "park", "school yard",
    "playground", "market square", "rooftop", "roof", "garden", "bridge",
    "highway", "road", "canyon", "valley", "space", "planet", "moon",
)

# Kept small on purpose: a cramped room reads better on a phone screen, and the
# cast lane (|X| < 20, Z 4-54) is re-centred inside the room later.
ROOM_SIZES = {
    "tiny": (26.0, 26.0, 10.0),
    "small": (34.0, 34.0, 11.0),
    "medium": (44.0, 44.0, 13.0),
}


def _count(words: tuple[str, ...], text: str) -> int:
    total = 0
    for word in words:
        total += len(re.findall(rf"\b{re.escape(word)}\b", text))
    return total


def detect(topic: str = "", narration: str = "") -> dict:
    """Return {"mode", "size", "width", "depth", "height", "reason"}."""
    topic_text = str(topic or "").lower()
    story_text = str(narration or "").lower()
    # The topic is what the user asked for; the narration says where it happens.
    indoor = _count(INTERIOR_ROOMS, topic_text) + _count(INTERIOR_ROOMS, story_text)
    outdoor = _count(OUTDOOR_WORDS, topic_text) + _count(OUTDOOR_WORDS, story_text)
    cramped = bool(re.search(r"\b(cramped|tiny|small|narrow|little|packed|cosy|cozy)\b",
                             topic_text + " " + story_text))
    if indoor == 0 or indoor < outdoor:
        size = "medium"
        return {"mode": "outdoor", "size": size, "width": 0.0, "depth": 0.0, "height": 0.0,
                "reason": (f"no room named in the story ({outdoor} outdoor word(s)); "
                           f"building an open world")}
    size = "tiny" if cramped or indoor >= 3 else "small"
    width, depth, height = ROOM_SIZES[size]
    return {"mode": "interior", "size": size, "width": width, "depth": depth,
            "height": height,
            "reason": (f"the story happens inside ({indoor} room word(s) vs {outdoor} "
                       f"outdoor), so this is a {size} room {width:.0f}x{depth:.0f}x"
                       f"{height:.0f} studs")}


def prompt_block(mode: dict) -> str:
    """The prompt paragraph that makes the AI design a room, not a city."""
    if mode["mode"] != "interior":
        return ""
    width, depth, height = mode["width"], mode["depth"], mode["height"]
    return (
        "THIS WHOLE SCENE HAPPENS INSIDE ONE ROOM. Do not design a city, a street, a plaza or "
        "an open world: design the inside of a room.\n"
        "This paragraph overrides every later instruction in this prompt that describes an "
        "outdoor world: ignore the 640-by-640-stud map, the three building cores, the "
        "18-40-stud building sizes and the 20-stud-wide cast lane. There are NO buildings in "
        "this scene - there is one room, and the props are the furniture inside it.\n"
        f"The room is about {width:.0f} studs wide (X), {depth:.0f} deep (Z) and {height:.0f} "
        f"tall (Y), centred on the cast at X=0, Z=24. Keep every prop inside X and Z between "
        f"-{width / 2:.0f} and {width / 2:.0f} (offset so the room spans Z=24-{depth / 2:.0f} to "
        f"24+{depth / 2:.0f}) and below Y={height:.0f}. Props are furniture and room features, "
        "not buildings: bed, bunk bed, nightstand, desk, chair, wardrobe, rug, lamp, bookshelf, "
        "door, window with glass, curtains, posters, toy chest, plant, fan, small table. Use "
        "\"model\" values like bed, furniture, shelf, lamp, plant, rug, window, door. Sizes are "
        "real furniture sizes (a bed 6x3 wide, a nightstand 2x2), never 20-stud buildings.\n"
        f"Camera: every shot must be INSIDE the room (X within +/-{width / 2 - 2:.0f}, Z within "
        f"the room, Y between 3 and {height - 1:.0f}), so the viewer sees walls, floor and "
        "ceiling - never a view from outside or above the roof. The establishing shot is from "
        "a corner of the room, not from 150 studs away."
    )


def write_env(mode: dict, path: str | None) -> None:
    if not path:
        return
    with Path(path).open("a", encoding="utf-8") as handle:
        handle.write(f"WORLD_MODE={mode['mode']}\n")
        handle.write(f"ROOM_SIZE={mode['size']}\n")
        handle.write(f"ROOM_WIDTH={mode['width']}\n")
        handle.write(f"ROOM_DEPTH={mode['depth']}\n")
        handle.write(f"ROOM_HEIGHT={mode['height']}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", default="", help="the story topic as typed/AI-refined")
    parser.add_argument("--narration", type=Path, help="finished narration file")
    parser.add_argument("--github-env", help="path of $GITHUB_ENV")
    parser.add_argument("--prompt-out", type=Path, help="write the prompt paragraph here")
    parser.add_argument("--json", action="store_true", help="print the detection as JSON")
    args = parser.parse_args()
    narration = ""
    if args.narration and args.narration.is_file():
        narration = args.narration.read_text(encoding="utf-8")
    mode = detect(args.topic or os.environ.get("STORY_TOPIC", ""), narration)
    write_env(mode, args.github_env)
    if args.prompt_out:
        block = prompt_block(mode)
        args.prompt_out.write_text((block + "\n") if block else "", encoding="utf-8")
    if args.json:
        import json
        print(json.dumps(mode))
    else:
        print(f"Scene mode: {mode['mode']} ({mode['reason']}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
