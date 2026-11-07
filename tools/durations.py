#!/usr/bin/env python3
"""One source of truth for the short length.

Every tool used to carry its own copy of the duration rule, and they drifted: the
narration gate and the MP4 renderer accepted 90-180 s while the Studio builder
still rejected anything over 60 s, which failed long-form runs at the very end.

The length is free-form: pick any moment you like -- 2:24, 1:47, 3:02 -- and every
stage is told that exact number. `SUGGESTED_DURATIONS` only exists to offer handy
defaults; nothing rejects a length just because it is not round.
"""
from __future__ import annotations

import random
import re

# Seconds. Anything inside this window is allowed; the presets below are just
# convenient starting points shown to the user.
MIN_DURATION = 15
MAX_DURATION = 300

SUGGESTED_DURATIONS = (30, 45, 60, 90, 120, 150, 180)

# Backwards-compatible alias for callers that still talk about "the list".
DURATIONS = SUGGESTED_DURATIONS

_COLON_RE = re.compile(r"^(?:(\d{1,2}):)?(\d{1,2}):(\d{1,2}(?:\.\d+)?)$")
_RANGE_RE = re.compile(r"\s*(?:-|–|—|\bto\b|\bthrough\b|\btill\b|\buntil\b)\s*")
_MOMENT_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*([a-z]*)$")
_UNIT_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)(?![a-z])")
_UNIT_SECONDS = {
    "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
    "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
    "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
}


def _moment(text: str):
    """Parse one side of a window into (amount, unit_multiplier_or_None)."""
    colon = _COLON_RE.match(text)
    if colon:
        hours, minutes, secs = colon.groups()
        return float(int(hours or 0) * 3600 + int(minutes) * 60 + float(secs)), 1.0
    match = _MOMENT_RE.match(text)
    if not match:
        raise ValueError(f"{text!r} is not a length")
    amount, unit = float(match.group(1)), match.group(2)
    if not unit:
        return amount, None
    if unit not in _UNIT_SECONDS:
        raise ValueError(f"{text!r} uses an unknown time unit {unit!r}")
    return amount, float(_UNIT_SECONDS[unit])


def parse_spec(raw):
    """Return (low, high) seconds for an exact length or a length window.

    '2:24' -> (144, 144);  '2-3m' -> (120, 180);  '120 to 180' -> (120, 180).
    The high end is the hard ceiling: a 2-3 minute window never becomes 3:01.
    """
    text = "" if raw is None else str(raw).strip().lower()
    text = re.sub(r"\s+", " ", text.replace(",", " ")).strip()
    if not text:
        raise ValueError("duration is empty")
    text = re.sub(r"^(?:between|from|about|around|roughly|any length from)\s+", "", text)
    text = re.sub(r"\s+(?:long|total|overall|max|maximum|up to)$", "", text).strip()

    # An exact length wins: "2 min and 30 sec" is one length, not a window.
    try:
        seconds = parse_duration(text)
    except ValueError as exact_error:
        exact_message = str(exact_error)
    else:
        return seconds, seconds

    parts = None
    if " and " in text:
        pieces = [piece.strip() for piece in text.split(" and ")]
        if len(pieces) == 2 and all(pieces):
            parts = pieces
    if parts is None:
        pieces = _RANGE_RE.split(text, maxsplit=1)
        if len(pieces) == 2 and all(piece.strip() for piece in pieces):
            parts = [piece.strip() for piece in pieces]

    if parts is None:
        raise ValueError(exact_message)

    left_amount, left_unit = _moment(parts[0])
    right_amount, right_unit = _moment(parts[1])
    # "2-3m" means two to three minutes: the bare side borrows the unit.
    if left_unit is None:
        left_unit = right_unit if right_unit is not None else 1.0
    if right_unit is None:
        right_unit = left_unit
    low, high = int(round(left_amount * left_unit)), int(round(right_amount * right_unit))
    if low > high:
        low, high = high, low
    if not MIN_DURATION <= low <= MAX_DURATION or high > MAX_DURATION:
        raise ValueError(
            f"duration window {format_duration(low)}-{format_duration(high)} is outside "
            f"the supported {format_duration(MIN_DURATION)}-{format_duration(MAX_DURATION)}")
    return low, high


def choose_length(raw, seed=None):
    """Pick the exact ending, the way the AI would: never a round minute.

    An exact request is honoured to the second. A window is treated as a bag of
    endings: the pick lands in the last minute of the window and is nudged off
    round numbers, so choosing 2-3 minutes gives something like 2:59 or 2:47 --
    never 3:00 and never a new minute added on top.
    """
    low, high = parse_spec(raw)
    if low == high:
        return low
    # Never land exactly on the next whole minute: 2-3m tops out at 2:59.
    if high % 60 == 0:
        high -= 1
    window_low = max(low, high - 59)
    candidates = [value for value in range(window_low, high + 1) if value % 30]
    if not candidates:
        candidates = list(range(window_low, high + 1))
    return random.Random(seed).choice(candidates)


def format_duration(seconds) -> str:
    """Render seconds the way a person reads a clock: 144 -> '2:24'."""
    total = int(round(float(seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def parse_duration(raw) -> int:
    """Turn whatever the user typed into whole seconds.

    Accepts plain seconds ('144'), clock style ('2:24', '0:02:24'), and words
    ('2m24s', '2 min 24 sec', '2.5 minutes'). Raises ValueError when the text is
    not a length or falls outside MIN_DURATION..MAX_DURATION.
    """
    if isinstance(raw, bool):
        raise ValueError(f"duration must be a length of time, got {raw!r}")
    if isinstance(raw, (int, float)):
        return _bounded(float(raw), raw)
    text = "" if raw is None else str(raw).strip().lower()
    if not text:
        raise ValueError("duration is empty")
    text = text.replace(",", " ").replace("and", " ").strip()
    if _RANGE_RE.search(text):
        raise ValueError(f"{raw!r} is a window of lengths, not one length")

    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return _bounded(float(text), raw)

    colon = _COLON_RE.match(text)
    if colon:
        hours, minutes, secs = colon.groups()
        total = int(hours or 0) * 3600 + int(minutes) * 60 + float(secs)
        return _bounded(total, raw)

    tokens = _UNIT_RE.findall(text)
    if tokens:
        leftover = _UNIT_RE.sub(" ", text)
        leftover = re.sub(r"[\s,.+-]+", "", leftover)
        if not leftover:
            total = sum(float(amount) * _UNIT_SECONDS[unit] for amount, unit in tokens)
            return _bounded(total, raw)

    raise ValueError(
        f"duration {raw!r} is not a length like 144, 2:24, or 2m24s "
        f"(allowed: {MIN_DURATION}-{MAX_DURATION} seconds)")


def _bounded(seconds: float, raw) -> int:
    value = int(round(seconds))
    if not MIN_DURATION <= value <= MAX_DURATION:
        raise ValueError(
            f"duration {raw!r} is {format_duration(value)}; it must be between "
            f"{format_duration(MIN_DURATION)} and {format_duration(MAX_DURATION)} "
            f"({MIN_DURATION}-{MAX_DURATION} seconds)")
    return value


def is_supported(duration) -> bool:
    """True when a duration is a usable length (any value inside the window)."""
    try:
        parse_duration(duration)
    except (TypeError, ValueError):
        return False
    return True


def check_duration(duration) -> float:
    """Return the duration as a float, or raise ValueError with a clear message."""
    try:
        return float(parse_duration(duration))
    except ValueError as exc:
        raise ValueError(str(exc)) from exc


def duration_arg(text: str) -> int:
    """argparse type: free-form length with a friendly error message."""
    import argparse

    try:
        return parse_duration(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def describe() -> str:
    presets = ", ".join(str(choice) for choice in SUGGESTED_DURATIONS)
    return (f"any length from {format_duration(MIN_DURATION)} to "
            f"{format_duration(MAX_DURATION)} (e.g. 2:24, 144, 2m24s; "
            f"popular: {presets})")
