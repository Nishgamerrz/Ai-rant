"""Time-of-day choices shared by the MP4 and generated Roblox Studio place."""
from __future__ import annotations

import re

TIME_OF_DAY_CHOICES = ("auto", "dawn", "day", "sunset", "night")
CLOCK_TIMES = {
    "dawn": 6.5,
    "day": 13.5,
    "sunset": 18.2,
    "night": 20.5,
}
SCENE_TIME_CHOICES = tuple(CLOCK_TIMES)

_ALIASES = {
    "morning": "dawn", "sunrise": "dawn", "daybreak": "dawn", "early morning": "dawn",
    "dusk": "sunset", "evening": "sunset", "golden hour": "sunset",
    "midday": "day", "afternoon": "day",
    "midnight": "night", "nocturnal": "night", "moonlit": "night", "moonlight": "night",
    "after dark": "night",
}
_SCENE_TIME_PATTERN = re.compile(
    r"\b(early morning|golden hour|after dark|daybreak|sunrise|morning|dawn|"
    r"midday|afternoon|day|sunset|dusk|evening|midnight|nocturnal|moonlit|moonlight|night)\b",
    re.IGNORECASE,
)


def canonical_time_of_day(value: str) -> str | None:
    """Normalize a named hour, returning ``None`` for an unknown value."""
    name = re.sub(r"[-_]", " ", str(value or "").strip().casefold())
    name = _ALIASES.get(name, name)
    return name if name in CLOCK_TIMES else None


def resolve_time_of_day(requested: str = "auto", context: str = "") -> str:
    """Resolve a user choice or infer one coherent lighting preset from context.

    An explicit choice always wins over words in the story/theme. ``auto`` is
    intentionally conservative: it uses a named time when the prompt has one and
    otherwise keeps the familiar bright-daylight look.
    """
    choice = str(requested or "auto").strip().casefold().replace("-", "_")
    if choice in {"auto", ""}:
        text = str(context or "").casefold()
        for match in _SCENE_TIME_PATTERN.finditer(text):
            normalized = canonical_time_of_day(match.group(0))
            if normalized:
                return normalized
        return "day"
    normalized = canonical_time_of_day(choice)
    if normalized:
        return normalized
    raise ValueError(f"unknown time of day {requested!r}; choose from {', '.join(TIME_OF_DAY_CHOICES)}")


def scene_time_sequence(notes: str) -> list[str]:
    """Extract a left-to-right sequence of named hours from fallback directions.

    The AI map planner handles detailed per-scene instructions. This small
    deterministic parser is for the procedural fallback: e.g. ``night, then
    sunset`` assigns those hours to successive portions of the camera tour.
    """
    sequence: list[str] = []
    for match in _SCENE_TIME_PATTERN.finditer(str(notes or "")):
        hour = canonical_time_of_day(match.group(0))
        if hour and (not sequence or sequence[-1] != hour):
            sequence.append(hour)
    return sequence


def apply_scene_time_sequence(shots: list[dict], notes: str) -> bool:
    """Apply a simple ordered hour sequence to camera shots; return if applied."""
    sequence = scene_time_sequence(notes)
    if not sequence or not shots:
        return False
    count = len(shots)
    for index, shot in enumerate(shots):
        slot = min(len(sequence) - 1, index * len(sequence) // count)
        shot["time_of_day"] = sequence[slot]
    return True
