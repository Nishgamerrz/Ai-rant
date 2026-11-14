#!/usr/bin/env python3
"""Fix the spelling in the prompt the user typed, before any AI planning starts.

The Actions form is typed by hand, so the topic arrives with typos: "a stdent
finds a lost wallett on the way to shcool". Every later prompt repeats that text
verbatim, and a small local model happily inherits the mistakes.

So the raw text is cleaned once, up front, by the shared text provider
(BazaarLink first, then Gemini, then Groq): spelling, grammar and punctuation
fixed, the user's meaning and characters kept exactly, plus one or two concrete
details that make it a better prompt for a vertical Roblox-style story short.
The reply is used as the run's story/theme prompt from then on.

Rules the model is given (see TOPIC_NOTE):

* output the rewritten prompt and nothing else,
* never mention spelling, typos, corrections or the note itself,
* never answer the prompt, never explain, never add a heading.

The answer is also checked locally: a reply that talks about correcting
something, or that is wildly longer than the input, is thrown away and the
user's own wording is used instead. A missing key is a clean no-op.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ai_activity import append_activity, redact_secrets, sanitize_data  # noqa: E402
from console_style import paint  # noqa: E402

from gemini_subagent import (  # noqa: E402
    API_KEY_ENV,
    bazaar_link_api_key_from_env,
    DEFAULT_MODEL,
    DEFAULT_MODEL_VAR,
    GROQ_KEY_ENV,
    GeminiUnavailable,
    call_any,
)

# This parenthetical tells whichever text provider runs that the typed input
# may be misspelled, and that fixing it is silent.
TOPIC_NOTE = (
    "(Note: the text below was typed by the user of this workflow and may contain "
    "spelling, grammar or punctuation mistakes. Correct them silently. Never mention "
    "this note, never mention spelling, typos, grammar or corrections, and never say "
    "that anything was rewritten or improved.)"
)

STORY_RULES = """\
Rewrite the story prompt below so it reads correctly and makes a better prompt for
a short vertical Roblox-style story video.
- Fix every spelling, grammar and punctuation mistake.
- Keep the user's story, setting, characters and intent exactly as they are: same
  people, same situation, same mechanic, same outcome. Do not replace their idea
  with your own, and do not turn a "what if" premise into a scene that merely
  happens to be at midnight.
- If the text opens with a premise, that premise is the whole story and must stay
  exactly where it is. It can be "In a world where ...", "In this world where ...",
  "In a world in which ...", "What if ...", "Imagine a world where ...", "Suppose
  ..." or "Let's say ...". Begin your rewrite with that same opening, word for
  word, and never delete, shorten or paraphrase it. Do not replace it with a time
  or a place ("At midnight", "One night", "In a small town"): those are scene-
  setting, and the premise is the idea the video is built from.
- If the text has no such premise, do not invent one.
- The rule that grants the wish, the power or the twist must survive unchanged:
  who gets it, when, and why the characters behave as they do.
- You may add one or two concrete, ordinary details that make the scene easier to
  film (a place, an object, a time of day), but never a new plot or a moral.
- One or two sentences, present tense, plain English, under 60 words.
- Output the rewritten prompt only. No quotes around it, no heading, no label, no
  explanation, no list, and no answer to the prompt itself."""

THEME_RULES = """\
Rewrite the world theme below so it reads correctly and makes a better styling
prompt for the 3D map of the same short.
- Fix every spelling, grammar and punctuation mistake.
- Keep the user's place and mood: same setting, same colours, same materials they
  named. Do not move the story somewhere else.
- You may add one or two concrete visual details (a material, a light, a colour
  direction), but do not invent a different location.
- One sentence, under 35 words.
- Output the rewritten theme only. No quotes, no heading, no label, no explanation."""

# Anything like this in the reply means the model talked about the job instead of
# doing it. Those answers are dropped and the user's own wording is kept.
META_PHRASES = (
    "spelling", "spellings", "misspell", "typo", "typos", "grammar", "grammatic",
    "corrected", "correcting", "correction", "rewrote", "rewritten", "rewrite",
    "here is", "here's", "certainly", "sure,", "note:", "i fixed", "i've fixed",
    "fixed the", "as an ai", "the user", "your prompt", "the prompt below",
    "original text", "improved version",
)
PREFIXES = (
    "rewritten prompt:", "revised prompt:", "corrected prompt:", "fixed prompt:",
    "improved prompt:", "story prompt:", "story topic:", "topic:", "theme:",
    "rewritten theme:", "revised theme:", "output:", "answer:",
)


def build_prompt(text: str, kind: str = "story") -> str:
    """The full instruction for one prompt-cleanup call."""
    rules = STORY_RULES if kind == "story" else THEME_RULES
    label = "Story prompt" if kind == "story" else "World theme"
    return "\n\n".join([rules, TOPIC_NOTE, f"{label} to clean up:\n{text.strip()}"])


# A story prompt is a premise, not a scene. "In a world where ...", "In this world
# where ...", "What if ..." - that clause is the idea every later prompt builds the
# map, the cast, the narration and the ending from. Gemini likes to rewrite it as
# scene-setting ("At midnight, two brothers ..."), which quietly replaces the idea
# with a moment, so the premise is protected rather than left to chance.
WORLD_PHRASE = re.compile(
    r"\b(?:in|of)\s+(?:a|an|this|our|one|another|the)\s+"
    r"(?:world|universe|land|town|city|realm|country|village|planet|time|time period)\b",
    re.IGNORECASE,
)
PREMISE_PATTERNS = (
    ("world", WORLD_PHRASE),
    ("what if", re.compile(r"\bwhat\s+if\b", re.IGNORECASE)),
    ("imagine", re.compile(r"\bimagine\s+(?:a|an|this|that|if|what)\b", re.IGNORECASE)),
    ("suppose", re.compile(r"\b(?:suppose|let's say)\b", re.IGNORECASE)),
)


def premises(text: str) -> set[str]:
    """Every kind of premise clause the text uses ("world", "what if", ...)."""
    flat = " ".join((text or "").split())
    return {name for name, pattern in PREMISE_PATTERNS if pattern.search(flat)}


def starts_with_premise(text: str) -> bool:
    """True when the first clause is the premise, in any of its usual shapes."""
    flat = " ".join((text or "").split())
    return any(pattern.match(flat) for _, pattern in PREMISE_PATTERNS)


def _tidy_punctuation(text: str) -> str:
    """Close the gaps a model leaves around punctuation and finish the sentence."""
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    if text and text[-1] not in ".!?":
        text += "."
    return text


def _strip_wrapping(text: str) -> str:
    """Take the fenced/quoted/labelled reply down to bare prompt text."""
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    kept = [line for line in lines if not line.strip().startswith("```")]
    text = "\n".join(kept).strip()
    lowered = text.casefold()
    for prefix in PREFIXES:
        if lowered.startswith(prefix):
            text = text[len(prefix):].strip()
            break
    for quote in ('"', "'", "\u201c", "\u2018"):
        closing = {'"': '"', "'": "'", "\u201c": "\u201d", "\u2018": "\u2019"}[quote]
        if len(text) >= 2 and text.startswith(quote) and text.endswith(closing):
            text = text[1:-1].strip()
    text = _tidy_punctuation(" ".join(text.split()))
    return text


def sanitize(reply: str, raw: str) -> tuple[str | None, str]:
    """Return (usable_text, reason). unusable_text means keep the user's wording."""
    text = _strip_wrapping(reply or "")
    if not text:
        return None, "the reply was empty"
    lowered = text.casefold()
    for phrase in META_PHRASES:
        if phrase in lowered:
            return None, f"the reply talked about the change ({phrase!r})"
    if text.startswith(("(", "[", "{")) or "**" in text or text.count("\n") > 1:
        return None, "the reply was formatted like an explanation, not a prompt"
    if not 3 <= len(text) <= max(240, int(len(raw.strip()) * 3)):
        return None, "the reply was not a plausible rewrite of the input"
    if len(text.split()) > max(12, len(raw.split()) * 3 + 10):
        return None, "the reply grew far beyond the input"
    bare, raw_bare = text.rstrip(".!? ").casefold(), raw.strip().rstrip(".!? ").casefold()
    if bare and bare == raw_bare:
        return None, "the reply was identical to the input"
    raw_premises, text_premises = premises(raw), premises(text)
    if raw_premises and not text_premises:
        return None, ("the reply deleted the "
                      + "/".join(sorted(raw_premises))
                      + " premise and became a scene instead of a what-if")
    if raw_premises and starts_with_premise(raw) and not starts_with_premise(text):
        return None, ("the reply moved the "
                      + "/".join(sorted(raw_premises))
                      + " premise out of the opening and turned it into scene-setting")
    return text, "ok"


def refine(text: str, *, api_key: str, model: str = DEFAULT_MODEL,
           kind: str = "story", bazaar_key: str | None = None,
           bazaar_url: str | None = None, url: str | None = None,
           timeout: float = 60.0, groq_key: str = "",
           groq_url: str | None = None, on_attempt=None) -> dict:
    """Clean one prompt. Never raises: falls back to the text as typed.

    The shared provider helper tries BazaarLink, then Gemini, then Groq. The
    optional callback gets safe provider-attempt metadata, never raw requests.
    """
    started = time.monotonic()
    raw = str(text or "").strip()
    api_key = str(api_key or "").strip()
    if bazaar_key is None:
        bazaar_key = bazaar_link_api_key_from_env()
    bazaar_key = str(bazaar_key or "").strip()
    groq_key = str(groq_key or os.environ.get(GROQ_KEY_ENV, "")).strip()
    attempts = []

    def report_attempt(event: dict) -> None:
        attempts.append(dict(event))
        if on_attempt:
            on_attempt(event)

    if not raw:
        return {"ok": False, "skipped": True, "text": "", "reason": "nothing to clean",
                "provider_attempts": attempts, "seconds": 0}
    if not bazaar_key and not api_key and not groq_key:
        return {"ok": False, "skipped": True, "text": raw, "reason": "no API key",
                "provider_attempts": attempts, "seconds": round(time.monotonic() - started, 2)}
    try:
        reply, provider = call_any(build_prompt(raw, kind),
                                   bazaar_key=bazaar_key, bazaar_url=bazaar_url,
                                   gemini_key=api_key, gemini_model=model,
                                   groq_key=groq_key, timeout=timeout,
                                   url=url, groq_url=groq_url,
                                   on_attempt=report_attempt)
    except GeminiUnavailable as exc:
        return {"ok": False, "skipped": False, "text": raw, "reason": str(exc)[:300],
                "provider_attempts": attempts,
                "seconds": round(time.monotonic() - started, 2)}
    answered = next((attempt for attempt in reversed(attempts)
                     if str(attempt.get("status") or "").lower() == "answered"), {})
    # Provider-attempt telemetry is authoritative for the visible label. This
    # prevents a stale/incorrect compatibility return value from calling a
    # BazaarLink completion a Gemini answer (or vice versa).
    actual_provider = str(answered.get("provider") or provider or "").strip().lower()
    provider_model = str(answered.get("model") or "").strip()
    cleaned, reason = sanitize(reply, raw)
    common = {"provider": actual_provider, "provider_model": provider_model,
              "provider_attempts": attempts,
              "seconds": round(time.monotonic() - started, 2)}
    if cleaned is None:
        return {"ok": False, "skipped": False, "text": raw, "candidate": reply,
                "reason": reason, **common}
    return {"ok": True, "skipped": False, "text": cleaned, "candidate": reply,
            "reason": "ok", "original": raw, **common}


def _write_outputs(path: str | None, values: dict) -> None:
    """Write step outputs. A typed prompt may contain newlines, so use the
    heredoc form GitHub supports rather than a bare key=value line."""
    if not path:
        return
    with Path(path).open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            text = str(value or "").rstrip("\n")
            if "\n" in text:
                delimiter = "GH_TOPIC_EOF"
                handle.write(f"{key}<<{delimiter}\n{text}\n{delimiter}\n")
            else:
                handle.write(f"{key}={text}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--story-env", default="RAW_STORY_TOPIC",
                        help="environment variable holding the typed story prompt")
    parser.add_argument("--theme-env", default="RAW_WORLD_THEME",
                        help="environment variable holding the typed world theme")
    parser.add_argument("--model", default=os.environ.get(DEFAULT_MODEL_VAR) or DEFAULT_MODEL)
    parser.add_argument("--output", type=Path, help="write the cleaned prompts here as JSON")
    parser.add_argument("--github-output", help="path of $GITHUB_OUTPUT")
    parser.add_argument("--stdout", action="store_true",
                        help="show whether each prompt was corrected and print the exact text used")
    parser.add_argument("--url", help="override the Gemini endpoint (tests)")
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()

    api_key = os.environ.get(API_KEY_ENV, "").strip()
    bazaar_key = bazaar_link_api_key_from_env()
    groq_key = os.environ.get(GROQ_KEY_ENV, "").strip()
    story_raw = os.environ.get(args.story_env, "")
    theme_raw = os.environ.get(args.theme_env, "")

    activity_path = (args.output.parent if args.output else Path("dist")) / "ai_activity.jsonl"

    def topic_tag(provider: str = "") -> str:
        provider = str(provider or "").strip().lower()
        if not provider:
            return "[topic cleanup]"
        label = {"bazaarlink": "bazaar", "gemini": "gemini", "groq": "groq"}.get(
            provider, provider)
        return f"[{label} topic]"

    def attempt_logger(label: str):
        def log_attempt(attempt: dict) -> None:
            provider = str(attempt.get("provider") or "").strip().lower()
            append_activity({"type": "provider_attempt", "stage": "topic",
                             "label": label, "tag": topic_tag(provider), **attempt},
                            path=activity_path, emit=False)
        return log_attempt

    story = refine(story_raw, api_key=api_key, bazaar_key=bazaar_key,
                   model=args.model, kind="story", url=args.url,
                   timeout=args.timeout, groq_key=groq_key,
                   on_attempt=attempt_logger("story prompt"))
    theme = (refine(theme_raw, api_key=api_key, bazaar_key=bazaar_key,
                    model=args.model, kind="theme", url=args.url,
                    timeout=args.timeout, groq_key=groq_key,
                    on_attempt=attempt_logger("world theme"))
             if theme_raw.strip() else {"ok": False, "skipped": True, "text": "",
                                        "reason": "no theme typed"})

    for label, kind, entry, raw in (("story prompt", "story", story, story_raw),
                                    ("world theme", "theme", theme, theme_raw)):
        if not raw.strip():
            continue
        attempts = entry.get("provider_attempts", [])
        answered = next((attempt for attempt in reversed(attempts)
                         if str(attempt.get("status") or "").lower() == "answered"), {})
        # Use the last provider whose request actually answered for artifact metadata.
        provider = str(answered.get("provider") or entry.get("provider") or "").strip().lower()
        provider_model = str(answered.get("model") or entry.get("provider_model") or "").strip()
        tag = topic_tag(provider)
        status = "cleaned" if entry.get("ok") else (
            "skipped" if entry.get("skipped") else "kept_input")
        candidate = entry.get("candidate")
        append_activity({
            "type": "topic_cleanup", "stage": "topic", "tag": tag,
            "label": label, "kind": kind, "status": status,
            "provider": provider, "model": provider_model,
            "seconds": entry.get("seconds"),
            "provider_attempts": attempts,
            "input": raw,
            "prompt": build_prompt(raw, kind) if provider else "",
            "output": candidate if candidate is not None else entry.get("text", raw),
            "cleaned_text": entry.get("text", raw),
            "reason": entry.get("reason", ""),
        }, path=activity_path, emit=False)
        if args.stdout:
            if entry.get("ok"):
                status_line = f"[prompt cleanup] Corrected the {label} for spelling, grammar and punctuation."
                status_kind = "success"
            elif entry.get("skipped") and entry.get("reason") == "no API key":
                status_line = (f"[prompt cleanup] No text provider is configured for the {label}; "
                               "retaining the original wording.")
                status_kind = "warning"
            else:
                status_line = (f"[prompt cleanup] No safe correction was produced for the {label}; "
                               "retaining the original wording.")
                status_kind = "warning"
            print(paint(status_line, status_kind), flush=True)
            final_text = redact_secrets(entry.get("text", raw)).strip()
            if final_text:
                print(paint(f"[effective {label}]", "label"), flush=True)
                print(paint(final_text, "answer"), flush=True)

    values = {"story_topic": story["text"], "world_theme": theme["text"]}
    _write_outputs(args.github_output, values)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        record = sanitize_data({"model": args.model, "story": story, "theme": theme})
        args.output.write_text(json.dumps(record, ensure_ascii=False, indent=2),
                               encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
