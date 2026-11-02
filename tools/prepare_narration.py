#!/usr/bin/env python3
"""Extract and validate one continuous 1–2 minute narration from Ollama output."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def main():
    if len(sys.argv) != 4:
        raise SystemExit("usage: prepare_narration.py RESPONSE.json OUTPUT.txt DURATION_SECONDS")
    response_path, output_path = map(Path, sys.argv[1:3])
    duration = int(sys.argv[3])
    payload = json.loads(response_path.read_text(encoding="utf-8"))
    response = payload.get("response", "") if isinstance(payload, dict) else ""
    try:
        story = json.loads(response)
    except (json.JSONDecodeError, TypeError):
        story = {}
    text = story.get("narration", "") if isinstance(story, dict) else ""
    if not isinstance(text, str):
        raise SystemExit("The AI did not return a narration string.")
    text = re.sub(r"\s+", " ", text).strip()
    words = re.findall(r"\b[\w’'-]+\b", text)
    # In the tested voice pipeline, ~1.7 words/second lands near the chosen runtime.
    minimum, maximum = int(duration * 1.6), int(duration * 1.75)
    if not minimum <= len(words) <= maximum:
        raise SystemExit(
            f"Narration is {len(words)} words; expected {minimum}–{maximum} "
            f"for a {duration}-second short. Rerun the workflow."
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text + "\n", encoding="utf-8")
    print(f"Prepared one continuous female-voice narration ({len(words)} words).")


if __name__ == "__main__":
    main()
