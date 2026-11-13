"""Focused planning and quality tools for Roblox short production.

These functions stay deterministic and local: the agent decides when to call
one, while the tool measures a script, lighting cues, map, captions, or MP4.
"""
from __future__ import annotations

import math
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
_WORD = re.compile(r"[\w]+(?:['’_-][\w]+)*", re.UNICODE)
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_SRT_TIME = re.compile(
    r"^(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*"
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})(?:\s+.*)?$"
)


def _duration(value) -> float:
    try:
        seconds = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("duration must be a number of seconds") from exc
    if not math.isfinite(seconds) or not 1 <= seconds <= 600:
        raise ValueError("duration must be between 1 and 600 seconds")
    return seconds


def analyze_short_script(text: str, duration=150) -> dict:
    """Report hook/line pacing and estimated narration length without rewriting."""
    source = str(text or "").strip()
    if not source:
        return {"ok": False, "error": "provide narration text or a workspace file path"}
    target = _duration(duration)
    words = _WORD.findall(source)
    sentences = [part.strip() for part in _SENTENCE.split(source) if part.strip()]
    sentence_rows = [{"index": index + 1, "words": len(_WORD.findall(sentence)),
                      "text": sentence[:240]}
                     for index, sentence in enumerate(sentences[:60])]
    counts = [row["words"] for row in sentence_rows]
    words_per_minute = 150.0
    estimated = len(words) * 60.0 / words_per_minute
    first_sentence = sentences[0] if sentences else source
    hook = bool(re.search(r"^(?:in a world where|when|every|the day|the first time|imagine)\b",
                          first_sentence, re.IGNORECASE))
    warnings = []
    if estimated < target * 0.75:
        warnings.append("narration may finish well before the video target")
    elif estimated > target * 1.05:
        warnings.append("narration may exceed the video target")
    long_lines = [row for row in sentence_rows if row["words"] > 14]
    if long_lines:
        warnings.append("split or shorten long spoken lines to preserve reference-style pauses")
    beats = []
    if sentences:
        beats.append({"role": "hook", "sentence": 1, "text": sentences[0][:240]})
        if len(sentences) > 2:
            middle = max(1, (len(sentences) - 1) // 2)
            beats.append({"role": "turn", "sentence": middle + 1, "text": sentences[middle][:240]})
        if len(sentences) > 1:
            beats.append({"role": "payoff", "sentence": len(sentences), "text": sentences[-1][:240]})
    return {
        "ok": True,
        "word_count": len(words),
        "sentence_count": len(sentences),
        "target_seconds": round(target, 2),
        "estimated_narration_seconds_at_150_wpm": round(estimated, 2),
        "target_fill_percent": round(estimated / target * 100, 1),
        "hook_opens_with_story_setup": hook,
        "average_sentence_words": round(sum(counts) / len(counts), 2) if counts else 0,
        "long_sentences_over_14_words": long_lines,
        "story_beats": beats,
        "warnings": warnings,
        "note": "Pacing estimates are heuristic; listen to the synthesized voice before publishing.",
    }


def plan_short_lighting(text: str, duration=150) -> dict:
    """Suggest an automatic global hour and ordered scene-hour candidates."""
    from time_of_day import CLOCK_TIMES, resolve_time_of_day, scene_time_sequence

    source = str(text or "").strip()
    if not source:
        return {"ok": False, "error": "provide a story, narration, or workspace file path"}
    target = _duration(duration)
    global_hour = resolve_time_of_day("auto", source)
    cues = scene_time_sequence(source)
    if cues and cues[0] != global_hour:
        cues.insert(0, global_hour)
    # This evenly-spaced sequence is a fallback only; the camera AI should align
    # each actual change to its story beat, not use these estimate times blindly.
    suggestions = []
    if len(cues) > 1:
        slice_seconds = target / len(cues)
        for index, hour in enumerate(cues[1:], 1):
            suggestions.append({
                "time_of_day": hour,
                "suggested_time_seconds": round(slice_seconds * index, 2),
            })
    return {
        "ok": True,
        "global_hour": global_hour,
        "roblox_clock_time": CLOCK_TIMES[global_hour],
        "scene_hour_cues": cues,
        "suggested_overrides": suggestions,
        "mode": "per_scene" if suggestions else "global",
        "note": "Use story beats for final camera-shot override times; unmarked shots inherit the previous hour.",
    }


def audit_roblox_map(plan: dict, duration=150, cast=()) -> dict:
    """Run the production map normalizer and summarize camera/lighting coverage."""
    from build_story_map import validate
    from time_of_day import SCENE_TIME_CHOICES, canonical_time_of_day, resolve_time_of_day

    target = _duration(duration)
    if not isinstance(plan, dict):
        return {"ok": False, "error": "map JSON must contain an object"}
    usernames = [str(name).strip() for name in (cast or []) if str(name).strip()]
    if not usernames:
        usernames = [str(row.get("username")) for row in plan.get("character_placements", [])
                     if isinstance(row, dict) and str(row.get("username") or "").strip()]
    raw_shots = plan.get("camera_shots") if isinstance(plan.get("camera_shots"), list) else []
    invalid_overrides = sum(
        1 for shot in raw_shots
        if isinstance(shot, dict) and "time_of_day" in shot
        and canonical_time_of_day(shot.get("time_of_day")) is None
    )
    raw_hour = canonical_time_of_day(plan.get("time_of_day"))
    warnings = []
    if plan.get("time_of_day") and not raw_hour:
        warnings.append("invalid global hour; inferred a safe fallback from the theme")
    if invalid_overrides:
        warnings.append(f"{invalid_overrides} invalid per-shot hour override(s) will be ignored")
    if not 4 <= len(raw_shots) <= 48:
        warnings.append("camera shot count is outside 4–48; the validator will use its safe default path")
    else:
        previous = -1.0
        invalid_path = False
        invalid_transitions = 0
        for shot in raw_shots:
            if not isinstance(shot, dict):
                invalid_path = True
                break
            shot_time = shot.get("time")
            if (isinstance(shot_time, bool) or not isinstance(shot_time, (int, float))
                    or not 0 <= shot_time <= target or shot_time <= previous):
                invalid_path = True
                break
            for vector_name in ("position", "target"):
                vector = shot.get(vector_name)
                if (not isinstance(vector, list) or len(vector) != 3
                        or any(isinstance(value, bool) or not isinstance(value, (int, float))
                               or not -300 <= value <= 300 for value in vector)):
                    invalid_path = True
                    break
            if invalid_path:
                break
            transition = shot.get("transition", "smooth")
            if not isinstance(transition, str) or transition not in {"smooth", "snap"}:
                invalid_transitions += 1
            previous = shot_time
        if invalid_path:
            warnings.append("camera timestamps or vectors are invalid; the validator will use its safe default path")
        if invalid_transitions:
            warnings.append(f"{invalid_transitions} unknown camera transition(s) will be normalized to smooth")
    normalized = validate(plan, target, usernames, min_props=8)
    hour = raw_hour or resolve_time_of_day("auto", str(plan.get("theme") or ""))
    shots = normalized.get("camera_shots") or []
    shot_times = [float(shot["time"]) for shot in shots if isinstance(shot, dict)]
    gaps = [right - left for left, right in zip(shot_times, shot_times[1:])]
    face_shots = sum(1 for shot in shots if shot.get("framing") == "face")
    if usernames and face_shots < 3:
        warnings.append("fewer than three readable face-framing shots")
    if gaps and max(gaps) > 6.0:
        warnings.append(f"camera beat gap reaches {max(gaps):.1f}s; consider adding a cutaway")
    overrides = [{"time": shot.get("time"), "hour": shot.get("time_of_day")}
                 for shot in shots if shot.get("time_of_day") in SCENE_TIME_CHOICES]
    shapes = Counter(str(prop.get("shape") or "Block") for prop in normalized.get("props", []))
    return {
        "ok": True,
        "world_name": normalized["name"],
        "world_parts": len(normalized["props"]),
        "distinct_shapes": dict(shapes),
        "camera_shots": len(shots),
        "longest_camera_gap_seconds": round(max(gaps), 2) if gaps else 0,
        "snap_cuts": sum(1 for shot in shots if shot.get("transition") == "snap"),
        "face_closeups": face_shots,
        "global_hour": hour,
        "scene_hour_overrides": overrides,
        "warnings": warnings,
    }


def _timestamp(match, offset: int) -> float:
    hours, minutes, seconds, milliseconds = (int(match.group(offset + step)) for step in range(4))
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000


def audit_short_captions(text: str, duration=0, max_words=1) -> dict:
    """Check subtitle order, overlaps, duration bounds and one-word readability."""
    source = str(text or "").strip().lstrip("\ufeff")
    if not source:
        return {"ok": False, "error": "caption file is empty"}
    target = _duration(duration) if float(duration or 0) > 0 else None
    try:
        word_limit = max(1, min(8, int(max_words)))
    except (TypeError, ValueError):
        word_limit = 1
    cues = []
    errors, warnings = [], []
    blocks = re.split(r"\n\s*\n", source)
    for block_index, block in enumerate(blocks, 1):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        time_index = next((i for i, line in enumerate(lines) if _SRT_TIME.match(line)), None)
        if time_index is None:
            continue
        match = _SRT_TIME.match(lines[time_index])
        start, finish = _timestamp(match, 1), _timestamp(match, 5)
        caption = re.sub(r"<[^>]*>", "", " ".join(lines[time_index + 1:])).strip()
        if caption:
            cues.append({"block": block_index, "start": start, "finish": finish,
                         "text": caption, "words": len(_WORD.findall(caption))})
    if not cues:
        return {"ok": False, "error": "no valid timed SRT cues were found"}
    previous_start = -1.0
    previous_finish = -1.0
    gaps = []
    multiword = []
    for cue in cues:
        if cue["start"] < previous_start:
            errors.append(f"cue {cue['block']} starts out of order")
        if cue["finish"] <= cue["start"]:
            errors.append(f"cue {cue['block']} has a non-positive duration")
        if cue["start"] < previous_finish - 0.02:
            errors.append(f"cue {cue['block']} overlaps the preceding caption")
        gap = cue["start"] - previous_finish if previous_finish >= 0 else 0.0
        if gap > 0:
            gaps.append(gap)
        if cue["words"] > word_limit:
            multiword.append({"cue": cue["block"], "words": cue["words"], "text": cue["text"][:120]})
        if cue["finish"] - cue["start"] > 1.8:
            warnings.append(f"cue {cue['block']} lasts over 1.8 seconds")
        if target is not None and cue["finish"] > target + 0.05:
            errors.append(f"cue {cue['block']} ends after the {target:g}s video duration")
        previous_start, previous_finish = cue["start"], max(previous_finish, cue["finish"])
    if multiword:
        warnings.append(f"{len(multiword)} cue(s) exceed the {word_limit}-word reference caption limit")
    return {
        "ok": not errors,
        "cue_count": len(cues),
        "caption_word_count": sum(cue["words"] for cue in cues),
        "single_word_cues": sum(1 for cue in cues if cue["words"] == 1),
        "multiword_cues": multiword,
        "largest_gap_seconds": round(max(gaps), 3) if gaps else 0,
        "errors": errors,
        "warnings": warnings,
    }


def inspect_roblox_short(video: Path, report: Path | None = None,
                         frames_dir: Path | None = None, samples=8, timeout=180) -> dict:
    """Run the shipped-file MP4 inspection, including sampled pixel quality."""
    video = Path(video)
    if not video.is_file() or video.stat().st_size == 0:
        return {"ok": False, "error": f"video not found or empty: {video.name}"}
    try:
        sample_count = max(3, min(12, int(samples)))
    except (TypeError, ValueError):
        sample_count = 8
    command = [sys.executable, str(TOOLS / "inspect_short.py"), "--video", str(video),
               "--samples", str(sample_count)]
    if report:
        command.extend(("--report", str(report)))
    if frames_dir:
        command.extend(("--frames-dir", str(frames_dir)))
    try:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                                timeout=max(5, min(300, int(timeout))),
                                env={**__import__("os").environ, "AI_COLOR": "0"})
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "MP4 visual audit timed out; use fewer samples or a smaller video"}
    except OSError as exc:
        return {"ok": False, "error": f"could not start MP4 audit: {exc}"}
    output = ((result.stdout or "") + (result.stderr or ""))[-12_000:]
    response = {"ok": result.returncode == 0,
                "video": video.name,
                "samples": sample_count,
                "diagnostics": output}
    if report:
        response["report"] = str(report)
    if frames_dir:
        response["frames_dir"] = str(frames_dir)
    return response
