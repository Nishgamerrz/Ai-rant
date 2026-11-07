#!/usr/bin/env python3
"""Colour for the Actions console.

The run log mixes a local model's reasoning, its answer, tool chatter, Gemini
replies and errors. Read in one grey wall it is impossible to tell where the
model stopped thinking and started answering. This module gives every kind of
line its own colour so the live log can be skimmed while it streams.

Behaviour:

* ``AI_COLOR=1`` (set by the workflow) turns colour on even though Actions is
  not a TTY - the log viewer renders ANSI codes.
* ``NO_COLOR`` or ``AI_COLOR=0`` turns it off.
* With neither set, colour follows ``stdout.isatty()``, so tests and pipes stay
  plain text.
"""
from __future__ import annotations

import os
import sys

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

# One hue per kind of line. GitHub prints the log on near-black, so these are
# deliberately mid-dark, desaturated tones: the old palette used a bright grey for
# thinking and a neon cyan for the answer, which was tiring to look at for the
# twenty minutes a local model can run. Nothing here is brighter than the code.
CODES = {
    "thinking": "\033[38;5;109m",   # dusty blue-grey: the model working it out
    "answer": "\033[38;5;108m",     # sage green: the real answer
    "label": "\033[38;5;74m",       # steel blue: who is speaking
    "notice": "\033[38;5;180m",     # tan: waiting, retrying, switching model
    "success": "\033[38;5;71m",     # moss green: finished, accepted
    "warning": "\033[38;5;173m",    # clay: recovered from something
    "error": "\033[38;5;167m",      # brick: failed, dropped
    "tool": "\033[38;5;140m",       # muted violet: tools, gemini, sub-agent
    "plan": "\033[38;5;145m",       # pale slate: plan/world details
    "thought": "\033[38;5;240m",    # dark grey: the rare quiet waiting note
    "frame": "\033[38;5;238m",      # near-invisible grey: the thinking box edge
}


def enabled(stream=None) -> bool:
    setting = os.environ.get("AI_COLOR", "").strip().lower()
    if setting in {"0", "false", "no", "off", "never"}:
        return False
    if os.environ.get("NO_COLOR"):
        return False
    if setting in {"1", "true", "yes", "on", "always"}:
        return True
    target = stream or sys.stdout
    try:
        return bool(target.isatty())
    except (AttributeError, ValueError):
        return False


def paint(text: str, kind: str = "label", *, stream=None, bold: bool = False) -> str:
    """Wrap text in the colour for `kind`, or return it untouched."""
    if not text or not enabled(stream):
        return text
    code = CODES.get(kind, "")
    if not code:
        return text
    prefix = (BOLD if bold else "") + code
    return f"{prefix}{text}{RESET}"


def ansi(kind: str = "label", *, stream=None) -> str:
    """The raw escape sequence for a kind ("" when colour is off)."""
    if not enabled(stream):
        return ""
    return CODES.get(kind, "")


def strip(text: str) -> str:
    """Remove ANSI escapes (used by tests and by any consumer of a log line)."""
    out, index = [], 0
    while index < len(text):
        if text[index] == "\033" and index + 1 < len(text) and text[index + 1] == "[":
            index += 2
            while index < len(text) and text[index] not in "mK":
                index += 1
            index += 1
            continue
        out.append(text[index])
        index += 1
    return "".join(out)
