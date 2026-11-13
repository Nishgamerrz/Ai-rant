#!/usr/bin/env python3
"""Choose a bounded Edge TTS rate that moves a take toward its target length.

Edge TTS rates are relative to normal speaking speed. If a take measured at
+4% is too short, the correction must account for that existing +4% baseline;
using only ``seconds / target - 1`` over-slows the voice and can turn a short
take into one that exceeds the video duration.
"""
from __future__ import annotations

import argparse
import math
import re

MIN_RATE_PERCENT = -20
MAX_RATE_PERCENT = 4
_RATE = re.compile(r"^([+-]?\d+(?:\.\d+)?)%?$")


def parse_rate(value: str | float | int) -> float:
    """Parse an Edge TTS rate such as ``+4%`` into a numeric percentage."""
    if isinstance(value, bool):
        raise ValueError("rate must be a numeric percentage")
    if isinstance(value, (int, float)):
        result = float(value)
    else:
        match = _RATE.fullmatch(str(value).strip())
        if not match:
            raise ValueError(f"invalid Edge TTS rate: {value!r}")
        result = float(match.group(1))
    if not math.isfinite(result) or result <= -100:
        raise ValueError("rate must be finite and greater than -100%")
    return result


def rate_for_target(seconds: float, target_seconds: float, current_rate: str | float | int,
                    *, minimum: int = MIN_RATE_PERCENT,
                    maximum: int = MAX_RATE_PERCENT) -> int:
    """Return a clamped integer rate that should move ``seconds`` to target.

    The measured duration scales approximately as 1 / speaking speed. Convert
    the measured rate to a speed factor, multiply it by the duration ratio, then
    convert back to a rate. For example, 112.27 seconds at +4% targeting 132
    seconds needs about -12%, not -15%.
    """
    seconds = float(seconds)
    target_seconds = float(target_seconds)
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("measured narration duration must be positive and finite")
    if not math.isfinite(target_seconds) or target_seconds <= 0:
        raise ValueError("target duration must be positive and finite")
    if minimum > maximum:
        raise ValueError("minimum rate cannot exceed maximum rate")

    current_percent = parse_rate(current_rate)
    current_speed = 1.0 + current_percent / 100.0
    desired_speed = current_speed * seconds / target_seconds
    ideal_percent = (desired_speed - 1.0) * 100.0
    rounded = int(round(ideal_percent))
    return max(int(minimum), min(int(maximum), rounded))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("seconds", type=float, help="measured narration duration")
    parser.add_argument("target", type=float, help="target video duration")
    parser.add_argument("--current-rate", required=True,
                        help="current Edge TTS rate, e.g. +4%% or -12%%")
    args = parser.parse_args()
    print(f"{rate_for_target(args.seconds, args.target, args.current_rate):+d}%")


if __name__ == "__main__":
    main()
