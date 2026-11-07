#!/usr/bin/env python3
"""Fix the spelling in the prompt the user typed, before any AI planning starts.

The Actions form is typed by hand, so the topic arrives with typos: "a stdent
finds a lost wallett on the way to shcool". Every later prompt repeats that text
verbatim, and a small local model happily inherits the mistakes.

So the raw text is cleaned once, up front, by Gemini: spelling, grammar and
punctuation fixed, the user's meaning and characters kept exactly, plus one or
two concrete details that make it a better prompt for a vertical Roblox-style
story short. The reply is used as the run's story/theme prompt from then on.

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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from console_style import paint  # noqa: E402

from gemini_subagent import (  # noqa: E402
    API_KEY_ENV,
    DEFAULT_MODEL,
    DEFAULT_MODEL_VAR,
    GeminiUnavailable,
    call_gemini,
)

# This parenthetical is the note the workflow promised: Gemini is told that the
# text came from a person and may be misspelled, and that fixing it is silent.
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
- If the text opens with a premise ("In a world where ...", "What if ..."), keep
  that opening word for word. It is the idea of the story, not scene-setting.
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


# A story prompt is a premise, not a scene: "In a world where ..." or "What if ..."
# is what the later prompts build the story from. Gemini likes to rewrite it as a
# paragraph of scene-setting, which quietly replaces the idea with a moment.
PREMISE_OPENERS = ("in a world where", "in a world", "what if", "imagine a world")


def premise_of(text: str) -> str | None:
    """The family of premise an opener belongs to ("in a world where" and
    "in a world" count as the same idea, so a small rewording is still allowed)."""
    lowered = " ".join((text or "").split()).casefold()
    for opener in PREMISE_OPENERS:
        if lowered.startswith(opener):
            return "in a world" if opener.startswith("in a world") else opener
    return None


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
    raw_premise = premise_of(raw)
    if raw_premise and premise_of(text) != raw_premise:
        return None, (f"the reply dropped the {raw_premise!r} premise and became a "
                      "scene instead of a what-if")
    return text, "ok"


def refine(text: str, *, api_key: str, model: str = DEFAULT_MODEL,
           kind: str = "story", url: str | None = None,
           timeout: float = 60.0) -> dict:
    """Clean one prompt. Never raises: falls back to the text as typed."""
    raw = str(text or "").strip()
    if not raw:
        return {"ok": False, "skipped": True, "text": "", "reason": "nothing to clean"}
    if not api_key:
        return {"ok": False, "skipped": True, "text": raw, "reason": "no API key"}
    try:
        reply = call_gemini(build_prompt(raw, kind), api_key=api_key, model=model,
                            timeout=timeout, url=url)
    except GeminiUnavailable as exc:
        return {"ok": False, "skipped": False, "text": raw, "reason": str(exc)[:300]}
    cleaned, reason = sanitize(reply, raw)
    if cleaned is None:
        return {"ok": False, "skipped": False, "text": raw, "reason": reason}
    return {"ok": True, "skipped": False, "text": cleaned, "reason": "ok",
            "original": raw}


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
    parser.add_argument("--stdout", action="store_true", help="print the cleaned story prompt")
    parser.add_argument("--url", help="override the Gemini endpoint (tests)")
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()

    api_key = os.environ.get(API_KEY_ENV, "").strip()
    story_raw = os.environ.get(args.story_env, "")
    theme_raw = os.environ.get(args.theme_env, "")

    story = refine(story_raw, api_key=api_key, model=args.model, kind="story",
                   url=args.url, timeout=args.timeout)
    theme = (refine(theme_raw, api_key=api_key, model=args.model, kind="theme",
                    url=args.url, timeout=args.timeout)
             if theme_raw.strip() else {"ok": False, "skipped": True, "text": "",
                                        "reason": "no theme typed"})

    if not api_key:
        print(paint("[gemini topic] GEMINI_API_KEY is not configured; using the prompt "
                    "exactly as typed. Add the secret to fix spelling automatically.",
                    "warning"), flush=True)
    for label, entry, raw in (("story prompt", story, story_raw),
                              ("world theme", theme, theme_raw)):
        if entry["skipped"]:
            continue
        if entry["ok"]:
            print(paint(f"[gemini topic] cleaned the {label} with {args.model}:", "tool"),
                  flush=True)
            print(paint(f"[gemini topic]   as typed : {' '.join(raw.split())}", "thought"),
                  flush=True)
            print(paint(f"[gemini topic]   cleaned  : {entry['text']}", "answer"), flush=True)
        else:
            print(paint(f"[gemini topic] kept the {label} as typed ({entry['reason']}).",
                        "notice"), flush=True)

    values = {"story_topic": story["text"], "world_theme": theme["text"]}
    _write_outputs(args.github_output, values)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"model": args.model, "story": story,
                                           "theme": theme}, ensure_ascii=False, indent=2),
                               encoding="utf-8")
    if args.stdout:
        print(story["text"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
