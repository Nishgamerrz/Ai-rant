#!/usr/bin/env python3
"""Extract and validate one continuous 1–2 minute narration from Ollama output."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

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


def main():
    if len(sys.argv) != 4:
        raise SystemExit("usage: prepare_narration.py RESPONSE.json OUTPUT.txt DURATION_SECONDS")
    response_path, output_path = map(Path, sys.argv[1:3])
    duration = int(sys.argv[3])
    payload = json.loads(response_path.read_text(encoding="utf-8"))
    text = re.sub(r"\s+", " ", extract_narration(payload)).strip()
    words = re.findall(r"\b[\w’'-]+\b", text)
    minimum, maximum = int(duration * 1.9), int(duration * 2.1)
    forbidden_meta = re.search(r"\b(?:A\.I\.|AI|servers?|Roblox|avatars?|game mechanics?|generated)\b", text, re.IGNORECASE)
    if forbidden_meta:
        raise SystemExit(f"Narration includes forbidden AI/game meta-talk: {forbidden_meta.group(0)!r}.")
    if not minimum <= len(words) <= maximum:
        fields = ", ".join(payload.keys()) if isinstance(payload, dict) else type(payload).__name__
        if not text and isinstance(payload, dict) and payload.get("thinking"):
            reason = "Qwen3 returned private reasoning but no final narration; the request must use think:false. "
        else:
            reason = ""
        raise SystemExit(
            f"{reason}Narration is {len(words)} words (response fields: {fields}); expected "
            f"{minimum}–{maximum} for a {duration}-second short."
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text + "\n", encoding="utf-8")
    print(f"Prepared one continuous narration ({len(words)} words).")


if __name__ == "__main__":
    main()
