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
import math
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
        topic = str(task.get("topic") or "").strip().lower()
        if topic == "models" and task.get("use_tools") is not True:
            raise ValueError("the AI-authored models task must set use_tools:true for Roblox asset search and mesh inspection")
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


def _asset_name_in_query(name: str, query: str) -> bool:
    """Require an anchor-specific search, while ignoring common article words."""
    stop_words = {"a", "an", "the", "of", "for", "and", "to"}
    tokens = [token for token in re.findall(r"[a-z0-9]+", str(name).casefold())
              if token not in stop_words]
    query_tokens = set(re.findall(r"[a-z0-9]+", str(query).casefold()))
    return bool(tokens) and all(token in query_tokens for token in tokens)


def _paired_tool_events(result: dict) -> list[tuple[dict, dict | None]]:
    """Pair persisted model-authored calls with their safe, same-tool results."""
    calls = [call for call in result.get("tool_calls", []) if isinstance(call, dict)]
    results = [row for row in result.get("tool_results", []) if isinstance(row, dict)]
    used: set[int] = set()
    pairs = []
    for call in calls:
        tool = str(call.get("tool") or "")
        call_round = call.get("round")
        match_index = next((index for index, row in enumerate(results)
                            if index not in used and str(row.get("tool") or "") == tool
                            and (call_round is None or row.get("round") in (None, call_round))), None)
        if match_index is None:
            match_index = next((index for index, row in enumerate(results)
                                if index not in used and str(row.get("tool") or "") == tool), None)
        if match_index is None:
            pairs.append((call, None))
        else:
            used.add(match_index)
            pairs.append((call, results[match_index]))
    return pairs


def _valid_dimensions(value: Any) -> list[float] | None:
    if (not isinstance(value, list) or len(value) != 3
            or any(isinstance(number, bool) or not isinstance(number, (int, float))
                   or not math.isfinite(float(number)) or float(number) <= 0
                   for number in value)):
        return None
    return [round(float(number), 4) for number in value]


def _same_dimensions(left: Any, right: Any) -> bool:
    a, b = _valid_dimensions(left), _valid_dimensions(right)
    return bool(a and b and all(abs(x - y) <= 0.0001 for x, y in zip(a, b)))


def _validate_model_asset_tools(model_result: dict, asset_names: list[str]) -> list[tuple[dict, dict | None]]:
    """Require real authored searches and a measured, scaled placement when possible."""
    pairs = _paired_tool_events(model_result)
    for name in asset_names:
        matching = [(call, row) for call, row in pairs
                    if str(call.get("tool") or "") == "search_roblox_meshes"
                    and _asset_name_in_query(name, (call.get("arguments") or {}).get("query", ""))]
        if not matching:
            raise ValueError(f"models task did not author Roblox mesh search for {name!r}")
        if not any(row and isinstance(row.get("result"), dict)
                   and row["result"].get("ok") is True for _call, row in matching):
            raise ValueError(f"Roblox mesh search for {name!r} did not return usable search evidence")

    # A fetched mesh is only a reference. If it was downloaded successfully, the
    # agent must attempt an authored dimension inspection on that exact file.
    fetched_indices: list[tuple[int, str]] = []
    for index, (_call, row) in enumerate(pairs):
        if str((_call or {}).get("tool") or "") != "fetch_mesh_reference" or not row:
            continue
        outcome = row.get("result") or {}
        if outcome.get("ok") is True and outcome.get("path"):
            fetched_indices.append((index, str(outcome["path"])))
    for fetched_index, path in fetched_indices:
        inspected = any(
            str(call.get("tool") or "") == "inspect_mesh_dimensions"
            and str((call.get("arguments") or {}).get("path") or "") == path
            and row is not None and index > fetched_index
            for index, (call, row) in enumerate(pairs)
        )
        if not inspected:
            raise ValueError(f"downloaded mesh {path!r} was not inspected for dimensions")

    measurements = []
    for call, row in pairs:
        if str(call.get("tool") or "") != "inspect_mesh_dimensions" or not row:
            continue
        outcome = row.get("result") or {}
        dimensions = _valid_dimensions(outcome.get("dimensions_source_units"))
        if outcome.get("ok") is True and dimensions:
            measurements.append((call, row, dimensions))
    for _measurement_call, measurement_row, dimensions in measurements:
        measurement_round = measurement_row.get("round")
        placements = []
        for call, row in pairs:
            if str(call.get("tool") or "") != "plan_mesh_placement" or not row:
                continue
            args = call.get("arguments") or {}
            outcome = row.get("result") or {}
            scale = args.get("studs_per_unit")
            if (str(args.get("name") or "").casefold() in {name.casefold() for name in asset_names}
                    and _same_dimensions(args.get("dimensions"), dimensions)
                    and isinstance(scale, (int, float)) and not isinstance(scale, bool)
                    and math.isfinite(float(scale)) and float(scale) > 0
                    and outcome.get("ok") is True
                    and _same_dimensions(outcome.get("source_dimensions"), dimensions)):
                placements.append((call, row))
        if not placements:
            raise ValueError("measured mesh dimensions were not carried into a successful "
                             "explicitly scaled plan_mesh_placement call")
    return pairs


def _public_asset_row(value: Any) -> dict | None:
    if not isinstance(value, dict):
        return None
    row = {}
    for key in ("title", "asset_type", "creator", "snippet", "source"):
        if value.get(key):
            row[key] = " ".join(str(value[key]).split())[:420]
    asset_id = str(value.get("asset_id") or "").strip()
    if asset_id.isdigit():
        row["asset_id"] = asset_id
    url = str(value.get("url") or "").strip()
    if url.startswith("https://"):
        row["url"] = url[:500]
    return row if row.get("asset_id") or row.get("url") else None


def _asset_references(asset_names: list[str],
                      pairs: list[tuple[dict, dict | None]]) -> list[dict]:
    references = []
    for name in asset_names:
        searches, matches, downloads, measurements, placements = [], [], [], [], []
        for call, row in pairs:
            tool = str(call.get("tool") or "")
            arguments = call.get("arguments") or {}
            outcome = (row or {}).get("result") or {}
            if tool == "search_roblox_meshes" and _asset_name_in_query(name, arguments.get("query", "")):
                query = " ".join(str(arguments.get("query") or "").split())[:240]
                rows = [clean for clean in (_public_asset_row(item)
                                             for item in outcome.get("results", [])[:8]) if clean]
                searches.append({
                    "query": query,
                    "source": str(outcome.get("source") or "unknown")[:80],
                    "creator_store_api_status": str(outcome.get("creator_store_api_status") or "unknown")[:40],
                    "creator_store_search_url": str(outcome.get("creator_store_search_url") or "")[:500],
                    "results": rows,
                })
                matches.extend(rows)
        unique_matches = []
        seen = set()
        for row in matches:
            identity = row.get("asset_id") or row.get("url")
            if identity and identity not in seen:
                seen.add(identity)
                unique_matches.append(row)

        name_asset_ids = {row.get("asset_id") for row in unique_matches if row.get("asset_id")}
        name_urls = {row.get("url") for row in unique_matches if row.get("url")}
        placement_dimensions = []
        for call, row in pairs:
            if str(call.get("tool") or "") != "plan_mesh_placement" or not row:
                continue
            arguments = call.get("arguments") or {}
            outcome = row.get("result") or {}
            if (str(arguments.get("name") or "").casefold() != name.casefold()
                    or outcome.get("ok") is not True):
                continue
            placement = {key: outcome[key] for key in
                         ("anchor", "source_dimensions", "source_units_per_stud",
                          "scale_applied", "room_size", "note") if outcome.get(key) is not None}
            if arguments.get("studs_per_unit") is not None:
                placement["studs_per_unit"] = arguments["studs_per_unit"]
            placements.append(placement)
            placement_dimensions.append(_valid_dimensions(outcome.get("source_dimensions")))
        measured_paths = set()
        for call, row in pairs:
            if str(call.get("tool") or "") != "inspect_mesh_dimensions" or not row:
                continue
            outcome = row.get("result") or {}
            dimensions = _valid_dimensions(outcome.get("dimensions_source_units"))
            if (outcome.get("ok") is True and dimensions
                    and any(_same_dimensions(dimensions, placed)
                            for placed in placement_dimensions if placed)):
                measured_paths.add(str(outcome.get("path") or
                                       (call.get("arguments") or {}).get("path") or ""))

        for call, row in pairs:
            if not row:
                continue
            tool = str(call.get("tool") or "")
            arguments = call.get("arguments") or {}
            outcome = row.get("result") or {}
            path = str(outcome.get("path") or arguments.get("path") or "")
            source = str(outcome.get("source") or arguments.get("url") or "")
            path_matches = _asset_name_in_query(name, path.replace("_", " "))
            url_matches = any(identifier and identifier in source for identifier in name_asset_ids)
            url_matches = url_matches or source in name_urls
            if tool == "fetch_mesh_reference" and outcome.get("ok") is True:
                if len(asset_names) == 1 or path_matches or url_matches or path in measured_paths:
                    downloads.append({key: outcome[key] for key in ("path", "source", "format", "bytes")
                                      if outcome.get(key) is not None})
            elif tool == "inspect_mesh_dimensions" and outcome.get("ok") is True:
                dimensions = _valid_dimensions(outcome.get("dimensions_source_units"))
                if dimensions and (len(asset_names) == 1 or path_matches
                                   or any(_same_dimensions(dimensions, placed)
                                          for placed in placement_dimensions if placed)):
                    measurement = {"path": path[:300],
                                   "dimensions_source_units": dimensions,
                                   "units": str(outcome.get("units") or "source mesh coordinate units; not assumed to be Roblox studs")[:180]}
                    for key in ("bounds", "bounds_frame", "studs_per_unit", "estimated_dimensions_studs",
                                "source_units_per_stud", "scale_applied", "format", "vertices_measured"):
                        if outcome.get(key) is not None:
                            measurement[key] = outcome[key]
                    measurements.append(measurement)
        references.append({
            "anchor_name": name,
            "search_status": "results_found" if unique_matches else "no_results",
            "searches": searches,
            "matches": unique_matches[:12],
            "downloaded_meshes": downloads[:4],
            "measurements": measurements[:4],
            "placements": placements[:4],
            "reference_only": True,
            "imported_into_render": False,
            "note": ("Creator Store discovery is not a license or dimension guarantee. Mesh source units "
                     "are converted only with an explicit scale; the render uses editable map anchors, "
                     "not an imported external mesh."),
        })
    return references


def _apply_verified_placements(model_props: list[dict], asset_references: list[dict]) -> None:
    """Carry measured, explicitly scaled tool placements into the final props."""
    by_name = {str(prop.get("name") or "").casefold(): prop for prop in model_props}
    for reference in asset_references:
        prop = by_name.get(str(reference.get("anchor_name") or "").casefold())
        if prop is None:
            continue
        placements = reference.get("placements") or []
        if not placements:
            continue
        anchor = placements[-1].get("anchor")
        if not isinstance(anchor, dict):
            continue
        for key in ("shape", "material", "position", "size", "model", "physics"):
            if key in anchor:
                prop[key] = anchor[key]


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
    models_task = next(task for task in tasks
                       if str(task.get("topic") or "").strip().lower() == "models")
    request = {
        "context": "\n\n".join(part for part in (context, *extras) if part),
        # These task objects are passed through unchanged. This tool never
        # invents a required call or replaces the local model's instructions.
        "tasks": tasks,
        # This is a runner-side acceptance policy, not another authored task or
        # tool call. The helper must still author every search/fetch/inspection
        # call itself before the shared tools execute it.
        "tool_requirements": {
            str(models_task["id"]): {
                "asset_search_names": names,
                "inspect_fetched_meshes": True,
                "place_measured_meshes": True,
            },
        },
    }
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

    tool_events = _validate_model_asset_tools(models_result, expected_names)
    asset_references = _asset_references(expected_names, tool_events)
    _apply_verified_placements(model_props, asset_references)

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
    plan["asset_references"] = asset_references
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(paint(f"Combined the delegated map, camera and {len(model_props)} model anchor(s).",
                "success"), flush=True)
    return plan


def _review_asset_digest(values: Any) -> list[dict]:
    digest = []
    for reference in values[:2] if isinstance(values, list) else []:
        if not isinstance(reference, dict):
            continue
        matches = []
        for result in reference.get("matches", [])[:4] if isinstance(reference.get("matches"), list) else []:
            if not isinstance(result, dict):
                continue
            matches.append({key: result[key] for key in
                            ("title", "asset_id", "asset_type", "creator", "url", "source")
                            if result.get(key) is not None})
        measurements = []
        for measurement in reference.get("measurements", [])[:3] if isinstance(reference.get("measurements"), list) else []:
            if not isinstance(measurement, dict):
                continue
            measurements.append({key: measurement[key] for key in
                                 ("path", "dimensions_source_units", "units", "studs_per_unit",
                                  "estimated_dimensions_studs", "source_units_per_stud", "scale_applied")
                                 if measurement.get(key) is not None})
        placements = []
        for placement in reference.get("placements", [])[:2] if isinstance(reference.get("placements"), list) else []:
            if not isinstance(placement, dict):
                continue
            anchor = placement.get("anchor") if isinstance(placement.get("anchor"), dict) else {}
            placements.append({
                "anchor": {key: anchor[key] for key in ("name", "model", "position", "size")
                           if anchor.get(key) is not None},
                "source_dimensions": placement.get("source_dimensions"),
                "studs_per_unit": placement.get("studs_per_unit"),
                "scale_applied": placement.get("scale_applied"),
            })
        digest.append({
            "anchor_name": reference.get("anchor_name"),
            "search_status": reference.get("search_status"),
            "matches": matches,
            "measurements": measurements,
            "placements": placements,
            "reference_only": True,
            "imported_into_render": False,
        })
    return digest


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
        "asset_references": _review_asset_digest(plan.get("asset_references", [])),
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


def build_review_handoff_request(orchestration_path: Path, plan_path: Path,
                                  results_path: Path, context_path: Path,
                                  system_path: Path, model: str, failure_reason: str,
                                  duration: float, cast: list[str] | str,
                                  output_path: Path) -> dict:
    """Give a tool-enabled external reviewer the current run, plan, and evidence."""
    orchestration = _orchestration(_read_json(orchestration_path))
    tasks = _validated_tasks(orchestration)
    plan = _read_json(plan_path)
    results = _read_json(results_path)
    completed = []
    for task in tasks:
        result = _successful_result(results, str(task["id"]), str(task.get("topic") or "task"))
        completed.append({"id": task["id"], "topic": task.get("topic"),
                          "provider": result.get("provider", ""),
                          "provider_model": result.get("provider_model", ""),
                          "seconds": result.get("seconds")})
    try:
        run_memory = system_path.read_text(encoding="utf-8").strip()
    except OSError:
        run_memory = ""
    map_context = context_path.read_text(encoding="utf-8").strip()
    safe_memory = redact_secrets(run_memory)[:5400]
    safe_context = redact_secrets(map_context)[:4600]
    reason = redact_secrets(" ".join(str(failure_reason or "review call did not return a usable answer").split()))[:240]
    run_context = "\n\n".join((
        "Current-run system memory (selected local model/preset, narration, and earlier decisions):\n" + safe_memory,
        "Map-specific story and acceptance constraints:\n" + safe_context,
        f"Selected local Ollama model: {model}. The local review call did not complete ({reason}). "
        "This is an explicit external sub-agent handoff; do not switch or claim a different local model was used.",
    ))[:11900]
    local_director = {
        "public_rationale": orchestration.get("public_rationale", ""),
        "design_brief": orchestration.get("design_brief", ""),
        "model_anchor_names": orchestration.get("model_anchor_names", []),
        "authored_calls": [{"id": task.get("id"), "topic": task.get("topic"),
                            "instruction": str(task.get("instruction") or "")[:1200]}
                           for task in tasks],
    }
    review_input = {
        "selected_local_model": model,
        "handoff_reason": reason,
        "local_director_first_response": local_director,
        "completed_helper_calls": completed,
        "assembled_plan_digest": _review_digest(plan),
        "asset_search_measurement_evidence": plan.get("asset_references", []),
        "available_workspace_evidence": ["map_response.json", "subagent_results.json",
                                         "map_orchestration_response.json", "map_context.txt",
                                         "system_prompt.txt"],
    }
    input_text = json.dumps(review_input, ensure_ascii=False, separators=(",", ":"))
    # gemini_subagent bounds each task input at 12,000 characters. Keep the direct
    # evidence digest intact where possible; the full assembled plan and raw helper
    # trace remain readable with the mandatory workspace audit/read tools.
    if len(input_text) > 11900:
        review_input["asset_search_measurement_evidence"] = [
            {key: value for key, value in row.items()
             if key not in {"matches", "searches", "downloaded_meshes"}}
            for row in plan.get("asset_references", []) if isinstance(row, dict)
        ]
        review_input["assembled_plan_digest"] = {
            "name": plan.get("name"), "theme": plan.get("theme"),
            "props": _review_digest(plan).get("props", []),
            "asset_references": review_input["asset_search_measurement_evidence"],
        }
        input_text = json.dumps(review_input, ensure_ascii=False, separators=(",", ":"))[:11900]
    if isinstance(cast, str):
        cast_names = [name.strip() for name in cast.replace(";", ",").split(",") if name.strip()]
    else:
        cast_names = [str(name).strip() for name in cast if str(name).strip()]
    task = {
        "id": "r1",
        "kind": "agent",
        "topic": "map_review",
        "use_tools": True,
        "instruction": (
            "Independently review the already assembled Roblox story-map plan using the current-run memory, "
            "story/scene constraints, local director brief, model-search evidence, and full plan files. "
            "Do not edit, repair, rewrite, or replace any map. You MUST author and execute "
            f"audit_roblox_map(path=map_response.json, duration={float(duration):g}, cast={json.dumps(cast_names)}). "
            "Check story/theme and indoor-room fit, cast placements, usable cameras and face timing, and "
            "whether the assigned model anchors and verified asset evidence are carried into the plan. "
            "If there is no blocking defect, accept exactly t1 and t2. If there is one, set changes_needed "
            "true with a short actionable revision_instruction; the workflow stops and does not rewrite locally. "
            "Do not reveal private reasoning. Return JSON only in the required acceptance shape."
        ),
        "input": input_text,
    }
    request = {
        "context": run_context,
        "tasks": [task],
        "tool_requirements": {"r1": {"required_tools": ["audit_roblox_map"]}},
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(request, ensure_ascii=False) + "\n", encoding="utf-8")
    return request


def _public_review_note(value: Any) -> str:
    note = redact_secrets(" ".join(str(value or "").split())).strip()[:320]
    lowered = note.casefold()
    if (note.startswith(("{", "[")) or any(marker in lowered for marker in _PRIVATE_RATIONALE_MARKERS)):
        return ""
    return note


def _record_review(orchestration_path: Path, plan_path: Path, review: dict,
                   reviewer: dict, reviewer_label: str) -> dict:
    orchestration = _orchestration(_read_json(orchestration_path))
    tasks = _validated_tasks(orchestration)
    if not isinstance(review, dict):
        raise ValueError(f"{reviewer_label} did not return a review JSON object")
    accepted = review.get("accepted")
    accepted = [str(item).strip() for item in accepted] if isinstance(accepted, list) else []
    note = _public_review_note(review.get("note"))
    if review.get("changes_needed") is True:
        detail = _public_review_note(review.get("revision_instruction") or note)
        raise ValueError(f"{reviewer_label} did not accept the sub-agent plan: "
                         + (detail or "it requested changes")
                         + "; stopping without a local map rewrite or a repair loop")
    if review.get("changes_needed") is not False:
        raise ValueError(f"{reviewer_label} did not explicitly approve the sub-agent plan; "
                         "refusing to ship an unreviewed map")
    required_ids = {str(task["id"]) for task in tasks}
    if len(accepted) != len(set(accepted)) or set(accepted) != required_ids:
        raise ValueError(f"{reviewer_label} must explicitly accept both sub-agent tasks "
                         "and no others; refusing to ship an unreviewed map")
    plan = _read_json(plan_path)
    if not isinstance(plan, dict):
        raise ValueError("the assembled map plan is not a JSON object")
    plan["subagent_review"] = {"accepted": accepted, "note": note,
                               "reviewer": reviewer}
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    print(paint(f"{reviewer_label} accepted both sub-agent tasks"
                + (f": {note}" if note else "."), "success"), flush=True)
    return plan


def accept_review(orchestration_path: Path, review_path: Path, plan_path: Path,
                  model: str = "") -> dict:
    """Require the selected local model to positively review both authored calls."""
    review = extract_plan(_read_json(review_path))
    if not isinstance(review, dict):
        raise ValueError("the selected local model did not return a review JSON object")
    reviewer = {"kind": "selected_local_model"}
    if model:
        reviewer["model"] = str(model)[:120]
    return _record_review(orchestration_path, plan_path, review, reviewer,
                          "Selected local model")


def accept_handoff_review(orchestration_path: Path, results_path: Path, plan_path: Path,
                          local_model: str, failure_reason: str) -> dict:
    """Accept only a tool-enabled handoff result that audited the assembled map."""
    handoff = _successful_result(_read_json(results_path), "r1", "map-review handoff")
    audit_completed = any(
        str(call.get("tool") or "") == "audit_roblox_map"
        and row is not None and isinstance(row.get("result"), dict)
        and row["result"].get("ok") is True
        for call, row in _paired_tool_events(handoff)
    )
    if not audit_completed:
        raise ValueError("the map-review handoff did not complete its required audit_roblox_map tool call")
    review = _decode_answer(str(handoff.get("text") or ""), label="map-review handoff")
    provider = str(handoff.get("provider") or "external sub-agent")[:80]
    provider_model = str(handoff.get("provider_model") or "")[:120]
    reason = redact_secrets(" ".join(str(failure_reason or "local review call stalled").split()))[:240]
    reviewer = {"kind": "context_aware_tool_enabled_subagent", "provider": provider,
                "selected_local_model": str(local_model)[:120], "handoff_reason": reason}
    if provider_model:
        reviewer["provider_model"] = provider_model
    return _record_review(orchestration_path, plan_path, review, reviewer,
                          "Context-aware tool-enabled sub-agent")


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

    handoff_parser = subparsers.add_parser(
        "review-handoff-request", help="prepare a context-aware, tool-enabled external review handoff")
    handoff_parser.add_argument("--orchestration", required=True, type=Path)
    handoff_parser.add_argument("--plan", required=True, type=Path)
    handoff_parser.add_argument("--results", required=True, type=Path)
    handoff_parser.add_argument("--context", required=True, type=Path)
    handoff_parser.add_argument("--system", required=True, type=Path)
    handoff_parser.add_argument("--model", required=True)
    handoff_parser.add_argument("--failure-reason", required=True)
    handoff_parser.add_argument("--duration", type=float, required=True)
    handoff_parser.add_argument("--cast", default="")
    handoff_parser.add_argument("--output", required=True, type=Path)

    accept_parser = subparsers.add_parser("accept", help="validate and record the local review")
    accept_parser.add_argument("--orchestration", required=True, type=Path)
    accept_parser.add_argument("--review", required=True, type=Path)
    accept_parser.add_argument("--plan", required=True, type=Path)
    accept_parser.add_argument("--model", default="")

    accept_handoff_parser = subparsers.add_parser(
        "accept-handoff", help="validate a tool-enabled external review and record its provenance")
    accept_handoff_parser.add_argument("--orchestration", required=True, type=Path)
    accept_handoff_parser.add_argument("--results", required=True, type=Path)
    accept_handoff_parser.add_argument("--plan", required=True, type=Path)
    accept_handoff_parser.add_argument("--local-model", required=True)
    accept_handoff_parser.add_argument("--failure-reason", required=True)

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
        elif args.command == "review-handoff-request":
            request = build_review_handoff_request(
                args.orchestration, args.plan, args.results, args.context, args.system,
                args.model, args.failure_reason, args.duration, args.cast, args.output)
            print(paint(f"Prepared a context-aware tool-enabled review handoff; selected local model "
                        f"{args.model} remains unchanged.", "plan"), flush=True)
        elif args.command == "accept":
            accept_review(args.orchestration, args.review, args.plan, args.model)
        elif args.command == "accept-handoff":
            accept_handoff_review(args.orchestration, args.results, args.plan,
                                  args.local_model, args.failure_reason)
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(paint(f"Map orchestration failed: {exc}", "error", stream=sys.stderr),
              file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
