#!/usr/bin/env python3
"""Extract a compact, bounded narration for any chosen length (15-300 s)."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from durations import parse_duration  # noqa: E402

TEXT_KEYS = ("narration", "voiceover", "voiceover_script", "spoken_script", "script", "story", "narrative", "short_story", "text", "content")


def text_from_value(value):
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return " ".join(text_from_value(item) for item in value if isinstance(item, str)).strip()
    if isinstance(value, dict):
        for key in TEXT_KEYS:
            text = text_from_value(value.get(key))
            if text:
                return text
        # Some models ignore the requested field name. Accept the first actual
        # paragraph-sized string, but never mistake a title for the narration.
        for key, item in value.items():
            text = text_from_value(item)
            if key.lower() not in {"name", "title", "duration", "seconds", "priority"} and len(text.split()) >= 30:
                return text
    return ""


def extract_narration(payload):
    if isinstance(payload, dict):
        response = payload.get("response")
        if not response:
            message = payload.get("message")
            response = message.get("content") if isinstance(message, dict) else ""
        if not response:
            response = payload.get("final") or payload.get("output") or payload.get("result", "")
    else:
        response = payload

    if isinstance(response, (dict, list)):
        return text_from_value(response)
    if not isinstance(response, str):
        return ""

    raw = response.strip()
    # Qwen3 may put private reasoning before or after its final JSON response.
    raw = re.sub(r"<think>.*?(?:</think>|$)", " ", raw, flags=re.IGNORECASE | re.DOTALL)
    raw = re.sub(r"<\|[^|]+\|>", " ", raw)
    raw = re.sub(r"```(?:json|text)?|```", " ", raw, flags=re.IGNORECASE).strip()

    candidates = []
    try:
        candidates.append(json.loads(raw))
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for match in re.finditer(r"[\[{\"]", raw):
        try:
            candidate, _ = decoder.raw_decode(raw[match.start():])
        except json.JSONDecodeError:
            continue
        candidates.append(candidate)
    short_candidate = ""
    for candidate in candidates:
        text = text_from_value(candidate)
        if len(text.split()) >= 30:
            return text
        if text:
            short_candidate = text

    # Recover the requested field even if the model produced imperfect JSON.
    for key in TEXT_KEYS:
        match = re.search(rf'"{re.escape(key)}"\s*:\s*("(?:\\.|[^"\\])*")', raw, re.IGNORECASE | re.DOTALL)
        if match:
            try:
                text = json.loads(match.group(1)).strip()
                if text:
                    return text
            except json.JSONDecodeError:
                pass

    if short_candidate:
        return short_candidate

    # Last resort: accept plain prose instead of treating it as an empty script.
    raw = re.sub(r"^(?:here(?:'s| is)\s+)?(?:the\s+)?(?:narration|voiceover|script|story)\s*:\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s+", " ", raw).strip()
    if raw.startswith("{") or raw.startswith("["):
        return ""
    return raw


def trim_to_word_limit(text, limit):
    """Trim at a sentence boundary when possible, preserving readable punctuation."""
    sentences = re.split(r"(?<=[.!?…])\s+", text.strip())
    selected = []
    count = 0
    for sentence in sentences:
        sentence_count = len(re.findall(r"\b[\w’'-]+\b", sentence))
        if count + sentence_count > limit:
            break
        selected.append(sentence)
        count += sentence_count
    if selected:
        return " ".join(selected).strip()

    # If even the first sentence exceeds the cap, cut at a complete word.
    parts = text.split()
    while parts and len(re.findall(r"\b[\w’'-]+\b", " ".join(parts))) > limit:
        parts.pop()
    clipped = " ".join(parts).rstrip(" ,;:-")
    if clipped and clipped[-1] not in ".!?…":
        clipped += "."
    return clipped


def main():
    if len(sys.argv) not in (4, 6):
        raise SystemExit(
            "usage: prepare_narration.py RESPONSE.json OUTPUT.txt DURATION_SECONDS "
            "[--truncate TOPIC]"
        )
    response_path, output_path = map(Path, sys.argv[1:3])
    duration = parse_duration(sys.argv[3])
    truncate = len(sys.argv) == 6 and sys.argv[4] == "--truncate"
    topic = sys.argv[5] if truncate else "a small act of honesty"
    if len(sys.argv) == 6 and not truncate:
        raise SystemExit("the optional arguments must be --truncate TOPIC")

    # Word limits scale with the requested length. The old hard 100-word cap
    # silently rejected every 90-180 second short, so long videos could never
    # pass this gate. The floor matches validate_short.py exactly: rejecting a
    # narration the final quality gate would accept only costs another long,
    # thinking-heavy generation round.
    minimum = max(1, int(duration * 1.4))
    maximum = max(24, int(duration * 5 / 3))
    try:
        payload = json.loads(response_path.read_text(encoding="utf-8"))
        text = re.sub(r"\s+", " ", extract_narration(payload)).strip()
    except (OSError, json.JSONDecodeError):
        payload, text = {}, ""
    words = re.findall(r"\b[\w’'-]+\b", text)
    forbidden = re.compile(r"\b(?:A\.I\.|AI|servers?|Roblox|avatars?|game mechanics?|generated)\b", re.IGNORECASE)
    forbidden_meta = forbidden.search(text)

    if truncate:
        # Last-resort guard after the AI has had two chances to rewrite its own draft.
        # Keep the MP4 workflow moving, but never let the final voiceover exceed the cap.
        text = forbidden.sub("", text)
        text = re.sub(r"\s+", " ", text).strip()
        words = re.findall(r"\b[\w’'-]+\b", text)
        if len(words) > maximum:
            text = trim_to_word_limit(text, maximum)
            words = re.findall(r"\b[\w’'-]+\b", text)
        if not text or len(words) < minimum:
            # A compact known-good story is the last resort when the model stays
            # below the floor after the directional rewrite retries.
            cast = [name.strip() for name in os.environ.get("CAST_NAMES", "").split(",") if name.strip()]
            lead = cast[0] if cast else "Maya"
            group = lead if len(cast) == 1 else f"{', '.join(cast[:-1])} and {cast[-1]}" if cast else lead
            text = (
                f"On a busy afternoon, {group} spotted a wallet beside the school gate. "
                f"{lead} checked only for a name, then brought it to the office before hurrying home. "
                "A worried parent returned minutes later, grateful to find the family photo still inside. "
                f"{lead} had nearly walked past, but stopping took only a moment. "
                "That evening, the relieved smile reminded everyone that doing the right thing often begins with one small decision. "
                "They hoped someone would show the same care if they ever lost something important."
            )
            text = trim_to_word_limit(text, maximum)
            words = re.findall(r"\b[\w’'-]+\b", text)
            for sentence in ("It mattered.", "She felt glad.", "That was enough."):
                extra = len(re.findall(r"\b[\w’'-]+\b", sentence))
                if len(words) >= minimum or len(words) + extra > maximum:
                    continue
                text = f"{text} {sentence}"
                words = re.findall(r"\b[\w’'-]+\b", text)
        print(f"Final short-story guard applied for {topic!r}: {len(words)} words (target {minimum}–{maximum}).")
    elif forbidden_meta:
        raise SystemExit(f"Narration includes forbidden AI/game meta-talk: {forbidden_meta.group(0)!r}.")
    elif not minimum <= len(words) <= maximum:
        fields = ", ".join(payload.keys()) if isinstance(payload, dict) else type(payload).__name__
        raise SystemExit(
            f"Narration is {len(words)} words (response fields: {fields}); target "
            f"{minimum}–{maximum} words for a {duration}-second short."
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text + "\n", encoding="utf-8")
    print(f"Prepared one continuous narration ({len(words)} words; maximum {maximum}).")


if __name__ == "__main__":
    main()
