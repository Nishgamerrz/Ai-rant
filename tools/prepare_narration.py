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
from ai_activity import append_activity, redact_secrets  # noqa: E402
from console_style import paint  # noqa: E402

# Run #85 rendered its whole video and was then refused with
#   SHORT NOT APPROVED: narration reads out selected usernames: noob
# The story prompt already forbids usernames, but a local model under pressure
# still drops one into the prose. Speaking a Roblox username is the one thing the
# narration must never do, so the text is scrubbed here - before the text-to-speech
# call, which also produces the captions - rather than blamed after the render.
INVENTED_NAMES = (
    "Maya", "Leo", "Ari", "Nina", "Sam", "Ruby", "Theo", "Ivy",
    "Milo", "Zara", "Owen", "Lena", "Jonah", "Priya", "Ellis", "June",
)

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


def narration_from_subagent(path: Path, *, expected_id: str = "t1") -> str:
    """Accept only the complete required edit result authored for narration."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SystemExit("Could not read the narration proofread result; the draft was not used.") from exc
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list) or len(results) != 1 or not isinstance(results[0], dict):
        raise SystemExit("The narration sub-agent did not return exactly one complete proofread; the draft was not used.")
    result = results[0]
    text = result.get("text")
    if (result.get("id") != expected_id or result.get("kind") != "edit"
            or result.get("ok") is not True or result.get("status") != "complete"
            or not isinstance(text, str) or not text.strip()):
        raise SystemExit("The narration sub-agent result is incomplete or invalid; the draft was not used.")
    if len(text) > 20000:
        raise SystemExit("The narration proofread is unexpectedly long; the draft was not used.")
    if text.strip().startswith("```") or text.strip().endswith("```"):
        raise SystemExit("The narration sub-agent returned formatting instead of plain corrected text; the draft was not used.")
    return text


def _word_limit(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    try:
        limit = int(value)
    except ValueError as exc:
        raise SystemExit(f"{name} must be a positive whole number.") from exc
    if limit < 1:
        raise SystemExit(f"{name} must be a positive whole number.")
    return limit


def cast_usernames() -> list[str]:
    """The selected Roblox usernames, from the environment or the cast file."""
    names = [name.strip() for name in os.environ.get("CAST_NAMES", "").split(",") if name.strip()]
    if not names:
        try:
            payload = json.loads(Path("dist/characters.json").read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                payload = payload.get("characters") or list(payload)
            names = [str(item.get("username") if isinstance(item, dict) else item)
                     for item in payload]
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            names = []
    return [name for name in names if name]


def invented_names(usernames, seed_text: str = "") -> dict[str, str]:
    """One stable, human first name per username.

    Stable for a given cast, so a re-run of the same topic keeps the same people,
    and never repeats a first name inside one video.
    """
    used: set[str] = set()
    mapping: dict[str, str] = {}
    offset = sum(ord(character) for character in seed_text) % len(INVENTED_NAMES)
    for position, username in enumerate(usernames):
        for step in range(len(INVENTED_NAMES)):
            candidate = INVENTED_NAMES[(offset + position * 5 + step) % len(INVENTED_NAMES)]
            if candidate.casefold() not in used:
                break
        used.add(candidate.casefold())
        mapping[username] = candidate
    return mapping


def scrub_usernames(text: str, usernames=None, mapping=None) -> tuple[str, list[str]]:
    """Swap every spoken username for an invented first name.

    Matches the username as a standalone word (underscores and digits count as
    word characters, so `noob` inside `noob_master` is left alone) and keeps the
    sentence readable: "noob walked in" becomes "Ruby walked in".
    """
    usernames = list(usernames if usernames is not None else cast_usernames())
    mapping = mapping or invented_names(usernames, text[:400])
    replaced: list[str] = []
    for username in sorted(usernames, key=len, reverse=True):
        if not username:
            continue
        pattern = re.compile(r"(?<![\w])" + re.escape(username) + r"(?![\w])", re.IGNORECASE)
        text, count = pattern.subn(mapping.get(username, "Sam"), text)
        if count:
            replaced.append(username)
    return text, replaced


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


def scrub_file(path: Path) -> int:
    """Rewrite a narration file in place with every spoken username replaced."""
    text = path.read_text(encoding="utf-8")
    cleaned, replaced = scrub_usernames(text)
    if not replaced:
        print(f"No Roblox username is spoken in {path}; nothing to change.")
        return 0
    path.write_text(cleaned, encoding="utf-8")
    print(f"Replaced spoken username(s) {', '.join(replaced)} in {path} with invented first "
          f"names, so the narrator never reads an account name aloud.")
    return 0


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--scrub":
        raise SystemExit(scrub_file(Path(sys.argv[2])))
    subagent_mode = len(sys.argv) in (5, 7) and sys.argv[1] == "--subagent"
    if not subagent_mode and len(sys.argv) not in (4, 6):
        raise SystemExit(
            "usage: prepare_narration.py RESPONSE.json OUTPUT.txt DURATION_SECONDS "
            "[--truncate TOPIC] | prepare_narration.py --subagent RESULTS.json OUTPUT.txt DURATION_SECONDS "
            "[--task-id ID] | prepare_narration.py --scrub narration.txt"
        )
    if subagent_mode:
        response_path, output_path = Path(sys.argv[2]), Path(sys.argv[3])
        duration = parse_duration(sys.argv[4])
        expected_task_id = "t1"
        if len(sys.argv) == 7:
            if sys.argv[5] != "--task-id" or not sys.argv[6].strip():
                raise SystemExit("the sub-agent option must be followed by --task-id ID")
            expected_task_id = sys.argv[6].strip()
        topic = "a complete narration proofread"
        truncate = False
    else:
        response_path, output_path = map(Path, sys.argv[1:3])
        duration = parse_duration(sys.argv[3])
        truncate = len(sys.argv) == 6 and sys.argv[4] == "--truncate"
        topic = sys.argv[5] if truncate else "a small act of honesty"
        if len(sys.argv) == 6 and not truncate:
            raise SystemExit("the optional arguments must be --truncate TOPIC")

    # The workflow exports its exact spoken-rate budget for the proofread to
    # meet. Standalone callers keep the established duration-scaled defaults.
    minimum = _word_limit("MIN_WORDS", max(1, int(duration * 1.4)))
    maximum = _word_limit("MAX_WORDS", max(24, int(duration * 5 / 3)))
    if minimum > maximum:
        raise SystemExit("MIN_WORDS cannot be greater than MAX_WORDS.")
    if subagent_mode:
        payload = {"response": {"narration": narration_from_subagent(
            response_path, expected_id=expected_task_id)}}
        text = str(payload["response"]["narration"])
    else:
        try:
            payload = json.loads(response_path.read_text(encoding="utf-8"))
            text = extract_narration(payload)
        except (OSError, UnicodeError, json.JSONDecodeError):
            payload, text = {}, ""
    if not subagent_mode:
        text = re.sub(r"\s+", " ", text).strip()
    text, replaced_usernames = scrub_usernames(text)
    if subagent_mode and replaced_usernames:
        raise SystemExit("The narration proofread included a selected username; it was not used. "
                         "Ask the sub-agent to replace it with an invented first name.")
    if replaced_usernames:
        print("Replaced spoken Roblox username(s) " + ", ".join(replaced_usernames)
              + " with invented first names before the voiceover.",
              file=sys.stderr)
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
            cast = list(invented_names(cast_usernames()).values())
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
    output_path.write_text(text if subagent_mode else text + "\n", encoding="utf-8")
    if subagent_mode:
        append_activity({
            "type": "narration_finalized", "stage": "narration",
            "tag": "[narration source]", "status": "complete",
            "source": "narration sub-agent proofread", "output": text,
            "word_count": len(words), "minimum_words": minimum,
            "maximum_words": maximum, "duration_seconds": duration,
        }, path=Path("dist/ai_activity.jsonl"), emit=False)
        print(paint(f"Sub-agent proofread accepted: {len(words)} words. This exact corrected text is now the narration source used downstream.",
                    "success", bold=True))
        display_text = redact_secrets(text)
        heading = ("[final corrected narration · exact downstream source]"
                   if display_text == text else
                   "[final corrected narration · exact downstream source; credentials masked in logs]")
        print(paint(heading, "label"), flush=True)
        print(paint(display_text, "tool"), flush=True)
    else:
        print(f"Prepared one continuous narration ({len(words)} words; maximum {maximum}).")


if __name__ == "__main__":
    main()
