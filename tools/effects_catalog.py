#!/usr/bin/env python3
"""The particle effects the AI can put in a Roblox short, and how they look.

A world full of static Parts still looks dead: a Roblox story short lives on the
little sparks that tell you where the magic is. This module is the catalogue the
model chooses from, and the rulebook the renderer follows.

Two layers:

* ``FAMILIES`` - twenty ways a particle system behaves (sparkles rise and twinkle,
  smoke drifts up and swells, rain falls fast and thin, confetti tumbles). Each
  family carries the motion parameters and the sprite the renderer draws.
* ``PALETTES`` - twenty-six colours with a readable name ("gold", "cyan",
  "ember red").

A preset is every family in every palette, so ``gold sparkles`` and ``cyan smoke``
both exist: 20 x 26 = 520 named effects, each one a complete, ready parameter
set. On top of that the AI can pass its own colour, rate, size, speed and
lifetime, so "increase the density" or "make it darker red" is a number away.

Nothing here imports anything but the standard library: the workflow's preflight
runs it on a bare runner.
"""
from __future__ import annotations

import argparse
import json
import re

# Each family: how many particles a full density uses, how big each one is in
# studs, how fast it travels, how long it lives, how hard gravity pulls it, and
# which sprite the renderer paints it with.
#   rate      particles at density 1.0 (renderer caps the total)
#   size      sprite size in studs
#   speed     studs per second
#   life      seconds each particle lives
#   gravity   negative falls, positive rises
#   spread    how wide the cone is (0 = straight up, 1 = full sphere)
#   look      sprite: star, glow, puff, streak, flake, bubble, heart, petal,
#             leaf, bolt, square
FAMILIES = {
    "sparkles": dict(rate=34, size=0.42, speed=1.5, life=1.6, gravity=0.7, spread=0.75, look="star", twinkle=True),
    "glitter": dict(rate=46, size=0.30, speed=0.9, life=2.2, gravity=1.2, spread=0.6, look="star", twinkle=True),
    "stars": dict(rate=22, size=0.55, speed=0.6, life=3.0, gravity=0.2, spread=0.9, look="star", twinkle=True),
    "embers": dict(rate=24, size=0.24, speed=1.2, life=2.4, gravity=1.0, spread=0.5, look="glow", twinkle=True),
    "fire": dict(rate=40, size=0.75, speed=1.9, life=1.0, gravity=1.6, spread=0.35, look="glow", twinkle=False),
    "flames": dict(rate=52, size=0.95, speed=2.4, life=0.85, gravity=1.9, spread=0.3, look="puff", twinkle=False),
    "smoke": dict(rate=20, size=1.3, speed=0.9, life=3.4, gravity=0.55, spread=0.45, look="puff", twinkle=False),
    "mist": dict(rate=30, size=2.2, speed=0.35, life=5.0, gravity=0.12, spread=0.9, look="puff", twinkle=False),
    "fog": dict(rate=18, size=3.2, speed=0.20, life=7.0, gravity=0.02, spread=1.0, look="puff", twinkle=False),
    "dust": dict(rate=26, size=0.22, speed=0.4, life=3.2, gravity=-0.05, spread=0.8, look="square", twinkle=False),
    "pollen": dict(rate=30, size=0.30, speed=0.5, life=4.0, gravity=0.10, spread=0.9, look="glow", twinkle=True),
    "confetti": dict(rate=48, size=0.34, speed=2.2, life=2.6, gravity=-1.6, spread=0.55, look="square", twinkle=False),
    "snow": dict(rate=44, size=0.34, speed=0.8, life=5.0, gravity=-0.35, spread=0.9, look="flake", twinkle=False),
    "rain": dict(rate=70, size=0.16, speed=6.5, life=1.6, gravity=-6.0, spread=0.5, look="streak", twinkle=False),
    "bubbles": dict(rate=26, size=0.42, speed=0.9, life=2.8, gravity=0.45, spread=0.7, look="bubble", twinkle=False),
    "hearts": dict(rate=16, size=0.46, speed=0.8, life=2.4, gravity=0.5, spread=0.5, look="heart", twinkle=False),
    "petals": dict(rate=24, size=0.40, speed=1.0, life=4.0, gravity=-0.6, spread=0.85, look="petal", twinkle=False),
    "leaves": dict(rate=20, size=0.50, speed=1.2, life=4.4, gravity=-0.9, spread=0.9, look="leaf", twinkle=False),
    "lightning": dict(rate=10, size=0.9, speed=4.0, life=0.35, gravity=0.0, spread=0.35, look="bolt", twinkle=True),
    "magic": dict(rate=38, size=0.38, speed=1.7, life=2.0, gravity=0.9, spread=0.85, look="star", twinkle=True),
}

PALETTES = {
    "gold": (255, 199, 64),
    "amber": (255, 162, 48),
    "copper": (214, 122, 63),
    "ember": (255, 96, 32),
    "red": (232, 52, 52),
    "crimson": (188, 28, 64),
    "rose": (244, 122, 148),
    "pink": (255, 138, 214),
    "magenta": (206, 74, 214),
    "violet": (146, 96, 240),
    "indigo": (96, 88, 208),
    "blue": (64, 118, 236),
    "azure": (62, 164, 244),
    "cyan": (64, 214, 232),
    "teal": (44, 186, 170),
    "mint": (128, 236, 186),
    "emerald": (52, 200, 112),
    "lime": (168, 226, 66),
    "olive": (168, 168, 72),
    "yellow": (250, 232, 88),
    "cream": (252, 236, 200),
    "white": (246, 248, 252),
    "silver": (196, 206, 218),
    "slate": (128, 142, 160),
    "brown": (150, 108, 70),
    "rainbow": (255, 128, 220),
}

# The keys of a resolved effect. build_story_map writes exactly these; the page
# reads exactly these; tests/test_map_features.py fails if the three drift.
EFFECT_KEYS = ("family", "color", "rate", "size", "speed", "life", "gravity", "spread", "look", "twinkle")


def _clamp(value, low, high, default):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number:  # NaN
        return default
    return max(low, min(high, number))


def _color(value, fallback):
    if isinstance(value, (list, tuple)) and len(value) == 3:
        try:
            return [max(0, min(255, int(round(float(channel))))) for channel in value]
        except (TypeError, ValueError):
            return list(fallback)
    return list(fallback)


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").casefold()).strip()


def preset_names() -> list[str]:
    """Every named effect: 20 families x 26 palettes."""
    return [f"{palette} {family}" for family in FAMILIES for palette in PALETTES]


def preset(name: str) -> dict | None:
    """Look up one named effect, e.g. "gold sparkles". None if it is not one."""
    key = _key(name)
    if not key:
        return None
    words = key.split()
    palette = next((word for word in words if word in PALETTES), None)
    family = next((word for word in words if word in FAMILIES), None)
    if not family:
        return None
    palette = palette or "gold"
    return resolve({"family": family, "color": list(PALETTES[palette])})


def resolve(value) -> dict | None:
    """Turn whatever the model wrote into a complete, bounded effect.

    Accepts a preset name ("cyan sparkles"), a family name ("smoke"), or an object
    {"family"|"name", "color", "rate", "size", "speed", "life", "gravity",
    "spread"}. Unknown words fall back to sparkles rather than dropping the effect,
    because a wrong effect is a nicer failure than a dead world.
    """
    if value in (None, "", {}, []):
        return None
    spec = {}
    if isinstance(value, str):
        spec["name"] = value
    elif isinstance(value, dict):
        spec = dict(value)
    else:
        return None

    family = _key(spec.get("family") or spec.get("style") or spec.get("kind") or "")
    palette_color = None
    if family not in FAMILIES:
        words = _key(spec.get("name") or spec.get("preset") or family).split()
        family = next((word for word in words if word in FAMILIES), "")
        palette = next((word for word in words if word in PALETTES), None)
        if palette:
            palette_color = list(PALETTES[palette])
    if family not in FAMILIES:
        family = "sparkles"
    base = FAMILIES[family]

    color = _color(spec.get("color"), palette_color or PALETTES["gold"])
    return {
        "family": family,
        "color": color,
        "rate": round(_clamp(spec.get("rate", spec.get("density")), 0.05, 1.0, 0.6), 3),
        "size": round(_clamp(spec.get("size"), 0.05, 6.0, base["size"]), 3),
        "speed": round(_clamp(spec.get("speed"), 0.0, 12.0, base["speed"]), 3),
        "life": round(_clamp(spec.get("life", spec.get("lifetime")), 0.1, 12.0, base["life"]), 3),
        "gravity": round(_clamp(spec.get("gravity"), -10.0, 6.0, base["gravity"]), 3),
        "spread": round(_clamp(spec.get("spread"), 0.0, 1.0, base["spread"]), 3),
        "look": base["look"],
        "twinkle": bool(base.get("twinkle", False)),
    }


def catalog() -> dict:
    return {"families": sorted(FAMILIES), "palettes": sorted(PALETTES),
            "presets": preset_names()}


def describe(limit: int = 0) -> str:
    """A short, prompt-sized description of what can be emitted."""
    families = ", ".join(sorted(FAMILIES))
    palettes = ", ".join(sorted(PALETTES))
    text = (f"effects: families {families}; colours {palettes}; any family+colour pair "
            f"is a preset (e.g. \"gold sparkles\", \"cyan smoke\"), {len(preset_names())} "
            "presets in total")
    if limit:
        text += "; " + ", ".join(preset_names()[:limit])
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print the whole catalogue")
    parser.add_argument("--names", action="store_true", help="print every preset name")
    parser.add_argument("--describe", action="store_true", help="print the prompt summary")
    parser.add_argument("--resolve", help="resolve one effect name and print it")
    args = parser.parse_args()
    if args.names:
        print("\n".join(preset_names()))
    elif args.resolve:
        print(json.dumps(resolve(args.resolve), indent=2))
    elif args.describe:
        print(describe())
    else:
        print(json.dumps(catalog(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
