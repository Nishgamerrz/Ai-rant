#!/usr/bin/env python3
"""Technical quality gate: approve only a complete, decodable, captioned Shorts MP4."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

WORD_RE = re.compile(r"\b[\w’'-]+\b")
META_RE = re.compile(r"\b(?:A\.I\.|AI|servers?|Roblox|avatars?|game mechanics?|generated)\b", re.I)
SRT_RE = re.compile(
    r"(?m)^\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})\s+-->\s+"
    r"(\d{2}:\d{2}:\d{2}[,.]\d{3})(?:[^\n]*)$"
)


def fail(message: str) -> None:
    text = f"SHORT NOT APPROVED: {message}"
    if "GITHUB_STEP_SUMMARY" in os.environ:
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as summary:
            summary.write(f"## Short quality gate: NOT APPROVED\\n\\n{message}\\n\\nNo MP4 artifact was uploaded.\\n")
    print(text, file=sys.stderr)
    raise SystemExit(1)


def seconds(timestamp: str) -> float:
    hours, minutes, rest = timestamp.replace(",", ".").split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(rest)


def sample_frame(path: Path, at: float, width: int, height: int) -> None:
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{at:.3f}", "-i", str(path),
        "-map", "0:v:0", "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
    ]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    expected_bytes = width * height * 3
    if result.returncode or len(result.stdout) != expected_bytes:
        fail(f"could not decode a visual sample at {at:.1f}s")
    samples = result.stdout[::4096]
    mean = sum(samples) / max(1, len(samples))
    visible_fraction = sum(channel > 8 for channel in samples) / max(1, len(samples))
    if mean < 1.0 or visible_fraction < 0.01:
        fail(f"sample at {at:.1f}s is effectively blank/black (mean={mean:.2f})")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--silent-video", required=True, type=Path)
    parser.add_argument("--narration", required=True, type=Path)
    parser.add_argument("--captions", required=True, type=Path)
    parser.add_argument("--duration", required=True, type=int, choices=(30, 45, 60))
    args = parser.parse_args()

    for label, path in (("final MP4", args.video), ("silent render", args.silent_video),
                        ("narration", args.narration), ("SRT captions", args.captions)):
        if not path.is_file() or path.stat().st_size == 0:
            fail(f"missing or empty {label}: {path}")
    if args.video.stat().st_size < 100_000:
        fail("final MP4 is unexpectedly small")

    narration = args.narration.read_text(encoding="utf-8").strip()
    word_count = len(WORD_RE.findall(narration))
    max_words = min(100, int(args.duration * 5 / 3))
    if not word_count or word_count > max_words:
        fail(f"narration has {word_count} words; maximum for {args.duration}s is {max_words}")
    if META_RE.search(narration):
        fail("narration contains forbidden AI/game meta-talk")

    captions = args.captions.read_text(encoding="utf-8-sig")
    cues = list(SRT_RE.finditer(captions))
    if not cues:
        fail("no valid timed caption cues found")
    if not re.search(r"(?m)^\s*\d+\s*$", captions):
        fail("SRT cue numbering is missing")
    for cue in cues:
        start, end = seconds(cue.group(1)), seconds(cue.group(2))
        if end <= start or end > args.duration + 1:
            fail(f"invalid caption timing {cue.group(1)} --> {cue.group(2)}")
    caption_blocks = re.split(r"\n\s*\n", captions.strip())
    caption_text = []
    for block in caption_blocks:
        lines = block.splitlines()
        if len(lines) >= 3 and "-->" in lines[1]:
            caption_text.extend(lines[2:])
    if not re.search(r"[A-Za-z0-9]", " ".join(caption_text)):
        fail("caption file contains no readable spoken text")

    probe = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(args.video)
    ], text=True))
    video = next((stream for stream in probe["streams"] if stream.get("codec_type") == "video"), None)
    audio = next((stream for stream in probe["streams"] if stream.get("codec_type") == "audio"), None)
    if not video or not audio:
        fail("MP4 must contain both video and audio streams")
    if (video.get("width"), video.get("height")) != (1440, 2560):
        fail(f"expected vertical 1440x2560 video, got {video.get('width')}x{video.get('height')}")
    if video.get("codec_name") != "h264" or audio.get("codec_name") != "aac":
        fail(f"expected H.264/AAC streams, got {video.get('codec_name')}/{audio.get('codec_name')}")
    try:
        numerator, denominator = video["avg_frame_rate"].split("/", 1)
        fps = float(numerator) / float(denominator)
    except (KeyError, ValueError, ZeroDivisionError, TypeError):
        fps = 0
    if abs(float(fps) - 30.0) > 0.02:
        fail(f"expected 30 fps, got {video.get('avg_frame_rate')}")
    video_seconds = float(video.get("duration") or probe["format"].get("duration", 0))
    if abs(video_seconds - args.duration) > 1.5:
        fail(f"expected about {args.duration}s, got {video_seconds:.2f}s")
    audio_seconds = float(audio.get("duration") or video_seconds)
    if audio_seconds < video_seconds - 1.0:
        fail("audio ends more than one second before the picture")

    decode = subprocess.run([
        "ffmpeg", "-hide_banner", "-v", "error", "-i", str(args.video), "-f", "null", "-"
    ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, check=False)
    if decode.returncode:
        fail(f"full MP4 decode failed: {decode.stderr[-1200:]}")

    for fraction in (0.1, 0.5, 0.9):
        sample_frame(args.video, video_seconds * fraction, 1440, 2560)

    print(
        f"SHORT APPROVED: {args.video.name}; 1440x2560, {float(fps):g} fps, "
        f"{video_seconds:.2f}s, H.264/AAC, {word_count} narration words, "
        f"{len(cues)} caption cues, full decode and 3 visual samples passed."
    )
    if "GITHUB_STEP_SUMMARY" in os.environ:
        summary = Path(os.environ["GITHUB_STEP_SUMMARY"])
        summary.write_text(
            f"## Short quality gate: APPROVED\n\n"
            f"- Video: `{args.video.name}` (1440×2560, 30 fps, {video_seconds:.2f}s)\n"
            f"- Audio: H.264 video with AAC audio\n"
            f"- Narration: {word_count}/{max_words} words; {len(cues)} timed caption cues\n"
            f"- Full decode and 3 nonblank visual samples passed\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
