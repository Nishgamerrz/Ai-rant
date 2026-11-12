#!/usr/bin/env python3
"""Require the map planner's original AI response to author its helper tasks.

The workflow deliberately validates the untouched Ollama response before it
builds or runs any Gemini request. A task synthesized by workflow code can never
satisfy this contract.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

MAP_CAMERA_TOPICS = {"map", "cameras", "faces"}


def _decode_json(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return None


def extract_plan(response: Any) -> dict:
    """Extract the AI's plan from an Ollama response or a direct plan object."""
    payload = _decode_json(response)
    if not isinstance(payload, dict):
        return {}

    message = payload.get("message")
    if isinstance(message, dict):
        plan = _decode_json(message.get("content"))
        if isinstance(plan, dict):
            return plan

    plan = _decode_json(payload.get("response"))
    if isinstance(plan, dict):
        return plan

    return payload


def authored_topics(response: Any) -> set[str]:
    """Return topics present in valid, AI-authored task objects in the response."""
    plan = extract_plan(response)
    tasks = plan.get("subagent_tasks")
    if not isinstance(tasks, list):
        return set()

    topics: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict):
            continue
        if not str(task.get("instruction") or "").strip():
            continue
        topic = str(task.get("topic") or "").strip().lower()
        if topic:
            topics.add(topic)
    return topics


def missing_required_topics(response: Any) -> list[str]:
    """Describe required calls missing from the untouched first plan response."""
    topics = authored_topics(response)
    missing = []
    if not topics.intersection(MAP_CAMERA_TOPICS):
        missing.append("a map/camera task (topic 'map', 'cameras', or 'faces')")
    if "models" not in topics:
        missing.append("a models task (topic 'models')")
    return missing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("response", type=Path,
                        help="untouched Ollama response JSON from the first map-plan call")
    args = parser.parse_args()
    try:
        response = json.loads(args.response.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Cannot validate AI-authored sub-agent tasks in {args.response}: {exc}")
        return 2

    missing = missing_required_topics(response)
    if missing:
        print("The AI's first map-plan response did not manually author "
              + " and ".join(missing) + ". The workflow will not inject or "
                "substitute its own task; no sub-agent delegation was run.")
        return 1

    topics = sorted(authored_topics(response))
    print("Validated AI-authored first-response sub-agent tasks: "
          + ", ".join(topics))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
