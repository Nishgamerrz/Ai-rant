#!/usr/bin/env python3
"""Technical quality gate: approve only a complete, decodable, narrated Shorts MP4."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from durations import DURATIONS  # noqa: E402

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
            summary.write(f"## Short quality gate: NOT APPROVED\n\n{message}\n\nNo MP4 artifact was uploaded.\n")
    print(text, file=sys.stderr)
    raise SystemExit(1)


def seconds(timestamp: str) -> float:
    hours, minutes, rest = timestamp.replace(",", ".").split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(rest)


def avatar_asset_type(profile: dict) -> str | None:
    """Return the available authentic Roblox source: full mesh or public avatar image."""
    model = Path(profile.get("model_obj", ""))
    material = Path(profile.get("model_mtl", ""))
    if (profile.get("model_ready") and model.is_file() and model.stat().st_size > 0
            and material.is_file() and material.stat().st_size > 0):
        return "mesh"
    thumbnail = Path(profile.get("thumbnail", ""))
    if profile.get("thumbnail_ready") and thumbnail.is_file() and thumbnail.stat().st_size > 0:
        return "thumbnail"
    return None


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
    parser.add_argument("--characters", type=Path)
    parser.add_argument("--profiles", type=Path)
    parser.add_argument("--map-plan", type=Path)
    parser.add_argument("--duration", required=True, type=int, choices=DURATIONS)
    args = parser.parse_args()

    for label, path in (("final MP4", args.video), ("silent render", args.silent_video),
                        ("narration", args.narration), ("SRT captions", args.captions)):
        if not path.is_file() or path.stat().st_size == 0:
            fail(f"missing or empty {label}: {path}")
    if args.video.stat().st_size < 100_000:
        fail("final MP4 is unexpectedly small")

    cast_count = 0
    avatar_model_count = 0
    avatar_thumbnail_count = 0
    if args.characters:
        usernames = json.loads(args.characters.read_text(encoding="utf-8"))
        if not isinstance(usernames, list) or any(not isinstance(name, str) for name in usernames):
            fail("cast file is not a JSON array of usernames")
        cast_count = len(usernames)
        if cast_count > 6:
            fail(f"cast has {cast_count} names; the renderer supports at most 6")
        if usernames:
            if not args.profiles or not args.profiles.is_file():
                fail("public Roblox avatar profiles are missing")
            profiles = json.loads(args.profiles.read_text(encoding="utf-8"))
            profiles_by_name = {item.get("username", "").casefold(): item for item in profiles if isinstance(item, dict)}
            for name in usernames:
                profile = profiles_by_name.get(name.casefold(), {})
                source = avatar_asset_type(profile)
                if source is None:
                    fail(f"authentic Roblox avatar mesh and thumbnail are both missing for {name}")
                if source == "mesh":
                    avatar_model_count += 1
                else:
                    avatar_thumbnail_count += 1
        if args.map_plan:
            map_plan = json.loads(args.map_plan.read_text(encoding="utf-8"))
            placed = {item.get("username", "").casefold() for item in map_plan.get("character_placements", [])
                      if isinstance(item, dict)}
            missing = [name for name in usernames if name.casefold() not in placed]
            if missing:
                fail("map plan does not place all named characters: " + ", ".join(missing))
            # Face animation gate: the AI must schedule expression switches and
            # at least two close-ups of a face, like a Roblox story short.
            expressions = map_plan.get("face_expressions")
            if not isinstance(expressions, list) or len(expressions) < 3:
                fail("map plan is missing the AI face-expression timeline (need at least 3 beats)")
            previous = -1.0
            for entry in expressions:
                if not isinstance(entry, dict):
                    fail("face-expression timeline contains a non-object beat")
                timestamp = entry.get("time")
                if not isinstance(timestamp, (int, float)) or not 0 <= timestamp <= args.duration:
                    fail(f"face-expression beat has an invalid time: {entry}")
                if timestamp < previous:
                    fail("face-expression beats are not in time order")
                previous = float(timestamp)
            shots = [shot for shot in map_plan.get("camera_shots", []) if isinstance(shot, dict)]
            face_shots = [shot for shot in shots
                          if str(shot.get("framing", "")).lower() in {"face", "close", "closeup", "close-up"}]
            if len(face_shots) < 2:
                fail(f"map plan has {len(face_shots)} face close-up shot(s); at least 2 are required")
            if any(not str(shot.get("focus_username", "")).strip() for shot in face_shots):
                fail("every face close-up must follow a named character")
            print(f"Face animation plan verified: {len(expressions)} AI expression beats, "
                  f"{len(face_shots)} face close-up shot(s).")

    narration = args.narration.read_text(encoding="utf-8").strip()
    word_count = len(WORD_RE.findall(narration))
    min_words = max(1, int(args.duration * 1.4))
    max_words = int(args.duration * 1.8)
    if not min_words <= word_count <= max_words:
        fail(f"narration has {word_count} words; target for {args.duration}s is {min_words}–{max_words}")
    if META_RE.search(narration):
        fail("narration contains forbidden AI/game meta-talk")
    if args.characters and args.characters.exists():
        cast = json.loads(args.characters.read_text(encoding="utf-8"))
        spoken = {word.casefold() for word in WORD_RE.findall(narration)}
        leaked = sorted({name for name in cast if isinstance(name, str) and name.casefold() in spoken})
        if leaked:
            fail("narration reads out selected usernames: " + ", ".join(leaked))

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

    face_note = ""
    if args.map_plan and args.map_plan.is_file():
        planned = json.loads(args.map_plan.read_text(encoding="utf-8"))
        face_note = (f"{len(planned.get('face_expressions', []))} face-expression beats, "
                     f"{sum(1 for shot in planned.get('camera_shots', []) if str(shot.get('framing', '')).lower() == 'face')} face close-ups, ")
    print(
        f"SHORT APPROVED: {args.video.name}; 1440x2560, {float(fps):g} fps, "
        f"{video_seconds:.2f}s, H.264/AAC, {word_count} narration words, "
        f"{cast_count} named cast member(s), {avatar_model_count} avatar mesh(es) and {avatar_thumbnail_count} Roblox avatar thumbnail(s) verified, "
        f"{len(cues)} caption cues, {face_note}"
        "full decode and 3 visual samples passed."
    )
    if "GITHUB_STEP_SUMMARY" in os.environ:
        summary = Path(os.environ["GITHUB_STEP_SUMMARY"])
        with summary.open("a", encoding="utf-8") as report:
            report.write(
                f"## Short quality gate: APPROVED\n\n"
                f"- Video: `{args.video.name}` (1440×2560, 30 fps, {video_seconds:.2f}s)\n"
                f"- Codecs: H.264 video and AAC audio\n"
                f"- Narration: {word_count}/{max_words} words; {len(cues)} timed caption cues\n"
                f"- Named cast members: {cast_count}; authentic avatar meshes: {avatar_model_count}; account thumbnails: {avatar_thumbnail_count}\n"
                f"- Full decode and 3 nonblank visual samples passed\n"
            )


if __name__ == "__main__":
    main()
