#!/usr/bin/env python3
"""Create a subtle, timed procedural sound bed for a short using FFmpeg filters."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def main():
    if len(sys.argv) != 4:
        raise SystemExit("usage: create_sound_bed.py MAP.json DURATION_SECONDS OUTPUT.wav")
    plan_path, output_path = Path(sys.argv[1]), Path(sys.argv[3])
    duration = float(sys.argv[2])
    if not 30 <= duration <= 60:
        raise SystemExit("duration must be between 30 and 60 seconds")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))

    inputs = ["-f", "lavfi", "-i", f"anoisesrc=color=pink:sample_rate=48000:duration={duration:g}"]
    graph = ["[0:a]lowpass=f=1500,highpass=f=100,volume=0.035[ambient]"]
    labels = ["[ambient]"]

    def add_noise(label, seconds, start, *, cutoff=1800, volume=0.12, fade_in=0.015):
        index = len([part for part in inputs if part == "-i"])
        # Add one deterministic white-noise source for this transient.
        inputs.extend(["-f", "lavfi", "-i", f"anoisesrc=color=white:sample_rate=48000:duration={seconds:g}:seed={index}"])
        delay = max(0, round(start * 1000))
        graph.append(
            f"[{index}:a]highpass=f=180,lowpass=f={cutoff},"
            f"afade=t=in:st=0:d={fade_in:g},afade=t=out:st={max(0.01, seconds - 0.18):g}:d=0.18,"
            f"volume={volume:g},adelay={delay}|{delay}[{label}]"
        )
        labels.append(f"[{label}]")

    # A few soft, generic footsteps establish movement without competing with speech.
    for index, at in enumerate((1.0, 1.55, 2.1)):
        add_noise(f"step{index}", 0.18, at, cutoff=520, volume=0.20, fade_in=0.003)

    # Gentle cloth/paper rustle around the midpoint, followed by a restrained positive chime.
    add_noise("rustle", 0.75, duration * 0.46, cutoff=4200, volume=0.075, fade_in=0.08)
    chime_index = len([part for part in inputs if part == "-i"])
    chime_at = duration * 0.72
    inputs.extend(["-f", "lavfi", "-i", f"sine=frequency=880:sample_rate=48000:duration=0.7"])
    graph.append(
        f"[{chime_index}:a]afade=t=in:st=0:d=0.04,afade=t=out:st=0.2:d=0.5,"
        f"volume=0.10,adelay={round(chime_at * 1000)}|{round(chime_at * 1000)}[chime]"
    )
    labels.append("[chime]")

    # Camera snap cuts receive quiet, short whooshes at their planned story beats.
    for index, shot in enumerate(plan.get("camera_shots", [])):
        if index and shot.get("transition") == "snap" and 0 < float(shot["time"]) < duration - 0.5:
            add_noise(f"whoosh{index}", 0.42, float(shot["time"]), cutoff=5000, volume=0.055, fade_in=0.06)

    graph.append(
        f"{''.join(labels)}amix=inputs={len(labels)}:duration=first:dropout_transition=0,"
        "alimiter=limit=0.85[out]"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *inputs,
               "-filter_complex", ";".join(graph), "-map", "[out]", "-t", f"{duration:g}",
               "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(output_path)]
    subprocess.run(command, check=True)
    if not output_path.is_file() or output_path.stat().st_size < 100_000:
        raise SystemExit("FFmpeg did not create a complete sound-effects bed")
    print(f"Generated timed sound-effects bed ({duration:g}s) with footsteps, rustle, chime, and camera whooshes.")


if __name__ == "__main__":
    main()
