#!/usr/bin/env python3
"""Validate AI-authored narration delegation and chain creation into proofreading.

The selected local model authors both narration sub-agent requests in its first
response. The first helper call creatively develops the draft; the second helper
call receives the exact creation result and proofreads that complete text. No
request is invented when the model omits or mis-shapes either task.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ai_activity import redact_secrets  # noqa: E402
from console_style import paint  # noqa: E402

MAX_TASK_INPUT_CHARS = 12000
MAX_TASK_INSTRUCTION_CHARS = 1200
_PRIVATE_MARKERS = (
    "chain of thought", "chain-of-thought", "private reasoning", "hidden reasoning",
    "internal monologue", "scratchpad", "let me think step by step",
    "here is my reasoning", "here's my reasoning", "my thought process",
)


class DelegationError(ValueError):
    """Raised when a model-authored narration delegation is incomplete or unsafe."""


def _load_json(path: Path, label: str):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DelegationError(f"cannot read {label} as JSON ({type(exc).__name__})") from exc


def _local_reply(path: Path) -> dict:
    payload = _load_json(path, "the selected model's narration response")
    if not isinstance(payload, dict):
        raise DelegationError("the selected model's narration response must be an object")
    message = payload.get("message")
    raw = message.get("content") if isinstance(message, dict) else None
    if not isinstance(raw, str) or not raw.strip():
        raw = payload.get("response")
    if isinstance(raw, dict):
        reply = raw
    elif isinstance(raw, str):
        try:
            reply = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise DelegationError("the selected model did not return valid narration JSON") from exc
    else:
        raise DelegationError("the selected model did not return narration JSON")
    if not isinstance(reply, dict):
        raise DelegationError("the selected model's narration JSON must be an object")
    return reply


def _validate_public_rationale(value) -> str:
    if not isinstance(value, str):
        raise DelegationError("the selected model must return public_rationale as a string")
    rationale = " ".join(value.split()).strip()
    rationale = redact_secrets(rationale)
    lowered = rationale.casefold()
    if not rationale or len(rationale) > 320:
        raise DelegationError("the selected model must return a concise public_rationale (1-320 characters)")
    if rationale.startswith(("{", "[")) or any(marker in lowered for marker in _PRIVATE_MARKERS):
        raise DelegationError("the narration response's public_rationale is not a safe public summary")
    return rationale


def _validated_task(candidate, *, task_id: str, kind: str, topic: str,
                    narration: str) -> dict:
    if not isinstance(candidate, dict):
        raise DelegationError(f"required narration sub-agent task {task_id!r} is not an object")
    if any(not isinstance(candidate.get(key), str)
           for key in ("id", "kind", "topic", "instruction", "input")):
        raise DelegationError(f"required narration task {task_id!r} must use string fields")
    actual_id = candidate["id"].strip()
    actual_kind = candidate["kind"].strip().lower()
    actual_topic = candidate["topic"].strip().lower()
    instruction = candidate["instruction"].strip()
    task_input = candidate["input"].strip()
    expected_input = narration if kind == "write" else "USE_T1_CREATION_RESULT"
    input_is_valid = (narration in task_input if kind == "write"
                      else task_input == expected_input)
    if (actual_id != task_id or actual_kind != kind or actual_topic != topic
            or not instruction or len(instruction) > MAX_TASK_INSTRUCTION_CHARS
            or not input_is_valid):
        detail = ("include the complete first-draft narration verbatim" if kind == "write"
                  else f"use the exact {expected_input!r} marker")
        raise DelegationError(
            f"required narration task {task_id!r} must be kind={kind!r}, topic={topic!r}, "
            f"have a non-empty bounded instruction, and {detail}"
        )
    if len(task_input) > MAX_TASK_INPUT_CHARS:
        raise DelegationError(f"narration task {task_id!r} exceeds the helper's input limit")
    lowered_instruction = instruction.casefold()
    if kind == "write" and not any(word in lowered_instruction for word in
                                    ("create", "write", "rewrite", "develop", "craft", "shape")):
        raise DelegationError("the narration-creation task must ask the sub-agent to create or develop the story")
    if kind == "edit" and not any(word in lowered_instruction for word in
                                   ("proofread", "grammar", "correct", "edit")):
        raise DelegationError("the narration-edit task must explicitly request proofreading or grammar correction")
    return {"id": actual_id, "kind": actual_kind, "topic": actual_topic,
            "instruction": instruction, "input": task_input}


def extract_tasks(response_path: Path, creation_request_path: Path,
                  proofread_template_path: Path, draft_path: Path,
                  duration_seconds: str) -> dict:
    """Validate the local model's two tasks and write the creation request/template."""
    reply = _local_reply(response_path)
    if not isinstance(reply.get("narration"), str):
        raise DelegationError("the selected model must return its first narration draft as a string")
    narration = reply["narration"].strip()
    if not narration:
        raise DelegationError("the selected model's first narration draft is empty")
    rationale = _validate_public_rationale(reply.get("public_rationale"))
    candidates = reply.get("subagent_tasks")
    if not isinstance(candidates, list) or len(candidates) != 2:
        raise DelegationError(
            "the selected model must author exactly two narration sub-agent tasks: "
            "t1 for creative story development and t2 for grammar proofreading"
        )
    by_id = {str(item.get("id") or "").strip(): item for item in candidates if isinstance(item, dict)}
    if len(by_id) != 2 or set(by_id) != {"t1", "t2"}:
        raise DelegationError("the narration sub-agent tasks must have the distinct IDs 't1' and 't2'")
    creation = _validated_task(by_id["t1"], task_id="t1", kind="write",
                               topic="narration", narration=narration)
    proofread = _validated_task(by_id["t2"], task_id="t2", kind="edit",
                                topic="narration", narration=narration)

    context = (f"Create and proofread the narration for a {duration_seconds}-second "
               "vertical story video. Preserve the premise and events while keeping "
               "the complete script natural to speak.")
    creation_request_path.parent.mkdir(parents=True, exist_ok=True)
    creation_request_path.write_text(json.dumps({"context": context, "tasks": [creation]},
                                               ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8")
    proofread_template_path.parent.mkdir(parents=True, exist_ok=True)
    proofread_template_path.write_text(json.dumps({"context": context,
                                                    "public_rationale": rationale,
                                                    "tasks": [proofread]},
                                                   ensure_ascii=False, indent=2) + "\n",
                                       encoding="utf-8")
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    draft_path.write_text(narration + "\n", encoding="utf-8")
    return {"narration": narration, "public_rationale": rationale,
            "creation_task": creation, "proofread_task": proofread}


def _complete_result(path: Path, *, task_id: str, kind: str) -> str:
    payload = _load_json(path, f"the {kind} sub-agent result")
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list) or len(results) != 1 or not isinstance(results[0], dict):
        raise DelegationError(f"the narration {kind} sub-agent must return exactly one complete task")
    result = results[0]
    text = result.get("text")
    if (result.get("id") != task_id or result.get("kind") != kind
            or result.get("ok") is not True or result.get("status") != "complete"
            or not isinstance(text, str) or not text.strip()):
        raise DelegationError(f"the narration {kind} sub-agent returned no complete {task_id} result")
    if len(text) > MAX_TASK_INPUT_CHARS:
        raise DelegationError(f"the narration {kind} result exceeds the helper's input limit")
    if text.strip().startswith("```") or text.strip().endswith("```"):
        raise DelegationError(f"the narration {kind} result must be plain text without markdown fences")
    return text


def prepare_proofread_request(template_path: Path, creation_result_path: Path,
                              output_path: Path, created_draft_path: Path) -> str:
    """Pass the complete creation result verbatim to the AI-authored proofreading task."""
    template = _load_json(template_path, "the AI-authored proofreading task")
    if not isinstance(template, dict):
        raise DelegationError("the AI-authored proofreading task must be an object")
    tasks = template.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 1 or not isinstance(tasks[0], dict):
        raise DelegationError("the AI-authored proofreading template must contain exactly one task")
    task = tasks[0]
    if (task.get("id") != "t2" or task.get("kind") != "edit"
            or task.get("topic") != "narration" or not str(task.get("instruction") or "").strip()):
        raise DelegationError("the proofreading template must preserve the model-authored t2 narration edit")
    created = _complete_result(creation_result_path, task_id="t1", kind="write")
    task["input"] = created
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(template, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    created_draft_path.parent.mkdir(parents=True, exist_ok=True)
    created_draft_path.write_text(created, encoding="utf-8")
    return created


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    extract = subparsers.add_parser("extract", help="validate the local model's two AI-authored tasks")
    extract.add_argument("--response", required=True, type=Path)
    extract.add_argument("--creation-request", required=True, type=Path)
    extract.add_argument("--proofread-template", required=True, type=Path)
    extract.add_argument("--draft", required=True, type=Path)
    extract.add_argument("--duration-seconds", required=True)
    prepare = subparsers.add_parser("prepare-proofread", help="feed the creation result into its proofread task")
    prepare.add_argument("--template", required=True, type=Path)
    prepare.add_argument("--creation-result", required=True, type=Path)
    prepare.add_argument("--output", required=True, type=Path)
    prepare.add_argument("--created-draft", required=True, type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "extract":
            result = extract_tasks(args.response, args.creation_request,
                                   args.proofread_template, args.draft,
                                   args.duration_seconds)
            print(paint("The selected model authored one required narration-creation task "
                        "and one narration-proofreading task.", "success"), flush=True)
            print(paint(f"Public rationale: {result['public_rationale']}", "plan"), flush=True)
        else:
            created = prepare_proofread_request(args.template, args.creation_result,
                                                args.output, args.created_draft)
            print(paint(f"Prepared the AI-authored t2 proofread with the exact narration-creation result ({len(created)} characters).",
                        "tool"), flush=True)
    except DelegationError as exc:
        print(f"Narration delegation error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
