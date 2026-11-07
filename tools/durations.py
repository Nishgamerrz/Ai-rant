#!/usr/bin/env python3
"""One source of truth for supported short length.

Every tool used to carry its own copy of the duration rule, and they drifted: the
narration gate and the MP4 renderer accepted 90–180 s while the Studio builder
still rejected anything over 60 s, which failed long-form runs at the very end.
Import from here instead of writing `choices=(30, 45, 60)` again.
"""
from __future__ import annotations

# Seconds. 30 s is the shortest supported story beat; 180 s is the long-form cap.
DURATIONS = (30, 45, 60, 90, 120, 150, 180)
MIN_DURATION = DURATIONS[0]
MAX_DURATION = DURATIONS[-1]

# Human-readable list for argument parsers and error messages.
DURATION_CHOICES = DURATIONS


def is_supported(duration) -> bool:
    """True when a duration is one of the selectable short lengths."""
    try:
        value = float(duration)
    except (TypeError, ValueError):
        return False
    return any(abs(value - choice) < 1e-9 for choice in DURATIONS)


def check_duration(duration, *, strict: bool = True) -> float:
    """Return the duration as a float, or raise ValueError with a clear message.

    `strict=False` allows any value inside the supported range, which the
    renderer/builder accept so a caller may pass e.g. 75 seconds explicitly.
    """
    try:
        value = float(duration)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"duration must be a number of seconds, got {duration!r}") from exc
    if strict:
        if not is_supported(value):
            options = ", ".join(str(choice) for choice in DURATIONS)
            raise ValueError(f"duration must be one of {options} seconds, got {value:g}")
    elif not MIN_DURATION <= value <= MAX_DURATION:
        raise ValueError(
            f"duration must be between {MIN_DURATION} and {MAX_DURATION} seconds, got {value:g}")
    return value


def describe() -> str:
    return f"{MIN_DURATION}–{MAX_DURATION} seconds ({', '.join(str(choice) for choice in DURATIONS)})"
