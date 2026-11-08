#!/usr/bin/env python3
"""Look at the finished MP4 the way a viewer would, and refuse a broken one.

Everything checked so far measured the *renderer*: the projection probe reads the
camera, and the frame audit reads the JPEG frames on their way into ffmpeg. That
still leaves the possibility that what comes out of ffmpeg is not what went in -
a non-square sample aspect ratio, a rotation flag, or a rescale that turns a
square world into an oval.

This script measures the shipped file instead:

* ffprobe: size, sample aspect ratio, display aspect ratio, rotation flag,
  codecs, frame rate and duration - the properties a player uses to decide how
  to stretch the picture;
* the actual decoded pixels: eight frames spread across the whole short are
  decoded and measured for brightness, pure black, blown-out white and colour;
* black slabs: dark regions are found as connected clusters of dark cells, and a
  large, rectangular, near-black cluster is reported as the black-block artefact
  rather than being averaged away;
* flat frames: a frame with almost no variation means the world failed to draw.

The frames it extracts are published next to the run (see the preview step in
main.yml), so a broken picture can be looked at instead of guessed about.

    python tools/inspect_short.py --video dist/Roblox_2K_YouTube_Short.mp4 \
        --frames-dir dist/preview --report dist/mp4_inspection.md
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

WIDTH, HEIGHT = 1440, 2560
EXPECTED_ASPECT = 9 / 16
# Decoding size for measurement. Same 9:16 shape as the video, small enough that
# the whole frame is a few hundred kilobytes of raw bytes.
PROBE_WIDTH, PROBE_HEIGHT = 180, 320
# A cell is 6x8 probe pixels, so the grid is 30 x 40 cells over the frame.
GRID_COLUMNS, GRID_ROWS = 30, 40

BLACK_LEVEL = 26.0        # luminance below this is "pure black"
WHITE_LEVEL = 232.0       # luminance above this is "blown out"
COLOUR_SATURATION = 0.12  # HSV saturation that counts as a hue
DARK_CELL = 24.0          # a grid cell this dark is part of a possible slab


class InspectionError(RuntimeError):
    """The shipped MP4 would not look right to a viewer."""


def say(level: str, message: str) -> None:
    """Use the project's coloured console when it is available."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from say import say as painted  # noqa: PLC0415 - optional import
    except Exception:  # noqa: BLE001 - colour is a nicety, not a requirement
        print(message, flush=True)
        return
    try:
        painted(level, message)
    except Exception:  # noqa: BLE001
        print(message, flush=True)


# --------------------------------------------------------------------------- #
# Probing the container
# --------------------------------------------------------------------------- #
def probe(path: Path) -> dict:
    output = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        text=True,
    )
    return json.loads(output)


def rotation_of(video: dict) -> float:
    for side in video.get("side_data_list") or []:
        try:
            return float(side.get("rotation") or 0.0)
        except (TypeError, ValueError):
            return 0.0
    try:
        return float((video.get("tags") or {}).get("rotate") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def ratio(text: str | None, fallback: float = 1.0) -> float:
    """Parse ffprobe's "num:den" ratios, including the "0:1" unknown case."""
    try:
        numerator, denominator = str(text).split(":", 1)
        numerator, denominator = int(numerator), int(denominator)
    except (TypeError, ValueError):
        return fallback
    if numerator == 0 or denominator == 0:
        return fallback
    return numerator / denominator


def container_problems(info: dict) -> tuple[list[str], dict]:
    streams = info.get("streams") or []
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    if video is None:
        raise InspectionError("the MP4 has no video stream at all")
    if audio is None:
        raise InspectionError("the MP4 has no audio stream, so the narration is missing")

    width, height = int(video.get("width") or 0), int(video.get("height") or 0)
    sample_aspect = ratio(video.get("sample_aspect_ratio"), 1.0)
    display_aspect = ratio(video.get("display_aspect_ratio"), width / height if height else 0.0)
    rotation = rotation_of(video)
    try:
        numerator, denominator = str(video.get("avg_frame_rate") or "0/1").split("/", 1)
        fps = float(numerator) / float(denominator)
    except (ValueError, ZeroDivisionError):
        fps = 0.0
    duration = float(video.get("duration") or (info.get("format") or {}).get("duration") or 0.0)

    facts = {
        "width": width,
        "height": height,
        "sample_aspect": sample_aspect,
        "display_aspect": display_aspect,
        "rotation": rotation,
        "fps": fps,
        "duration": duration,
        "video_codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name"),
        "pix_fmt": video.get("pix_fmt"),
        "size_mb": round(int((info.get("format") or {}).get("size") or 0) / (1024 * 1024), 1),
    }

    problems: list[str] = []

    def report(label: str, ok: bool, message: str) -> None:
        if not ok:
            problems.append(message)
        print(f"  {'ok  ' if ok else 'FAIL'} {label}", flush=True)

    report(f"frame size {width}x{height}",
           (width, height) == (WIDTH, HEIGHT),
           f"expected {WIDTH}x{HEIGHT}, got {width}x{height}")
    report("square pixels (sample aspect ratio 1:1)",
           math.isclose(sample_aspect, 1.0, rel_tol=0, abs_tol=1e-6),
           f"pixels are {sample_aspect:.4f} wide for their height, so players will stretch the picture")
    report("no rotation flag",
           math.isclose(rotation % 360, 0.0, abs_tol=1e-6),
           f"the video carries a {rotation:g} degree rotation flag, which stretches it on playback")
    report("9:16 display shape",
           math.isclose(display_aspect, EXPECTED_ASPECT, rel_tol=0, abs_tol=0.005),
           f"the player will show {display_aspect:.4f}:1 instead of 0.5625:1")
    report("H.264 video and AAC audio",
           facts["video_codec"] == "h264" and facts["audio_codec"] == "aac",
           f"got {facts['video_codec']}/{facts['audio_codec']}")
    report("about 30 frames per second",
           abs(fps - 30.0) < 0.02,
           f"got {fps:.2f} fps")
    report(f"{duration:.1f}s long", duration > 1.0, "the video is empty")
    return problems, facts


# --------------------------------------------------------------------------- #
# Looking at the pixels
# --------------------------------------------------------------------------- #
def frame_times(duration: float, count: int) -> list[float]:
    """Sample across the short, skipping the first and last frame."""
    if count <= 0:
        return []
    usable = max(duration - 1.0, 0.1)
    return [round(0.05 * usable + (index / max(count - 1, 1)) * 0.9 * usable, 2)
            for index in range(count)]


def decode_frame(video: Path, at: float) -> bytes:
    """Decode one frame as 180x320 rgb24 bytes."""
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{at:.3f}", "-i", str(video),
         "-frames:v", "1", "-vf", f"scale={PROBE_WIDTH}:{PROBE_HEIGHT}",
         "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"],
        capture_output=True, check=False,
    )
    expected = PROBE_WIDTH * PROBE_HEIGHT * 3
    if result.returncode != 0 or len(result.stdout) != expected:
        raise InspectionError(
            f"could not decode the frame at {at:.2f}s: ffmpeg exited {result.returncode} "
            f"with {len(result.stdout)}/{expected} bytes: {result.stderr.decode('utf-8', 'replace')[-300:]}"
        )
    return result.stdout


def find_black_slabs(raw: bytes) -> list[dict]:
    """Connected clusters of dark grid cells: the black-block artefact.

    A black Part in the world, or a material whose colour never arrived, shows up
    as a *rectangle* of near-black pixels with hard edges. Averaging the frame
    hides it, so the cells are clustered and the biggest square-ish cluster is
    reported with its position and size.
    """
    cell_w = PROBE_WIDTH // GRID_COLUMNS
    cell_h = PROBE_HEIGHT // GRID_ROWS
    luminosity = [[0.0] * GRID_COLUMNS for _ in range(GRID_ROWS)]
    for row in range(GRID_ROWS):
        for column in range(GRID_COLUMNS):
            total = 0.0
            for y in range(row * cell_h, (row + 1) * cell_h):
                base = (y * PROBE_WIDTH + column * cell_w) * 3
                for x in range(cell_w):
                    index = base + x * 3
                    total += 0.2126 * raw[index] + 0.7152 * raw[index + 1] + 0.0722 * raw[index + 2]
            luminosity[row][column] = total / (cell_w * cell_h)

    dark = {(row, column)
            for row in range(GRID_ROWS)
            for column in range(GRID_COLUMNS)
            if luminosity[row][column] < DARK_CELL}

    slabs: list[dict] = []
    seen: set[tuple[int, int]] = set()
    for start in sorted(dark):
        if start in seen:
            continue
        stack, cluster = [start], []
        seen.add(start)
        while stack:
            row, column = stack.pop()
            cluster.append((row, column))
            for d_row, d_column in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                neighbour = (row + d_row, column + d_column)
                if neighbour in dark and neighbour not in seen:
                    seen.add(neighbour)
                    stack.append(neighbour)
        if len(cluster) < 6:
            continue
        rows = [cell[0] for cell in cluster]
        columns = [cell[1] for cell in cluster]
        box_rows = max(rows) - min(rows) + 1
        box_columns = max(columns) - min(columns) + 1
        squareness = len(cluster) / (box_rows * box_columns)
        fill = len(cluster) / (GRID_ROWS * GRID_COLUMNS)
        slabs.append({
            "cells": len(cluster),
            "fill": round(fill, 4),
            "squareness": round(squareness, 3),
            "x": round(min(columns) / GRID_COLUMNS, 3),
            "y": round(min(rows) / GRID_ROWS, 3),
            "width": round(box_columns / GRID_COLUMNS, 3),
            "height": round(box_rows / GRID_ROWS, 3),
        })
    slabs.sort(key=lambda slab: slab["fill"], reverse=True)
    return slabs


def measure_frame(raw: bytes) -> dict:
    pixels = PROBE_WIDTH * PROBE_HEIGHT
    total = black = white = colourful = 0.0
    luminance_values = []
    for index in range(0, pixels * 3, 3):
        red, green, blue = raw[index], raw[index + 1], raw[index + 2]
        luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
        total += luminance
        luminance_values.append(luminance)
        if luminance < BLACK_LEVEL:
            black += 1
        if luminance > WHITE_LEVEL:
            white += 1
        high = max(red, green, blue)
        low = min(red, green, blue)
        if high > 24 and (high - low) / high > COLOUR_SATURATION:
            colourful += 1
    mean = total / pixels
    variance = sum((value - mean) ** 2 for value in luminance_values) / pixels
    return {
        "mean_luminance": round(mean, 1),
        "contrast": round(math.sqrt(variance), 1),
        "black_fraction": round(black / pixels, 4),
        "white_fraction": round(white / pixels, 4),
        "colour_fraction": round(colourful / pixels, 4),
    }


def frame_problems(name: str, stats: dict, slabs: list[dict]) -> list[str]:
    problems = []
    if stats["black_fraction"] > 0.55:
        problems.append(f"{name} is {stats['black_fraction'] * 100:.0f}% pure black, so the world is not lit")
    if stats["white_fraction"] > 0.55:
        problems.append(f"{name} is {stats['white_fraction'] * 100:.0f}% blown-out white, so the lighting is over-exposed")
    if stats["colour_fraction"] < 0.25:
        problems.append(f"{name} is nearly colourless ({stats['colour_fraction'] * 100:.1f}% of its pixels carry a hue)")
    if stats["contrast"] < 6:
        problems.append(f"{name} is almost flat (luminance spread {stats['contrast']}), so the world failed to draw")
    for slab in slabs:
        # Big, dark and rectangular: a slab, not a shadow.
        if slab["fill"] >= 0.05 and slab["squareness"] >= 0.8:
            problems.append(
                f"{name} contains a black block covering {slab['fill'] * 100:.1f}% of the frame "
                f"at x={slab['x']:.2f} y={slab['y']:.2f} "
                f"({slab['width'] * 100:.0f}% x {slab['height'] * 100:.0f}%), which is a Part that did not get its colour"
            )
    return problems


# --------------------------------------------------------------------------- #
# The report
# --------------------------------------------------------------------------- #
def write_report(path: Path, facts: dict, rows: list[dict], problems: list[str]) -> None:
    lines = [
        "# MP4 inspection",
        "",
        f"- Size: **{facts['width']}x{facts['height']}** ({facts['size_mb']} MB, "
        f"{facts['duration']:.1f}s at {facts['fps']:.2f} fps)",
        f"- Pixels: sample aspect ratio **{facts['sample_aspect']:.4f}**, "
        f"display aspect ratio **{facts['display_aspect']:.4f}** (9:16 is 0.5625)",
        f"- Rotation flag: **{facts['rotation']:g} degrees**",
        f"- Streams: {facts['video_codec']} video / {facts['audio_codec']} audio ({facts['pix_fmt']})",
        "",
        "| # | time | mean luminance | contrast | pure black | blown out | coloured | biggest dark block |",
        "|---|------|----------------|----------|------------|-----------|----------|--------------------|",
    ]
    for row in rows:
        stats, slab = row["stats"], row["biggest_slab"]
        slab_text = (f"{slab['fill'] * 100:.1f}% at x={slab['x']:.2f}, y={slab['y']:.2f}"
                     if slab else "-")
        lines.append(
            f"| {row['index']} | {row['time']:.1f}s | {stats['mean_luminance']:.0f}/255 | "
            f"{stats['contrast']:.0f} | {stats['black_fraction'] * 100:.1f}% | "
            f"{stats['white_fraction'] * 100:.1f}% | {stats['colour_fraction'] * 100:.1f}% | {slab_text} |"
        )
    lines.append("")
    if problems:
        lines.append("## Problems")
        lines.append("")
        lines.extend(f"- {problem}" for problem in problems)
    else:
        lines.append("## Verdict")
        lines.append("")
        lines.append("Every sampled frame is lit, colourful, varied, and free of black slabs and stretch flags.")
    lines.append("")
    lines.append("## Frames")
    lines.append("")
    for row in rows:
        lines.append(f"### {row['time']:.1f}s")
        lines.append("")
        lines.append(f"![frame at {row['time']:.1f}s]({row['image']})")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def inspect(video: Path, frames_dir: Path | None, report: Path | None, samples: int) -> int:
    if not video.is_file() or video.stat().st_size == 0:
        raise InspectionError(f"{video} does not exist or is empty")

    say("plan", f"Inspecting the shipped MP4: {video.name}")
    problems, facts = container_problems(probe(video))

    if frames_dir is not None:
        frames_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    times = frame_times(facts["duration"], samples)
    for index, at in enumerate(times, 1):
        raw = decode_frame(video, at)
        stats = measure_frame(raw)
        slabs = find_black_slabs(raw)
        biggest = slabs[0] if slabs else None
        image = ""
        if frames_dir is not None:
            image = f"mp4_{index:02d}_t{at:05.1f}s.png".replace(" ", "")
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{at:.3f}",
                 "-i", str(video), "-frames:v", "1", "-vf", "scale=540:-2", str(frames_dir / image)],
                check=False,
            )
        row = {"index": index, "time": at, "stats": stats, "biggest_slab": biggest, "image": image}
        rows.append(row)
        problems.extend(frame_problems(f"the frame at {at:.1f}s", stats, slabs))
        block = (f", biggest dark block {biggest['fill'] * 100:.1f}% "
                 f"(squareness {biggest['squareness']:.2f}) at x={biggest['x']:.2f} y={biggest['y']:.2f}"
                 if biggest else ", no dark block")
        say("plan",
            f"  t={at:5.1f}s  luminance {stats['mean_luminance']:5.1f}/255  "
            f"contrast {stats['contrast']:5.1f}  black {stats['black_fraction'] * 100:5.1f}%  "
            f"white {stats['white_fraction'] * 100:5.1f}%  colour {stats['colour_fraction'] * 100:5.1f}%"
            + block)

    if report is not None:
        write_report(report, facts, rows, problems)

    if problems:
        say("warning", f"The shipped MP4 has {len(problems)} problem(s):")
        for problem in problems:
            say("warning", f"  - {problem}")
        print(f"::error title=MP4 inspection failed::{problems[0][:900]}", flush=True)
        return 1
    say("success", f"MP4 inspection passed: {facts['width']}x{facts['height']} square pixels, "
                   f"{len(rows)} sampled frames all lit, colourful and free of black blocks.")
    print(f"::notice title=MP4 inspection::{facts['width']}x{facts['height']}, SAR "
          f"{facts['sample_aspect']:.4f}, {len(rows)} frames sampled, worst black block "
          f"{max((row['biggest_slab']['fill'] for row in rows if row['biggest_slab']), default=0.0) * 100:.1f}%.",
          flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--frames-dir", type=Path, default=None,
                        help="where to write the sampled frames as PNG")
    parser.add_argument("--report", type=Path, default=None,
                        help="where to write the markdown report")
    parser.add_argument("--samples", type=int, default=8, help="how many frames to look at")
    args = parser.parse_args()
    try:
        return inspect(args.video, args.frames_dir, args.report, args.samples)
    except InspectionError as exc:
        say("error", f"MP4 inspection could not finish: {exc}")
        print(f"::error title=MP4 inspection failed::{str(exc)[:900]}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
