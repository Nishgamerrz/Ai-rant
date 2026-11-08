#!/usr/bin/env python3
"""Report whether the AI model is still in RAM, so reloads are visible, not guessed.

The runner used to reload the model before several steps: each unload costs
minutes of CPU time on a free GitHub runner and makes the console look like the
AI is "starting over" every few minutes. Keep-alive was already set, so the
reloads came from somewhere else - a hand-over to the fallback model, or a call
made after the model was deliberately evicted for the render. Both are fixed, and
this tool is the proof: it records, for every AI step, whether the model was
already resident before that step ran.

Usage:
    python tools/model_residency.py --check --model qwen3:8b --label "story"
    python tools/model_residency.py --summary      # end-of-run table
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
DEFAULT_LOG = Path("dist/model_residency.log")


def loaded_models(url: str = DEFAULT_URL, timeout: float = 15.0) -> list[dict]:
    """Models Ollama currently holds in memory (GET /api/ps)."""
    request = urllib.request.Request(f"{url}/api/ps")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload.get("models") or []


def is_resident(model: str, url: str = DEFAULT_URL) -> tuple[bool, list[str]]:
    names = [str(item.get("name") or item.get("model") or "") for item in loaded_models(url)]
    # Ollama reports "qwen3:8b"; a bare "qwen3" means the ":latest" tag.
    wanted = model.strip()
    wanted = wanted if ":" in wanted else f"{wanted}:latest"
    present = any(name == wanted for name in names)
    return present, names


def record(label: str, model: str, resident: bool, names: list[str], log: Path) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as out:
        out.write(json.dumps({
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "label": label,
            "model": model,
            "resident": resident,
            "loaded": names,
        }) + "\n")


def summarise(log: Path) -> int:
    rows: list[dict] = []
    if log.is_file():
        for line in log.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if not rows:
        print("No AI step was recorded yet, so there is nothing to report about model reloads.")
        return 0
    cold = [row for row in rows if not row["resident"]]
    print(f"Model residency: {len(rows) - len(cold)} of {len(rows)} AI steps ran on weights "
          f"already in RAM.")
    for row in rows:
        state = "resident" if row["resident"] else "COLD LOAD"
        print(f"  - {row['label']}: {row['model']} -> {state}"
              + (f" (in memory: {', '.join(row['loaded'])})" if row["loaded"] else ""))
    if cold:
        print("The steps above had to load the model first: that is where the minutes go.")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as out:
            out.write("## Model residency\n")
            out.write(f"- {len(rows) - len(cold)} of {len(rows)} AI steps reused the model "
                      "already loaded in memory.\n")
            for row in rows:
                out.write(f"- {row['label']}: `{row['model']}` - "
                          f"{'resident' if row['resident'] else 'cold load'}\n")
    return 1 if cold else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="check one step and record it")
    parser.add_argument("--summary", action="store_true", help="print what the run recorded")
    parser.add_argument("--model", default=os.environ.get("AI_MODEL", ""))
    parser.add_argument("--label", default="AI step")
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--url", default=DEFAULT_URL)
    args = parser.parse_args()

    if args.summary or not args.check:
        return summarise(args.log)
    if not args.model:
        print("No model given, so residency cannot be checked.", file=sys.stderr)
        return 0
    try:
        resident, names = is_resident(args.model, args.url)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"Could not ask Ollama which models are loaded ({type(exc).__name__}); "
              "continuing without the residency check.", file=sys.stderr)
        return 0
    record(args.label, args.model, resident, names, args.log)
    if resident:
        print(f"[{args.label}] {args.model} is already in memory: no reload before this step.")
    else:
        print(f"[{args.label}] {args.model} is not in memory, so this step will pay for one "
              f"load (currently loaded: {', '.join(names) or 'nothing'}).")
        # A workflow command has to start its own line to be picked up by Actions.
        print(f"::warning title=Model reload::{args.model} was not resident before "
              f"{args.label}; the run reloaded it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
