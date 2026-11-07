#!/usr/bin/env python3
"""Web search the AI can call at any point in the pipeline.

Usage:
    python tools/ai_web_search.py dist/web_research.json "query one" ["query two" ...]

Results are merged (deduplicated by URL) into the JSON file the prompts read, so
the model can ask for more context during story writing, world planning, camera
planning or face/expression planning. Search failure is never fatal: the run
continues with whatever research already exists.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from console_style import paint  # noqa: E402

MAX_RESULTS = 4
MAX_STORED = 24


def search(query: str) -> list[dict]:
    try:
        from ddgs import DDGS
    except ImportError as exc:  # pragma: no cover - dependency installed in CI
        print(f"Web search unavailable ({exc}); continuing without it.", file=sys.stderr)
        return []
    results = []
    try:
        with DDGS(timeout=10) as client:
            for item in client.text(query, max_results=MAX_RESULTS, safesearch="moderate"):
                title = str(item.get("title", "")).strip()[:160]
                url = str(item.get("href", "")).strip()[:500]
                snippet = str(item.get("body", "")).strip()[:420]
                if title and url.startswith(("https://", "http://")):
                    results.append({"query": query[:120], "title": title, "url": url, "snippet": snippet})
    except Exception as exc:  # noqa: BLE001 - any network/DNS error must be non-fatal
        print(f"Search for {query!r} failed ({type(exc).__name__}); continuing without it.",
              file=sys.stderr)
    return results


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    output = Path(sys.argv[1])
    queries = [value.strip() for value in sys.argv[2:] if value.strip()]
    existing: list[dict] = []
    if output.is_file():
        try:
            loaded = json.loads(output.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                existing = [item for item in loaded if isinstance(item, dict)]
        except json.JSONDecodeError:
            existing = []
    seen = {item.get("url") for item in existing}
    added = 0
    for query in queries:
        print(paint(f"[web search] {query}", "tool"), flush=True)
        for result in search(query):
            if result["url"] in seen:
                continue
            seen.add(result["url"])
            existing.append(result)
            added += 1
            print(paint(f"  - {result['title']} — {result['url']}", "plan"), flush=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(existing[-MAX_STORED:], ensure_ascii=False) + "\n", encoding="utf-8")
    print(paint(f"[web search] added {added} new result(s); "
                f"{len(existing[-MAX_STORED:])} total available to the AI.", "tool"), flush=True)


if __name__ == "__main__":
    main()
