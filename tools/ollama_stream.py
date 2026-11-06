#!/usr/bin/env python3
"""Stream an Ollama chat request and show the model's live thinking in the log.

The workflow used to post a blocking request, so the Actions console sat silent
for minutes while the model worked. This wrapper asks Ollama to stream, prints
the reasoning and the answer as they arrive, and finally writes the same
aggregated JSON envelope the rest of the pipeline already reads.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_URL = "http://127.0.0.1:11434/api/chat"
PREVIEW = 90


def clean(text: str) -> str:
    return " ".join(str(text).split())[-PREVIEW:]


def stream(request: dict, url: str, label: str, timeout: float, quiet: bool) -> dict:
    request = {**request, "stream": True}
    payload = json.dumps(request).encode("utf-8")
    http = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    content: list[str] = []
    thinking: list[str] = []
    started = time.time()
    last_report = 0.0
    tokens = 0
    with urllib.request.urlopen(http, timeout=timeout) as response:
        for raw in response:
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            message = event.get("message") or {}
            piece_thinking = message.get("thinking") or ""
            piece_content = message.get("content") or ""
            if piece_thinking:
                thinking.append(piece_thinking)
            if piece_content:
                content.append(piece_content)
            if event.get("done"):
                tokens = int(event.get("eval_count") or 0)
            now = time.time()
            if not quiet and now - last_report > 2.0:
                last_report = now
                elapsed = now - started
                if piece_thinking and not content:
                    print(f"[{label}] thinking… {sum(len(p) for p in thinking):,} chars, {elapsed:.0f}s "
                          f"· …{clean(''.join(thinking))}", flush=True)
                elif content:
                    print(f"[{label}] writing… {sum(len(p) for p in content):,} chars, {elapsed:.0f}s "
                          f"· …{clean(''.join(content))}", flush=True)
                else:
                    print(f"[{label}] waiting for the model… {elapsed:.0f}s", flush=True)
    answer = "".join(content)
    reasoning = "".join(thinking)
    elapsed = time.time() - started
    if not quiet:
        print(f"[{label}] ✓ finished in {elapsed:.0f}s: {len(answer):,} answer chars, "
              f"{len(reasoning):,} reasoning chars, {tokens} tokens.", flush=True)
        if reasoning:
            print(f"[{label}] reasoning preview: …{clean(reasoning)}", flush=True)
    return {
        "message": {"role": "assistant", "content": answer, "thinking": reasoning},
        "response": answer,
        "thinking": reasoning,
        "done": True,
        "eval_count": tokens,
        "label": label,
        "elapsed_seconds": round(elapsed, 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path, help="Ollama chat request JSON")
    parser.add_argument("--output", required=True, type=Path, help="where to write the aggregated response")
    parser.add_argument("--label", default="AI", help="console prefix, e.g. 'world plan'")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--keep-stream-flag", action="store_true",
                        help="keep stream:true in the written request file for debugging")
    args = parser.parse_args()

    request = json.loads(args.request.read_text(encoding="utf-8"))
    print(f"[{args.label}] sending {request.get('model', 'model')} request "
          f"(temperature {request.get('options', {}).get('temperature', 'default')}); "
          f"live thinking is printed below.", flush=True)
    try:
        result = stream(request, args.url, args.label, args.timeout, args.quiet)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"[{args.label}] streaming request failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    if not result["response"].strip():
        print(f"[{args.label}] the model returned an empty answer.", file=sys.stderr)
        raise SystemExit(1)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False) + "\n", encoding="utf-8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as out:
            out.write(f"- **{args.label}:** {result['eval_count']} tokens in {result['elapsed_seconds']}s "
                      f"({len(result['response']):,} answer chars)\n")


if __name__ == "__main__":
    main()
