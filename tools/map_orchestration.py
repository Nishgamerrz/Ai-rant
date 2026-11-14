#!/usr/bin/env python3
"""Keep the local model in the director role while sub-agents build the map.

The selected Ollama model returns a compact orchestration envelope (brief,
model-anchor names, and its own map/camera plus models task calls). The helper
provider writes the actual map and model anchors. The selected Ollama model then
reviews a compact digest and accepts the helper task IDs; it never has to emit or
repair the full map JSON.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from console_style import paint  # noqa: E402
from ai_activity import redact_secrets  # noqa: E402
from map_delegation import MAP_CAMERA_TOPICS, extract_plan, missing_required_topics  # noqa: E402

TASK_IDS = ("t1", "t2")
VALID_TIMES = {"dawn", "day", "sunset", "night"}
_PRIVATE_RATIONALE_MARKERS = (
    "chain of thought", "chain-of-thought", "private reasoning", "hidden reasoning",
    "internal monologue", "scratchpad", "let me think step by step",
    "here is my reasoning", "here's my reasoning", "my thought process",
)


def orchestration_schema() -> dict:
    """JSON schema for the small, first local-model orchestration response."""
    task = {
        "type": "object",
        "properties": {
            "id": {"type": "string", "enum": list(TASK_IDS)},
            "kind": {"type": "string", "enum": ["write"]},
            "topic": {"type": "string",
                      "enum": ["map", "cameras", "faces", "models"]},
            "instruction": {"type": "string", "minLength": 20, "maxLength": 1200},
            "input": {"type": "string", "maxLength": 3000},
            "use_tools": {"type": "boolean",
                           "description": "Optional; true gives the helper access to model-authored shared tools."},
        },
        "required": ["id", "kind", "topic", "instruction"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "public_rationale": {"type": "string", "maxLength": 320},
            "design_brief": {"type": "string", "maxLength": 700},
            "model_anchor_names": {
                "type": "array",
                "items": {"type": "string", "minLength": 2, "maxLength": 48},
                "minItems": 1,
                "maxItems": 2,
            },
            "search_queries": {
                "type": "array",
                "items": {"type": "string", "maxLength": 120},
                "maxItems": 3,
            },
            "subagent_tasks": {
                "type": "array", "items": task, "minItems": 2, "maxItems": 2,
            },
        },
        "required": ["public_rationale", "design_brief", "model_anchor_names",
                     "search_queries", "subagent_tasks"],
        "additionalProperties": False,
    }


def review_schema() -> dict:
    """Small result schema for the selected model's review/acceptance call."""
    return {
        "type": "object",
        "properties": {
            "accepted": {"type": "array", "items": {"type": "string", "enum": list(TASK_IDS)},
                         "maxItems": len(TASK_IDS)},
            "note": {"type": "string", "maxLength": 320},
            "changes_needed": {"type": "boolean"},
            "revision_instruction": {"type": "string", "maxLength": 500},
        },
        "required": ["accepted", "note", "changes_needed", "revision_instruction"],
        "additionalProperties": False,
    }


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read valid JSON from {path}: {exc}") from exc


def _orchestration(value: Any) -> dict:
    plan = extract_plan(value)
    if not isinstance(plan, dict):
        raise ValueError("the selected model did not return an orchestration JSON object")
    return plan


def _validated_tasks(plan: dict) -> list[dict]:
    raw_rationale = plan.get("public_rationale")
    if not isinstance(raw_rationale, str):
        raise ValueError("the first response must include a concise public rationale (max 320 chars)")
    rationale = redact_secrets(" ".join(raw_rationale.split())).strip()
    lowered = rationale.casefold()
    if (not rationale or len(rationale) > 320 or rationale.startswith(("{", "["))
            or any(marker in lowered for marker in _PRIVATE_RATIONALE_MARKERS)):
        raise ValueError("the first response must include a concise safe public rationale (max 320 chars)")
    plan["public_rationale"] = rationale
    tasks = plan.get("subagent_tasks")
    if not isinstance(tasks, list) or len(tasks) != 2:
        raise ValueError("the first response must author exactly two sub-agent calls")
    missing = missing_required_topics({"subagent_tasks": tasks})
    if missing:
        raise ValueError("the first response must author " + " and ".join(missing))

    ids: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict):
            raise ValueError("each first-response sub-agent call must be a JSON object")
        task_id = str(task.get("id") or "").strip()
        if task_id not in TASK_IDS or task_id in ids:
            raise ValueError("the two first-response sub-agent calls need distinct IDs t1 and t2")
        ids.add(task_id)
        if str(task.get("kind") or "").strip().lower() != "write":
            raise ValueError("map and models sub-agent calls must use kind 'write'")
        if "use_tools" in task and not isinstance(task["use_tools"], bool):
            raise ValueError(f"sub-agent call {task_id} use_tools must be a JSON boolean")
        if not str(task.get("instruction") or "").strip():
            raise ValueError(f"sub-agent call {task_id} has no instruction")
        if task.get("apply_to"):
            raise ValueError("first-response map tasks may not choose files to overwrite")
    if ids != set(TASK_IDS):
        raise ValueError("the two first-response sub-agent calls must use IDs t1 and t2")

    names = plan.get("model_anchor_names")
    if not isinstance(names, list) or not 1 <= len(names) <= 2:
        raise ValueError("the orchestration response must name one or two model anchors")
    clean_names = [str(name).strip() for name in names]
    if any(len(name) < 2 or len(name) > 48 for name in clean_names):
        raise ValueError("model anchor names must be between 2 and 48 characters")
    if len({name.casefold() for name in clean_names}) != len(clean_names):
        raise ValueError("model anchor names must be unique")
    return tasks


def _decode_answer(text: str, *, label: str) -> Any:
    """Parse a sub-agent's JSON-only answer, tolerating a single markdown fence."""
    candidate = str(text or "").strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", candidate,
                          flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        candidate = fenced.group(1).strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for index, char in enumerate(candidate):
            if char not in "[{":
                continue
            try:
                value, _ = decoder.raw_decode(candidate[index:])
                return value
            except json.JSONDecodeError:
                continue
    raise ValueError(f"the {label} sub-agent answer was not valid JSON")


def _successful_result(results: dict, task_id: str, topic: str) -> dict:
    entries = results.get("results")
    if not isinstance(entries, list):
        raise ValueError("the sub-agent returned no results array")
    result = next((entry for entry in entries
                   if isinstance(entry, dict) and str(entry.get("id")) == task_id), None)
    if result is None:
        raise ValueError(f"the sub-agent did not return required task {task_id} ({topic})")
    if result.get("ok") is not True:
        reason = " ".join(str(result.get("error") or result.get("status") or "failed").split())[:240]
        raise ValueError(f"sub-agent task {task_id} ({topic}) did not complete: {reason}")
    return result


def build_subagent_request(response_path: Path, context_path: Path, output_path: Path) -> dict:
    """Forward only the two task calls in the selected model's first response."""
    plan = _orchestration(_read_json(response_path))
    tasks = _validated_tasks(plan)
    context = context_path.read_text(encoding="utf-8").strip()
    brief = str(plan.get("design_brief") or "").strip()
    names = [str(name).strip() for name in plan["model_anchor_names"]]
    extras = []
    rationale = str(plan.get("public_rationale") or "").strip()
    if rationale:
        extras.append("Selected local director's public rationale:\n" + rationale)
    if brief:
        extras.append("Selected local director's concise brief:\n" + brief)
    extras.append("Model-anchor names assigned to the AI-authored models task: "
                  + ", ".join(names))
    request = {"context": "\n\n".join(part for part in (context, *extras) if part),
               # These task objects are passed through unchanged. This tool never
               # invents a required call or replaces the local model's instructions.
               "tasks": tasks}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(request, ensure_ascii=False) + "\n", encoding="utf-8")
    return request


def assemble_plan(orchestration_path: Path, results_path: Path, output_path: Path) -> dict:
    """Combine the helper-authored map/camera JSON and model-authored prop anchors."""
    orchestration = _orchestration(_read_json(orchestration_path))
    tasks = _validated_tasks(orchestration)
    task_by_topic: dict[str, dict] = {}
    for task in tasks:
        topic = str(task.get("topic") or "").strip().lower()
        if topic in MAP_CAMERA_TOPICS:
            if "map" in task_by_topic:
                raise ValueError("the first response authored more than one map/camera task")
            task_by_topic["map"] = task
        elif topic == "models":
            task_by_topic["models"] = task
    if set(task_by_topic) != {"map", "models"}:
        raise ValueError("the first response must author one map/camera task and one models task")

    results = _read_json(results_path)
    map_result = _successful_result(results, task_by_topic["map"]["id"], "map/camera")
    models_result = _successful_result(results, task_by_topic["models"]["id"], "models")
    map_plan = _decode_answer(str(map_result.get("text") or ""), label="map/camera")
    models_answer = _decode_answer(str(models_result.get("text") or ""), label="models")
    if not isinstance(map_plan, dict):
        raise ValueError("the map/camera sub-agent must return a JSON object")
    if not isinstance(models_answer, dict) or not isinstance(models_answer.get("props"), list):
        raise ValueError("the models sub-agent must return a JSON object with a props array")

    map_props = map_plan.get("props")
    model_props = models_answer["props"]
    expected_names = [str(name).strip() for name in orchestration["model_anchor_names"]]
    if not isinstance(map_props, list) or len(map_props) < 8:
        raise ValueError("the map/camera sub-agent must create at least 8 map anchor props")
    if len(model_props) != len(expected_names):
        raise ValueError("the models sub-agent must return exactly one prop for each assigned model anchor")
    if any(not isinstance(prop, dict) for prop in [*map_props, *model_props]):
        raise ValueError("map and model props must be JSON objects")

    map_names = {str(prop.get("name") or "").strip().casefold() for prop in map_props}
    model_names = [str(prop.get("name") or "").strip() for prop in model_props]
    if any(not name for name in model_names):
        raise ValueError("every models-task prop needs a name")
    if {name.casefold() for name in model_names} != {name.casefold() for name in expected_names}:
        raise ValueError("the models sub-agent did not return the exact anchor names assigned by the local director")
    if any(name.casefold() in map_names for name in model_names):
        raise ValueError("a models-task anchor duplicates a map/camera-task prop name")
    combined_names = [*map_names, *(name.casefold() for name in model_names)]
    if len(combined_names) != len(set(combined_names)):
        raise ValueError("the combined map contains duplicate prop names")

    for key, minimum in (("camera_shots", 6), ("face_expressions", 6)):
        if not isinstance(map_plan.get(key), list) or len(map_plan[key]) < minimum:
            raise ValueError(f"the map/camera sub-agent must provide at least {minimum} {key}")
    if not isinstance(map_plan.get("character_placements"), list):
        raise ValueError("the map/camera sub-agent must return character_placements")
    if not str(map_plan.get("name") or "").strip() or not str(map_plan.get("theme") or "").strip():
        raise ValueError("the map/camera sub-agent must return a world name and a specific theme")
    if str(map_plan.get("time_of_day") or "").strip().lower() not in VALID_TIMES:
        raise ValueError("the map/camera sub-agent must choose dawn, day, sunset, or night")

    plan = dict(map_plan)
    plan["props"] = [*map_props, *model_props]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(paint(f"Combined the delegated map, camera and {len(model_props)} model anchor(s).",
                "success"), flush=True)
    return plan


def _review_digest(plan: dict) -> dict:
    """Give the local director enough structure to review without re-authoring it."""
    props = []
    for prop in plan.get("props", [])[:24]:
        if not isinstance(prop, dict):
            continue
        props.append({key: prop.get(key) for key in
                      ("name", "model", "shape", "material", "position", "size", "color")
                      if key in prop})
    shots = []
    for shot in plan.get("camera_shots", [])[:48]:
        if not isinstance(shot, dict):
            continue
        shots.append({key: shot.get(key) for key in
                      ("time", "focus_username", "transition", "framing", "face_distance",
                       "time_of_day") if key in shot})
    faces = []
    for beat in plan.get("face_expressions", [])[:24]:
        if not isinstance(beat, dict):
            continue
        faces.append({key: beat.get(key) for key in
                      ("time", "username", "expression", "intensity") if key in beat})
    return {
        "name": plan.get("name"), "theme": plan.get("theme"),
        "time_of_day": plan.get("time_of_day"),
        "ground_material": plan.get("ground_material"),
        "character_placements": plan.get("character_placements"),
        "props": props, "camera_shots": shots, "face_expressions": faces,
    }


def build_review_request(orchestration_path: Path, plan_path: Path, results_path: Path,
                         context_path: Path, system_path: Path, model: str,
                         thinking: bool, num_ctx: int, output_path: Path) -> dict:
    """Create a bounded, JSON-only acceptance call for the same selected model."""
    orchestration = _orchestration(_read_json(orchestration_path))
    tasks = _validated_tasks(orchestration)
    plan = _read_json(plan_path)
    results = _read_json(results_path)
    completed = []
    for task in tasks:
        result = _successful_result(results, str(task["id"]), str(task.get("topic") or "task"))
        completed.append({"id": task["id"], "topic": task.get("topic"),
                          "provider": result.get("provider", ""),
                          "seconds": result.get("seconds")})
    context = context_path.read_text(encoding="utf-8").strip()
    prompt = (
        "You are the selected local Ollama model acting as director. The text sub-agent "
        "created the map, camera storyboard, face timeline, and the separately delegated "
        "model anchors. Review the submitted result; do NOT create, rewrite, repair, or "
        "repeat any map JSON. Check story/theme fit, indoor-versus-outdoor scene mode, "
        "cast placements, usable camera coverage, face timing, and that both delegated "
        "tasks are represented. Accept both task IDs when there is no blocking defect. "
        "If a blocking defect remains, set changes_needed true and describe it in one "
        "short revision_instruction; the workflow will stop rather than start a planning loop.\n\n"
        "Run context:\n" + context[:9000] + "\n\n"
        "Completed helper calls:\n" + json.dumps(completed, ensure_ascii=False) + "\n\n"
        "Delegated plan digest:\n" + json.dumps(_review_digest(plan), ensure_ascii=False) + "\n\n"
        "Return only the required JSON object: {\"accepted\":[\"t1\",\"t2\"],"
        "\"note\":\"brief review\",\"changes_needed\":false,"
        "\"revision_instruction\":\"\"}."
    )
    try:
        system = system_path.read_text(encoding="utf-8").strip()
    except OSError:
        system = ""
    messages = ([{"role": "system", "content": system}] if system else [])
    messages.append({"role": "user", "content": prompt})
    request = {
        "model": model,
        "messages": messages,
        "format": review_schema(),
        "think": bool(thinking),
        "stream": False,
        "keep_alive": "60m",
        "options": {"temperature": 0.2, "num_ctx": int(num_ctx), "num_predict": 420},
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(request, ensure_ascii=False) + "\n", encoding="utf-8")
    return request


def accept_review(orchestration_path: Path, review_path: Path, plan_path: Path) -> dict:
    """Require a positive review of both original, AI-authored calls."""
    orchestration = _orchestration(_read_json(orchestration_path))
    tasks = _validated_tasks(orchestration)
    review = extract_plan(_read_json(review_path))
    if not isinstance(review, dict):
        raise ValueError("the selected local model did not return a review JSON object")
    accepted = review.get("accepted")
    accepted = [str(item).strip() for item in accepted] if isinstance(accepted, list) else []
    note = " ".join(str(review.get("note") or "").split())[:320]
    if review.get("changes_needed") is True:
        detail = " ".join(str(review.get("revision_instruction") or note or "").split())[:320]
        raise ValueError("the selected local model did not accept the sub-agent plan: "
                         + (detail or "it requested changes")
                         + "; stopping without a local map rewrite or a repair loop")
    if review.get("changes_needed") is not False:
        raise ValueError("the selected local model did not explicitly approve the sub-agent plan; "
                         "refusing to ship an unreviewed map")
    required_ids = {str(task["id"]) for task in tasks}
    if len(accepted) != len(set(accepted)) or set(accepted) != required_ids:
        raise ValueError("the selected local model must explicitly accept both sub-agent tasks "
                         "and no others; refusing to ship an unreviewed map")
    plan = _read_json(plan_path)
    if not isinstance(plan, dict):
        raise ValueError("the assembled map plan is not a JSON object")
    plan["subagent_review"] = {"accepted": accepted, "note": note}
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    print(paint("Selected local model accepted both sub-agent tasks"
                + (f": {note}" if note else "."), "success"), flush=True)
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    schema_parser = subparsers.add_parser("schema", help="write the compact orchestration JSON schema")
    schema_parser.add_argument("--output", required=True, type=Path)

    queries_parser = subparsers.add_parser("queries", help="print AI-authored web search queries")
    queries_parser.add_argument("--response", required=True, type=Path)

    prepare_parser = subparsers.add_parser("prepare", help="forward the AI-authored helper calls")
    prepare_parser.add_argument("--response", required=True, type=Path)
    prepare_parser.add_argument("--context", required=True, type=Path)
    prepare_parser.add_argument("--output", required=True, type=Path)

    assemble_parser = subparsers.add_parser("assemble", help="combine helper map and model outputs")
    assemble_parser.add_argument("--orchestration", required=True, type=Path)
    assemble_parser.add_argument("--results", required=True, type=Path)
    assemble_parser.add_argument("--output", required=True, type=Path)

    review_parser = subparsers.add_parser("review-request", help="write a short local-model acceptance request")
    review_parser.add_argument("--orchestration", required=True, type=Path)
    review_parser.add_argument("--plan", required=True, type=Path)
    review_parser.add_argument("--results", required=True, type=Path)
    review_parser.add_argument("--context", required=True, type=Path)
    review_parser.add_argument("--system", required=True, type=Path)
    review_parser.add_argument("--model", required=True)
    review_parser.add_argument("--think", default="true")
    review_parser.add_argument("--num-ctx", type=int, required=True)
    review_parser.add_argument("--output", required=True, type=Path)

    accept_parser = subparsers.add_parser("accept", help="validate and record the local review")
    accept_parser.add_argument("--orchestration", required=True, type=Path)
    accept_parser.add_argument("--review", required=True, type=Path)
    accept_parser.add_argument("--plan", required=True, type=Path)

    args = parser.parse_args()
    try:
        if args.command == "schema":
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(orchestration_schema()) + "\n", encoding="utf-8")
            print(paint(f"Wrote bounded map-orchestration schema to {args.output}", "plan"),
                  flush=True)
        elif args.command == "queries":
            plan = _orchestration(_read_json(args.response))
            _validated_tasks(plan)
            for query in plan.get("search_queries") or []:
                query = " ".join(str(query).split())[:120]
                if query:
                    print(query)
        elif args.command == "prepare":
            request = build_subagent_request(args.response, args.context, args.output)
            print(paint(f"Forwarded the {len(request['tasks'])} AI-authored map and models calls unchanged.",
                        "tool"), flush=True)
        elif args.command == "assemble":
            assemble_plan(args.orchestration, args.results, args.output)
        elif args.command == "review-request":
            thinking = str(args.think).strip().lower() in {"1", "true", "yes", "on"}
            build_review_request(args.orchestration, args.plan, args.results, args.context,
                                 args.system, args.model, thinking, args.num_ctx, args.output)
            print(paint(f"Prepared a compact review request for selected model {args.model}.",
                        "plan"), flush=True)
        elif args.command == "accept":
            accept_review(args.orchestration, args.review, args.plan)
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(paint(f"Map orchestration failed: {exc}", "error", stream=sys.stderr),
              file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
