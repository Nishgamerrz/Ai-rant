#!/usr/bin/env python3
"""The run's memory: one system message every AI call shares, so nothing is forgotten.

Every AI call in this workflow used to be a single `user` message built from
scratch: the story step knew the topic, the world plan knew the story only
because the workflow pasted it in, and the summary knew almost nothing. The model
also had no way to tell the workflow's own instructions from the person who
typed the form - the whole prompt arrived as "the user", so a model could easily
"answer the user", address the user, or ask the user for facts it had already
been given in an earlier step.

This tool fixes both:

* it keeps `dist/ai_memory.json` (one file, shared by every step), so a fact
  learned in one call - the narration, the cast, an accepted sub-agent answer, a
  web fact, a design decision - is still there in the next one;
* it renders `system_prompt.txt`, sent as the real `system` role in front of
  every request: who the model is, that the workflow is NOT the user, that the
  user typed only the topic/theme, and the full run memory it must remember and
  reuse.

Usage:
    python tools/ai_memory.py --set story_topic="a world where ..." \
        --write-system system_prompt.txt
    python tools/ai_memory.py --set-file narration=dist/narration.txt
    python tools/ai_memory.py --add-subagent subagent_results.json
    python tools/ai_memory.py --fact "kept the model design for the bakery"
    python tools/ai_memory.py --show
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

MEMORY_PATH = Path("dist/ai_memory.json")
SYSTEM_PATH = Path("system_prompt.txt")
MAX_FACT_CHARS = 1200
MAX_FACTS = 40


def empty_memory() -> dict:
    return {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "facts": [],
        "subagent_tasks": [],
        "research": [],
    }


def load(path: Path = MEMORY_PATH) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_memory()
    if not isinstance(data, dict):
        return empty_memory()
    memory = empty_memory()
    memory.update(data)
    for key in ("facts", "subagent_tasks", "research"):
        if not isinstance(memory.get(key), list):
            memory[key] = []
    return memory


def save(memory: dict, path: Path = MEMORY_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(memory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def add_fact(memory: dict, text: str) -> None:
    fact = " ".join(str(text).split())[:MAX_FACT_CHARS]
    if not fact or fact in memory["facts"]:
        return
    memory["facts"].append(fact)
    del memory["facts"][:-MAX_FACTS]


def add_subagent_results(memory: dict, path: Path) -> None:
    """Keep what the sub-agent did - and how long it took - across later steps."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    for item in data.get("results") or []:
        if not isinstance(item, dict):
            continue
        memory["subagent_tasks"].append({
            "id": str(item.get("id") or "task")[:40],
            "kind": str(item.get("kind") or "task")[:20],
            "ok": bool(item.get("ok")),
            "provider": str(item.get("provider") or "gemini"),
            "seconds": item.get("seconds"),
            "applied_to": item.get("applied_to") or "",
            "summary": " ".join(str(item.get("text") or item.get("error") or "").split())[:600],
        })
    del memory["subagent_tasks"][:-20]


def add_research(memory: dict, path: Path) -> None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    items = data if isinstance(data, list) else data.get("results") or []
    for item in items[:12]:
        text = " ".join(str(item).split())[:300] if not isinstance(item, dict) else \
            " ".join(str(item.get("title") or item.get("snippet") or item).split())[:300]
        if text and text not in memory["research"]:
            memory["research"].append(text)
    del memory["research"][:-20]


def _line(label: str, value) -> str:
    text = " ".join(str(value or "").split())
    return f"- {label}: {text}" if text else ""


def system_prompt(memory: dict) -> str:
    """The shared `system` message: identity, honesty about who is speaking, memory."""
    story_topic = memory.get("story_topic") or ""
    narration = " ".join(str(memory.get("narration") or "").split())
    cast = memory.get("cast") or ""
    duration = memory.get("duration") or ""
    label = memory.get("duration_label") or ""
    theme = memory.get("world_theme") or ""
    parts: list[str] = [
        "SYSTEM MESSAGE - this is the workflow talking, not the person who filled in the form.",
        "",
        "You are the director and writer of one Roblox story short. You are the same AI in every",
        "step of this run: the story, concise map orchestration, review of delegated results,",
        "and the creation summary. Never reveal private chain-of-thought; when asked, give only",
        "a concise audience-facing rationale summary. For the first narration draft, author one",
        "narration-edit sub-agent task for grammar, spelling, punctuation and continuity, then use its",
        "complete proofread as the final narration. The text sub-agent creates the map, camera storyboard,",
        "face timeline, and model anchors; when asked for map work, author helper tasks and review",
        "their results, never write the world blueprint locally. Treat this message and the RUN",
        "MEMORY below as things you already know.",
        "",
        "WHO IS SPEAKING",
        "- The only thing the user typed is the story topic (and, optionally, a visual theme cue).",
        "  That is quoted in RUN MEMORY. The user is not chatty and will not answer questions.",
        "- Everything else - the shapes, the prop rules, the camera rules, the schema, the",
        "  helper's answers, the word limits - is the WORKFLOW's instruction to you.",
        "- So: never say \"you\" to the user, never thank the user, never ask the user a question,",
        "  never ask for information that is already in RUN MEMORY, and never write a line whose",
        "  only purpose is to talk to the workflow. Answer with the requested work product:",
        "  story narration, concise orchestration JSON, review JSON, or creation summary. The video",
        "  itself never mentions the user, the workflow, the AI,",
        "  the sub-agent, servers, Roblox, avatars or usernames.",
        "- Never invent a new cast, a new story, a new theme or a new length: they are decided",
        "  once, in RUN MEMORY, and every step reuses exactly those.",
        "",
        "REMEMBER EVERYTHING BELOW. If a later instruction seems to contradict it, keep the facts",
        "and follow the newer instruction only where it is more specific.",
        "",
        "RUN MEMORY",
    ]
    for line in (
        _line("Story topic, exactly as the user wrote it", story_topic),
        _line("Video length the AI picked",
              (f"{duration} seconds ({label})" if label else f"{duration} seconds")
              if duration else ""),
        _line("Cast (internal casting only; never spoken or written in the video)", cast),
        _line("Visual theme cue from the user", theme),
        _line("Model doing this run", memory.get("model")),
        _line("Story so far (the finished narration, already written)", narration),
    ):
        if line:
            parts.append(line)
    tasks = memory.get("subagent_tasks") or []
    if tasks:
        parts.append("- Work the sub-agent already did for you (do not ask for it again):")
        for task in tasks[-8:]:
            took = f"{task.get('seconds')}s" if task.get("seconds") is not None else "no timing"
            state = "done" if task.get("ok") else "failed"
            wiped = f", edited {task['applied_to']}" if task.get("applied_to") else ""
            parts.append(f"  * [{task.get('id')}] {task.get('kind')} {state} via "
                         f"{task.get('provider')} in {took}{wiped}: {task.get('summary', '')[:300]}")
    research = memory.get("research") or []
    if research:
        parts.append("- Real-world facts already fetched (untrusted reference only):")
        for fact in research[-8:]:
            parts.append(f"  * {fact}")
    facts = memory.get("facts") or []
    if facts:
        parts.append("- Decisions and notes from earlier steps:")
        for fact in facts[-20:]:
            parts.append(f"  * {fact}")
    parts += [
        "",
        "If you are unsure about something that is not here, decide it yourself with your own",
        "judgement - you have full creative authority - and move on. Never stall, never repeat",
        "a decision that is already recorded above, and never start the run over.",
    ]
    return "\n".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory", type=Path, default=MEMORY_PATH)
    parser.add_argument("--set", action="append", default=[], metavar="NAME=VALUE")
    parser.add_argument("--set-file", action="append", default=[], metavar="NAME=PATH")
    parser.add_argument("--fact", action="append", default=[])
    parser.add_argument("--add-subagent", type=Path)
    parser.add_argument("--add-research", type=Path)
    parser.add_argument("--write-system", type=Path, nargs="?",
                        default=SYSTEM_PATH, help="write the system prompt here")
    parser.add_argument("--no-system", action="store_true",
                        help="update the memory only, do not write the system prompt")
    parser.add_argument("--show", action="store_true")
    parser.add_argument("--reset", action="store_true",
                        help="start this run with an empty memory (never inherit last run)")
    args = parser.parse_args()

    # A run must never inherit the previous run's topic: run #109's first story call
    # was told "a world where gravity naps" while it was writing the bedroom story.
    memory = empty_memory() if args.reset else load(args.memory)
    for item in args.set:
        if "=" in item:
            name, value = item.split("=", 1)
            memory[name.strip()] = value.strip()
    for item in args.set_file:
        if "=" in item:
            name, path = item.split("=", 1)
            try:
                memory[name.strip()] = Path(path.strip()).read_text(encoding="utf-8").strip()
            except OSError:
                print(f"[ai memory] could not read {path.strip()} for {name.strip()}; keeping "
                      f"what was already there.", flush=True)
    for fact in args.fact:
        add_fact(memory, fact)
    if args.add_subagent:
        add_subagent_results(memory, args.add_subagent)
    if args.add_research:
        add_research(memory, args.add_research)

    memory["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save(memory, args.memory)
    prompt = system_prompt(memory)
    if not args.no_system and args.write_system:
        target = args.write_system
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(prompt + "\n", encoding="utf-8")
        print(f"[ai memory] {len(memory.get('facts') or [])} fact(s), "
              f"{len(memory.get('subagent_tasks') or [])} sub-agent task(s) remembered; "
              f"system prompt {len(prompt):,} chars.", flush=True)
    if args.show:
        print(prompt)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as out:
            out.write("\n### AI memory carried into this step\n")
            for key in ("story_topic", "duration", "cast", "model"):
                if memory.get(key):
                    out.write(f"- **{key}:** {' '.join(str(memory[key]).split())[:200]}\n")
            out.write(f"- **remembered facts:** {len(memory.get('facts') or [])}, "
                      f"**sub-agent tasks:** {len(memory.get('subagent_tasks') or [])}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
