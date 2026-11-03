#!/usr/bin/env python3
"""Fetch a few web references for story realism; search failure is non-fatal."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: research_story.py STORY_TOPIC OUTPUT.json")
    topic, output = sys.argv[1], Path(sys.argv[2])
    results = []
    try:
        from ddgs import DDGS
        query = f"{topic} real life background facts"
        with DDGS(timeout=8) as search:
            for item in search.text(query, max_results=4, safesearch="moderate"):
                title = str(item.get("title", "")).strip()[:160]
                url = str(item.get("href", "")).strip()[:500]
                snippet = str(item.get("body", "")).strip()[:420]
                if title and url and url.startswith(("https://", "http://")):
                    results.append({"title": title, "url": url, "snippet": snippet})
    except Exception as exc:
        print(f"Web research unavailable; continuing without it ({type(exc).__name__}).", file=sys.stderr)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results[:4], ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Saved {min(len(results), 4)} web research result(s) for the AI prompt.")


if __name__ == "__main__":
    main()
