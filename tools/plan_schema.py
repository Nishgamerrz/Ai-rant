#!/usr/bin/env python3
"""Emit the JSON schema the world/camera/face plan must follow.

The plan request used to ask for plain `format: "json"`, so a model was free to
invent its own key names: one 22-minute run answered with `"type"` instead of
`"shape"`, lowercase `"brick"` materials and `"ambient_light"`, and the whole
blueprint was rejected after the wait. A schema makes those answers impossible:
the material and shape names are enums, the axis arrays are fixed-length numbers,
and every character field is limited to the cast that was actually supplied.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_story_map import MATERIALS, SHAPES  # noqa: E402

EXPRESSIONS = ("neutral", "happy", "sad", "surprised", "worried", "angry", "excited", "thinking")
MATERIAL_LIST = sorted(MATERIALS)
SHAPE_LIST = ["Block", "Ball", "Cylinder"]
assert set(SHAPE_LIST) == set(SHAPES)


def axis(low: float, high: float, *, integer: bool = False) -> dict:
    kind = "integer" if integer else "number"
    return {"type": "array", "items": {"type": kind, "minimum": low, "maximum": high},
            "minItems": 3, "maxItems": 3}


def build_schema(usernames=()) -> dict:
    cast = [name for name in usernames if isinstance(name, str) and name.strip()]
    username = {"type": "string"}
    if cast:
        username["enum"] = cast
    focus = {"type": "string"}
    focus["enum"] = [*cast, "world"] if cast else ["world"]

    prop = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "shape": {"type": "string", "enum": SHAPE_LIST},
            "material": {"type": "string", "enum": MATERIAL_LIST},
            "position": axis(-250, 250),
            "size": axis(0.5, 64),
            "color": {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 255},
                      "minItems": 3, "maxItems": 3},
            "physics": {"type": "string", "enum": ["static", "dynamic"]},
        },
        "required": ["name", "shape", "material", "position", "size", "color"],
    }
    shot = {
        "type": "object",
        "properties": {
            "time": {"type": "number", "minimum": 0, "maximum": 600},
            "position": axis(-320, 320),
            "target": axis(-320, 320),
            "focus_username": focus,
            "transition": {"type": "string", "enum": ["smooth", "snap"]},
            "framing": {"type": "string", "enum": ["auto", "face"]},
            "face_distance": {"type": "number", "minimum": 0.8, "maximum": 12},
        },
        "required": ["time", "position", "target", "focus_username", "transition"],
    }
    beat = {
        "type": "object",
        "properties": {
            "time": {"type": "number", "minimum": 0, "maximum": 600},
            "expression": {"type": "string", "enum": list(EXPRESSIONS)},
            "intensity": {"type": "number", "minimum": 0, "maximum": 1},
            "username": username,
        },
        "required": ["time", "expression", "username"],
    }
    placement = {
        "type": "object",
        "properties": {
            "username": username,
            "role": {"type": "string", "enum": ["lead", "supporting"]},
            "position": axis(-70, 70),
        },
        "required": ["username", "role", "position"],
    }
    return {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "theme": {"type": "string"},
            "ground_material": {"type": "string", "enum": MATERIAL_LIST},
            "ground_color": {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 255},
                             "minItems": 3, "maxItems": 3},
            "ambient_color": {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 255},
                              "minItems": 3, "maxItems": 3},
            # The validator requires this many anchors; the schema enforces it so a
            # model cannot answer with six props and get rejected after a long wait.
            "props": {"type": "array", "items": prop, "minItems": 8},
            "character_placements": {"type": "array", "items": placement},
            "camera_shots": {"type": "array", "items": shot, "minItems": 6},
            "face_expressions": {"type": "array", "items": beat, "minItems": 6},
            "search_queries": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["name", "theme", "props", "character_placements",
                     "camera_shots", "face_expressions", "search_queries"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--usernames", type=Path,
                        help="JSON array of the exact cast usernames")
    parser.add_argument("--output", type=Path, help="write the schema here (default: stdout)")
    args = parser.parse_args()
    cast = []
    if args.usernames and args.usernames.exists():
        data = json.loads(args.usernames.read_text(encoding="utf-8"))
        if isinstance(data, list):
            cast = [item for item in data if isinstance(item, str)]
    schema = build_schema(cast)
    text = json.dumps(schema, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
        print(f"Wrote plan schema for {len(cast)} username(s) to {args.output}")
    else:
        print(text)


if __name__ == "__main__":
    main()
