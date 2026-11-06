#!/usr/bin/env python3
"""Parse a Roblox cast list; first username is the lead character.

Usernames may be separated by commas, semicolons, spaces or newlines, because the
"Run workflow" form has a single text box and people paste lists in every style.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

USERNAME = re.compile(r"[A-Za-z0-9_]{3,20}\Z")
MAX_CHARACTERS = 6


def parse(value: str) -> list[str]:
    names, seen = [], set()
    for raw in re.split(r"[,;\s]+", value):
        name = raw.strip()
        if not name:
            continue
        if not USERNAME.fullmatch(name):
            raise ValueError(f"Invalid Roblox username {name!r}; use 3–20 letters, digits, or underscores.")
        key = name.casefold()
        if key not in seen:
            names.append(name)
            seen.add(key)
    if len(names) > MAX_CHARACTERS:
        raise ValueError(f"Use at most {MAX_CHARACTERS} comma-separated usernames so the full cast stays visible and renders quickly.")
    return names


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: parse_roblox_usernames.py \"Name1, Name2\" OUTPUT.json")
    try:
        names = parse(sys.argv[1])
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    output = Path(sys.argv[2])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(names, ensure_ascii=False) + "\n", encoding="utf-8")
    lead = names[0] if names else "AI-chosen protagonist"
    print(f"Prepared {len(names)} cast username(s); lead: {lead}.")


if __name__ == "__main__":
    main()
