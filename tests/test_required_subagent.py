"""Map creation is delegated; the selected local model only orchestrates/reviews."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import map_delegation  # noqa: E402
import map_orchestration  # noqa: E402

WORKFLOW = ROOT / ".github" / "workflows" / "main.yml"


def workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def task(task_id: str, topic: str, instruction: str) -> dict:
    return {"id": task_id, "kind": "write", "topic": topic,
            "instruction": instruction}


def orchestration() -> dict:
    models_task = task("t2", "models",
                       "Create the Parcel Lantern as one additional valid map prop anchor in JSON.")
    models_task["use_tools"] = True
    return {
        "public_rationale": "A bright market and shared search make the friends' hopeful ending easy to read.",
        "design_brief": "A warm, sunlit market where a lost parcel brings two friends together.",
        "model_anchor_names": ["Parcel Lantern"],
        "search_queries": [],
        "subagent_tasks": [
            task("t1", "map", "Create the complete story map, camera storyboard, and face timeline as JSON."),
            models_task,
        ],
    }


def model_result(text: str, name: str = "Parcel Lantern") -> dict:
    query = f"{name} Roblox model mesh"
    listing = {"title": f"{name} model", "asset_id": "123456", "asset_type": "Model",
               "creator": "Test Creator", "url": "https://create.roblox.com/store/asset/123456",
               "source": "Roblox Creator Store API"}
    return {
        "id": "t2", "topic": "models", "ok": True, "provider": "gemini",
        "text": text,
        "tool_calls": [{"tool": "search_roblox_meshes",
                         "arguments": {"query": query, "limit": 8}, "round": 1}],
        "tool_results": [{"tool": "search_roblox_meshes", "round": 1,
                          "result": {"ok": True, "query": query,
                                     "source": "Roblox Creator Store API",
                                     "creator_store_api_status": "available",
                                     "creator_store_search_url": "https://create.roblox.com/store/asset?query=Parcel",
                                     "results": [listing]}}],
    }


def measured_model_result(text: str) -> dict:
    result = model_result(text)
    result["tool_calls"].extend([
        {"tool": "fetch_mesh_reference",
         "arguments": {"url": "https://assets.example/parcel-lantern.obj",
                       "path": "references/parcel_lantern.obj"}, "round": 2},
        {"tool": "inspect_mesh_dimensions",
         "arguments": {"path": "references/parcel_lantern.obj"}, "round": 3},
        {"tool": "plan_mesh_placement",
         "arguments": {"name": "Parcel Lantern", "dimensions": [4, 2, 1],
                       "studs_per_unit": 2, "model": "lamp"}, "round": 4},
    ])
    result["tool_results"].extend([
        {"tool": "fetch_mesh_reference", "round": 2,
         "result": {"ok": True, "path": "references/parcel_lantern.obj",
                    "source": "https://assets.example/parcel-lantern.obj",
                    "format": "obj", "bytes": 1024}},
        {"tool": "inspect_mesh_dimensions", "round": 3,
         "result": {"ok": True, "path": "references/parcel_lantern.obj", "format": "obj",
                    "dimensions_source_units": [4.0, 2.0, 1.0],
                    "estimated_dimensions_studs": [8.0, 4.0, 2.0],
                    "studs_per_unit": 2,
                    "units": "source mesh coordinate units; not assumed to be Roblox studs",
                    "bounds": {"min": [-2, 0, -0.5], "max": [2, 2, 0.5]}}},
        {"tool": "plan_mesh_placement", "round": 4,
         "result": {"ok": True, "source_dimensions": [4.0, 2.0, 1.0],
                    "source_units_per_stud": 0.5, "scale_applied": 1.0,
                    "anchor": {"name": "Parcel Lantern", "shape": "Block", "material": "SmoothPlastic",
                               "position": [12.0, 2.0, -8.0], "size": [8.0, 4.0, 2.0],
                               "color": [128, 145, 168], "model": "lamp"}}},
    ])
    return result


def blueprint() -> dict:
    props = []
    for index in range(8):
        props.append({"name": f"Market Anchor {index + 1}", "model": "building",
                      "shape": "Block", "material": "Wood",
                      "position": [float(index * 24 + 24), 5, -40],
                      "size": [12, 10, 12], "color": [170, 190, 210]})
    return {
        "name": "Lantern Market",
        "theme": "A sunny storybook market where a parcel guides two friends home.",
        "time_of_day": "day",
        "ground_material": "Grass",
        "ground_color": [88, 166, 91],
        "ambient_color": [185, 205, 225],
        "props": props,
        "character_placements": [
            {"username": "Ava", "role": "lead", "position": [0, 0, 20]},
            {"username": "Bo", "role": "supporting", "position": [6, 0, 24]},
        ],
        "camera_shots": [
            {"time": float(index * 5), "position": [0, 10, 40], "target": [0, 4, 20],
             "focus_username": "Ava", "transition": "smooth", "framing": "auto"}
            for index in range(6)
        ],
        "face_expressions": [
            {"time": float(index * 4 + 1), "expression": "happy", "username": "Ava"}
            for index in range(6)
        ],
    }


class OrchestrationSchemaTests(unittest.TestCase):
    def test_first_local_response_is_a_compact_two_call_orchestration(self) -> None:
        schema = map_orchestration.orchestration_schema()
        self.assertEqual(schema["properties"]["subagent_tasks"]["minItems"], 2)
        self.assertEqual(schema["properties"]["subagent_tasks"]["maxItems"], 2)
        self.assertEqual(schema["properties"]["subagent_tasks"]["items"]["properties"]["kind"]["enum"],
                         ["write"])
        self.assertEqual(schema["properties"]["subagent_tasks"]["items"]["properties"]["id"]["enum"],
                         ["t1", "t2"])
        self.assertEqual(schema["properties"]["subagent_tasks"]["items"]["properties"]["use_tools"]["type"],
                         "boolean")
        self.assertEqual(schema["properties"]["model_anchor_names"]["minItems"], 1)
        self.assertEqual(set(schema["required"]),
                         {"public_rationale", "design_brief", "model_anchor_names",
                          "search_queries", "subagent_tasks"})
        self.assertNotIn("props", schema["properties"], "the local model must not emit the map")
        self.assertNotIn("camera_shots", schema["properties"])
        self.assertEqual(schema["properties"]["public_rationale"]["maxLength"], 320)

    def test_first_response_requires_a_safe_public_rationale(self) -> None:
        invalid_rationales = (None, {"thought": "private"}, "x" * 321,
                              "My private reasoning is to make the room dark.",
                              '{"public_rationale":"not prose"}')
        for rationale in invalid_rationales:
            with self.subTest(rationale=str(rationale)[:32]):
                bad = orchestration()
                if rationale is None:
                    bad.pop("public_rationale")
                else:
                    bad["public_rationale"] = rationale
                with self.assertRaisesRegex(ValueError, "public rationale"):
                    map_orchestration._validated_tasks(bad)

    def test_first_response_validator_requires_map_and_models_topics(self) -> None:
        response = {"message": {"content": json.dumps(orchestration())}}
        self.assertEqual(map_delegation.missing_required_topics(response), [])
        self.assertEqual(map_delegation.authored_topics(response), {"map", "models"})

    def test_missing_map_call_is_not_repaired_or_substituted(self) -> None:
        bad = orchestration()
        bad["subagent_tasks"] = [bad["subagent_tasks"][1],
                                 task("t1", "narration", "Write a narration instead.")]
        self.assertIn("map/camera", " ".join(map_delegation.missing_required_topics(bad)))
        with self.assertRaisesRegex(ValueError, "map/camera"):
            map_orchestration._validated_tasks(bad)

    def test_missing_models_call_is_not_repaired_or_substituted(self) -> None:
        bad = orchestration()
        bad["subagent_tasks"][1] = task("t2", "faces", "Create another face timeline.")
        self.assertIn("models", " ".join(map_delegation.missing_required_topics(bad)))
        with self.assertRaisesRegex(ValueError, "models"):
            map_orchestration._validated_tasks(bad)

    def test_task_instructions_and_tool_permission_are_forwarded_without_synthesis(self) -> None:
        original = orchestration()
        original["subagent_tasks"][1]["use_tools"] = True
        response = {"message": {"content": json.dumps(original)}}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            response_file = root / "response.json"
            context_file = root / "context.txt"
            output_file = root / "request.json"
            response_file.write_text(json.dumps(response), encoding="utf-8")
            context_file.write_text("Story and interior-room constraints.", encoding="utf-8")
            request = map_orchestration.build_subagent_request(response_file, context_file, output_file)
            self.assertEqual(request["tasks"], original["subagent_tasks"])
            self.assertIn(original["design_brief"], request["context"])
            self.assertIn(original["public_rationale"], request["context"])
            self.assertIn("public rationale", request["context"])
            self.assertIn("Parcel Lantern", request["context"])
            self.assertIn("Story and interior-room constraints", request["context"])
            self.assertIs(request["tasks"][1]["use_tools"], True)
            self.assertEqual(request["tool_requirements"]["t2"]["asset_search_names"],
                             ["Parcel Lantern"])
            self.assertTrue(request["tool_requirements"]["t2"]["inspect_fetched_meshes"])
            self.assertTrue(request["tool_requirements"]["t2"]["place_measured_meshes"])

    def test_models_task_must_author_tool_access(self) -> None:
        bad = orchestration()
        bad["subagent_tasks"][1]["use_tools"] = False
        with self.assertRaisesRegex(ValueError, "models task must set use_tools:true"):
            map_orchestration._validated_tasks(bad)

    def test_tool_access_must_be_an_ai_authored_json_boolean(self) -> None:
        bad = orchestration()
        bad["subagent_tasks"][1]["use_tools"] = "true"
        with self.assertRaisesRegex(ValueError, "use_tools must be a JSON boolean"):
            map_orchestration._validated_tasks(bad)


class SubagentAssemblyTests(unittest.TestCase):
    def test_map_camera_and_model_outputs_are_assembled_before_review(self) -> None:
        original = orchestration()
        helper_results = {
            "results": [
                {"id": "t1", "topic": "map", "ok": True,
                 "provider": "bazaarlink", "seconds": 12.0,
                 "text": json.dumps(blueprint())},
                {**model_result(json.dumps({"props": [
                    {"name": "Parcel Lantern", "model": "lamp", "shape": "Block",
                     "material": "Metal", "position": [72, 3, -40], "size": [2, 4, 2],
                     "color": [230, 190, 100]}
                ]})), "seconds": 4.0},
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestration_file = root / "orchestration.json"
            results_file = root / "results.json"
            plan_file = root / "plan.json"
            orchestration_file.write_text(json.dumps(original), encoding="utf-8")
            results_file.write_text(json.dumps(helper_results), encoding="utf-8")
            plan = map_orchestration.assemble_plan(orchestration_file, results_file, plan_file)
            self.assertEqual(len(plan["props"]), 9)
            self.assertEqual(plan["props"][-1]["name"], "Parcel Lantern")
            self.assertEqual(plan["asset_references"][0]["matches"][0]["asset_id"], "123456")
            self.assertFalse(plan["asset_references"][0]["imported_into_render"])
            self.assertEqual(json.loads(plan_file.read_text(encoding="utf-8")), plan)

    def test_verified_mesh_dimensions_and_scaled_placement_reach_the_generated_plan(self) -> None:
        helper_results = {"results": [
            {"id": "t1", "topic": "map", "ok": True, "text": json.dumps(blueprint())},
            measured_model_result(json.dumps({"props": [{
                "name": "Parcel Lantern", "model": "lamp", "shape": "Block",
                "material": "Metal", "position": [72, 3, -40], "size": [2, 4, 2],
                "color": [230, 190, 100],
            }]})),
        ]}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestration_file = root / "orchestration.json"
            results_file = root / "results.json"
            plan_file = root / "plan.json"
            orchestration_file.write_text(json.dumps(orchestration()), encoding="utf-8")
            results_file.write_text(json.dumps(helper_results), encoding="utf-8")
            plan = map_orchestration.assemble_plan(orchestration_file, results_file, plan_file)
        anchor = plan["props"][-1]
        self.assertEqual(anchor["position"], [12.0, 2.0, -8.0])
        self.assertEqual(anchor["size"], [8.0, 4.0, 2.0])
        self.assertEqual(anchor["model"], "lamp")
        evidence = plan["asset_references"][0]
        self.assertEqual(evidence["measurements"][0]["dimensions_source_units"], [4.0, 2.0, 1.0])
        self.assertEqual(evidence["placements"][0]["studs_per_unit"], 2)
        self.assertEqual(evidence["downloaded_meshes"][0]["source"],
                         "https://assets.example/parcel-lantern.obj")
        self.assertFalse(evidence["imported_into_render"])

    def test_assembly_rejects_model_anchors_without_authored_roblox_search_evidence(self) -> None:
        helper_results = {"results": [
            {"id": "t1", "topic": "map", "ok": True, "text": json.dumps(blueprint())},
            {"id": "t2", "topic": "models", "ok": True,
             "text": json.dumps({"props": [{"name": "Parcel Lantern"}]})},
        ]}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestration_file = root / "orchestration.json"
            results_file = root / "results.json"
            orchestration_file.write_text(json.dumps(orchestration()), encoding="utf-8")
            results_file.write_text(json.dumps(helper_results), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "did not author Roblox mesh search"):
                map_orchestration.assemble_plan(orchestration_file, results_file, root / "plan.json")

    def test_models_task_must_create_exactly_the_assigned_anchor_names(self) -> None:
        helper_results = {
            "results": [
                {"id": "t1", "topic": "map", "ok": True, "text": json.dumps(blueprint())},
                {"id": "t2", "topic": "models", "ok": True,
                 "text": json.dumps({"props": [{"name": "Wrong Name"}]})},
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestration_file = root / "orchestration.json"
            results_file = root / "results.json"
            orchestration_file.write_text(json.dumps(orchestration()), encoding="utf-8")
            results_file.write_text(json.dumps(helper_results), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "exact anchor names"):
                map_orchestration.assemble_plan(orchestration_file, results_file, root / "plan.json")

    def test_an_interior_scene_plan_must_include_cameras_and_faces(self) -> None:
        plan = blueprint()
        plan["camera_shots"] = []
        helper_results = {
            "results": [
                {"id": "t1", "topic": "map", "ok": True, "text": json.dumps(plan)},
                model_result(json.dumps({"props": [{"name": "Parcel Lantern"}]})),
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestration_file = root / "orchestration.json"
            results_file = root / "results.json"
            orchestration_file.write_text(json.dumps(orchestration()), encoding="utf-8")
            results_file.write_text(json.dumps(helper_results), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "camera_shots"):
                map_orchestration.assemble_plan(orchestration_file, results_file, root / "plan.json")


class LocalReviewTests(unittest.TestCase):
    def test_review_request_uses_the_selected_model_and_a_compact_plan_digest(self) -> None:
        original = orchestration()
        results = {"results": [
            {"id": "t1", "topic": "map", "ok": True, "provider": "gemini", "seconds": 5,
             "text": json.dumps(blueprint())},
            {"id": "t2", "topic": "models", "ok": True, "provider": "groq", "seconds": 3,
             "text": json.dumps({"props": [{"name": "Parcel Lantern"}]})},
        ]}
        plan = blueprint()
        plan["props"].append({"name": "Parcel Lantern", "model": "lamp"})
        plan["asset_references"] = [{
            "anchor_name": "Parcel Lantern", "search_status": "results_found",
            "matches": [{"asset_id": "123456", "title": "Parcel Lantern Model",
                         "url": "https://create.roblox.com/store/asset/123456"}],
            "measurements": [{"path": "references/parcel-lantern.obj",
                               "dimensions_source_units": [4.0, 2.0, 1.0],
                               "units": "source units; not assumed studs"}],
            "placements": [], "reference_only": True, "imported_into_render": False,
        }]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestration_file = root / "orchestration.json"
            results_file = root / "results.json"
            plan_file = root / "plan.json"
            context_file = root / "context.txt"
            system_file = root / "system.txt"
            output_file = root / "review.json"
            orchestration_file.write_text(json.dumps(original), encoding="utf-8")
            results_file.write_text(json.dumps(results), encoding="utf-8")
            plan_file.write_text(json.dumps(plan), encoding="utf-8")
            context_file.write_text("This is an indoor scene; the room prompt must be respected.", encoding="utf-8")
            system_file.write_text("director system prompt", encoding="utf-8")
            request = map_orchestration.build_review_request(
                orchestration_file, plan_file, results_file, context_file, system_file,
                "qwen3:8b", True, 8192, output_file)
        self.assertEqual(request["model"], "qwen3:8b")
        self.assertTrue(request["think"])
        self.assertEqual(request["options"]["num_predict"], 420)
        self.assertEqual(request["format"]["properties"]["changes_needed"]["type"], "boolean")
        prompt = request["messages"][-1]["content"]
        self.assertIn("do NOT create, rewrite, repair", prompt)
        self.assertIn("indoor scene", prompt)
        self.assertIn("Parcel Lantern", prompt)
        self.assertIn("123456", prompt)
        self.assertIn("dimensions_source_units", prompt)
        self.assertIn("imported_into_render", prompt)
        self.assertNotIn("camera position coordinates", prompt)

    def test_selected_model_must_accept_both_tasks_before_the_map_is_marked_reviewed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestration_file = root / "orchestration.json"
            review_file = root / "review.json"
            plan_file = root / "plan.json"
            orchestration_file.write_text(json.dumps(orchestration()), encoding="utf-8")
            plan_file.write_text(json.dumps(blueprint()), encoding="utf-8")
            review_file.write_text(json.dumps({"response": json.dumps({
                "accepted": ["t1", "t2"], "note": "Both helper designs fit.",
                "changes_needed": False, "revision_instruction": ""})}), encoding="utf-8")
            result = map_orchestration.accept_review(orchestration_file, review_file, plan_file)
            self.assertEqual(result["subagent_review"]["accepted"], ["t1", "t2"])
            self.assertEqual(result["subagent_review"]["note"], "Both helper designs fit.")

    def test_acceptance_requires_an_explicit_boolean_and_exact_task_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestration_file = root / "orchestration.json"
            review_file = root / "review.json"
            plan_file = root / "plan.json"
            orchestration_file.write_text(json.dumps(orchestration()), encoding="utf-8")
            plan_file.write_text(json.dumps(blueprint()), encoding="utf-8")
            cases = [
                ({"accepted": ["t1", "t2"], "note": "Ready.",
                  "revision_instruction": ""}, "did not explicitly approve"),
                ({"accepted": ["t1", "t2", "other"], "note": "Ready.",
                  "changes_needed": False, "revision_instruction": ""}, "both sub-agent tasks"),
            ]
            for payload, message in cases:
                with self.subTest(payload=payload):
                    review_file.write_text(json.dumps({"response": json.dumps(payload)}),
                                           encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, message):
                        map_orchestration.accept_review(
                            orchestration_file, review_file, plan_file)

    def test_rejected_review_stops_without_a_repair_loop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestration_file = root / "orchestration.json"
            review_file = root / "review.json"
            plan_file = root / "plan.json"
            orchestration_file.write_text(json.dumps(orchestration()), encoding="utf-8")
            plan_file.write_text(json.dumps(blueprint()), encoding="utf-8")
            review_file.write_text(json.dumps({"response": json.dumps({
                "accepted": ["t1"], "note": "Model anchor is missing.",
                "changes_needed": True, "revision_instruction": "Place the lantern beside the parcel."})}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "stopping without a local map rewrite"):
                map_orchestration.accept_review(orchestration_file, review_file, plan_file)

    def test_stalled_local_review_handoff_carries_run_memory_and_requires_map_audit_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestration_file = root / "orchestration.json"
            plan_file = root / "map_response.json"
            results_file = root / "subagent_results.json"
            context_file = root / "map_context.txt"
            system_file = root / "system_prompt.txt"
            output_file = root / "handoff.json"
            orchestration_file.write_text(json.dumps(orchestration()), encoding="utf-8")
            handoff_plan = blueprint()
            handoff_plan["asset_references"] = [{"anchor_name": "Parcel Lantern",
                                                 "search_status": "results_found",
                                                 "matches": [{"asset_id": "123456",
                                                              "title": "Parcel lantern asset"}],
                                                 "measurements": [], "placements": []}]
            plan_file.write_text(json.dumps(handoff_plan), encoding="utf-8")
            results_file.write_text(json.dumps({"results": [
                {"id": "t1", "topic": "map", "ok": True, "provider": "gemini", "text": "{}"},
                model_result("{\"props\":[{\"name\":\"Parcel Lantern\"}]}")
            ]}), encoding="utf-8")
            context_file.write_text("Story: two friends return a lost parcel. Scene mode: interior bedroom.",
                                    encoding="utf-8")
            system_file.write_text("RUN MEMORY: selected preset hard, model qwen3:8b; narration is complete.",
                                   encoding="utf-8")
            request = map_orchestration.build_review_handoff_request(
                orchestration_file, plan_file, results_file, context_file, system_file,
                "qwen3:8b", "selected local model review stalled after its same-model retry",
                60, ["Ava", "Bo"], output_file)
            self.assertEqual(json.loads(output_file.read_text(encoding="utf-8")), request)
        self.assertEqual(request["tasks"][0]["kind"], "agent")
        self.assertTrue(request["tasks"][0]["use_tools"])
        self.assertIn("audit_roblox_map", request["tasks"][0]["instruction"])
        self.assertIn("duration=60", request["tasks"][0]["instruction"])
        self.assertIn("qwen3:8b", request["context"])
        self.assertIn("interior bedroom", request["context"])
        self.assertIn("123456", request["tasks"][0]["input"])
        self.assertEqual(request["tool_requirements"]["r1"]["required_tools"],
                         ["audit_roblox_map"])

    def test_handoff_acceptance_requires_a_successful_tool_audit_and_records_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestration_file = root / "orchestration.json"
            plan_file = root / "map_response.json"
            results_file = root / "review_results.json"
            orchestration_file.write_text(json.dumps(orchestration()), encoding="utf-8")
            plan_file.write_text(json.dumps(blueprint()), encoding="utf-8")
            accepted = {"accepted": ["t1", "t2"], "note": "The plan fits the story and room.",
                        "changes_needed": False, "revision_instruction": ""}
            result = {"results": [{
                "id": "r1", "ok": True, "provider": "groq", "provider_model": "llama-3.3-70b-versatile",
                "text": json.dumps(accepted),
                "tool_calls": [{"tool": "audit_roblox_map",
                                "arguments": {"path": "map_response.json", "duration": 60,
                                              "cast": ["Ava", "Bo"]}, "round": 1}],
                "tool_results": [{"tool": "audit_roblox_map", "round": 1,
                                  "result": {"ok": True, "world_name": "Lantern Market"}}],
            }]}
            results_file.write_text(json.dumps(result), encoding="utf-8")
            plan = map_orchestration.accept_handoff_review(
                orchestration_file, results_file, plan_file, "qwen3:8b",
                "selected local model review stalled after the same-model retry")
        reviewer = plan["subagent_review"]["reviewer"]
        self.assertEqual(reviewer["kind"], "context_aware_tool_enabled_subagent")
        self.assertEqual(reviewer["provider"], "groq")
        self.assertEqual(reviewer["selected_local_model"], "qwen3:8b")
        self.assertIn("same-model", reviewer["handoff_reason"])
        self.assertEqual(plan["subagent_review"]["accepted"], ["t1", "t2"])

    def test_handoff_cannot_accept_without_a_successful_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            orchestration_file = root / "orchestration.json"
            plan_file = root / "map_response.json"
            results_file = root / "review_results.json"
            orchestration_file.write_text(json.dumps(orchestration()), encoding="utf-8")
            plan_file.write_text(json.dumps(blueprint()), encoding="utf-8")
            results_file.write_text(json.dumps({"results": [{
                "id": "r1", "ok": True, "provider": "gemini", "text": json.dumps({
                    "accepted": ["t1", "t2"], "note": "Ready.",
                    "changes_needed": False, "revision_instruction": ""}),
                "tool_calls": [], "tool_results": [],
            }]}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "required audit_roblox_map"):
                map_orchestration.accept_handoff_review(
                    orchestration_file, results_file, plan_file, "qwen3:8b", "stalled")


class WorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = workflow_text()
        self.start = self.text.index("      - name: Orchestrate and review the delegated map")
        self.end = self.text.index("      - name: Re-view the AI world", self.start)
        self.step = self.text[self.start:self.end]

    def map_prompt(self) -> str:
        prompt_start = self.step.index("cat > map_prompt.txt <<PROMPT")
        prompt_end = self.step.index("\n          PROMPT", prompt_start)
        return self.step[prompt_start:prompt_end]

    def test_story_workflow_step_has_valid_bash_syntax(self) -> None:
        workflow = yaml.safe_load(self.text)
        steps = workflow["jobs"]["generate_roblox_short"]["steps"]
        step = next(item for item in steps
                    if item.get("name") == "Write a believable real-life story")
        parsed = subprocess.run(["bash", "-n"], input=step["run"], text=True,
                                capture_output=True, check=False)
        self.assertEqual(parsed.returncode, 0, msg=parsed.stderr)

    def test_map_orchestration_workflow_step_has_valid_bash_syntax(self) -> None:
        workflow = yaml.safe_load(self.text)
        steps = workflow["jobs"]["generate_roblox_short"]["steps"]
        step = next(item for item in steps
                    if item.get("name") == "Orchestrate and review the delegated map, camera, and model plan")
        parsed = subprocess.run(["bash", "-n"], input=step["run"], text=True,
                                capture_output=True, check=False)
        self.assertEqual(parsed.returncode, 0, msg=parsed.stderr)

    def test_unquoted_map_heredoc_expands_story_and_scene_context(self) -> None:
        heredoc = self.map_prompt()
        command, *source_lines = heredoc.splitlines()
        self.assertEqual(command.strip(), "cat > map_prompt.txt <<PROMPT")
        self.assertNotIn("`", heredoc, "raw backticks execute as command substitutions")
        body = "\n".join(line[10:] if line.startswith("          ") else line
                           for line in source_lines)
        script = f"{command.strip()}\n{body}\nPROMPT\n"
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                **os.environ,
                "STORY_TOPIC": "EXPANDED_STORY_TOPIC",
                "NARRATION": "EXPANDED_NARRATION",
                "WORLD_THEME": "EXPANDED_WORLD_THEME",
                "SCENE_BLOCK": "EXPANDED_SCENE_BLOCK",
                "CAST_NAMES": "EXPANDED_CAST",
                "DURATION_SECONDS": "40",
                "DURATION_LABEL": "40 seconds",
                "MAP_DETAIL": "standard",
                "TARGET_PROPS": "1260",
                "SHOT_COUNT": "10",
                "SHOT_MAX": "16",
                "WORLD_MODE": "interior",
            }
            result = subprocess.run(["bash", "-c", script], cwd=tmp, env=env,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("command not found", result.stderr)
            rendered = (Path(tmp) / "map_prompt.txt").read_text(encoding="utf-8")
        self.assertIn("EXPANDED_STORY_TOPIC", rendered)
        self.assertIn("EXPANDED_NARRATION", rendered)
        self.assertIn("EXPANDED_WORLD_THEME", rendered)
        self.assertIn("EXPANDED_SCENE_BLOCK", rendered)
        self.assertIn("Scene mode: interior", rendered)
        self.assertIn('"model_anchor_names"', rendered)
        self.assertIn('topic "models"', rendered)

    def test_local_model_only_orchestrates_and_does_not_author_map_or_camera_json(self) -> None:
        prompt = self.map_prompt()
        self.assertIn("director and orchestrator, not the map artist", prompt)
        self.assertIn("Do NOT reveal hidden reasoning or write props, coordinates, camera shots, face beats", prompt)
        self.assertIn("two task calls that you author now", prompt)
        self.assertIn("actual sub-agent calls", prompt)
        self.assertIn('ALWAYS author "use_tools":true on this models task', prompt)
        self.assertIn("search_roblox_meshes query for each exact model_anchor_name", prompt)
        self.assertIn("inspect_mesh_dimensions", prompt)
        self.assertIn("explicit studs_per_unit", prompt)
        self.assertIn("Creator Store listings do not provide verified dimensions", prompt)
        self.assertNotIn("Design the complete coherent world blueprint", prompt)

    def test_scene_mode_is_passed_through_prompt_context_and_final_builder(self) -> None:
        self.assertIn("tools/scene_mode.py", self.step)
        self.assertIn("WORLD_MODE=$(printf", self.step)
        self.assertIn("Path('scene_prompt.txt').read_text", self.step)
        self.assertIn('--scene-mode "${WORLD_MODE:-auto}"', self.step)
        self.assertIn("Preserve all interior-room constraints", self.map_prompt())

    def test_first_response_validation_happens_before_any_helper_call_without_repairs(self) -> None:
        validation = self.step.index("python tools/map_delegation.py map_orchestration_response.json")
        helper_call = self.step.index("python tools/gemini_subagent.py")
        self.assertLess(validation, helper_call)
        self.assertNotIn("for delegation_retry", self.step)
        self.assertNotIn("for helper_round", self.step)
        self.assertNotIn("map_repair_request.json", self.step)
        self.assertIn("stopping without a local map or a repair loop", self.step)

    def test_subagent_creates_map_camera_and_models_then_reviews_or_hands_off(self) -> None:
        helper = self.step.index("python tools/gemini_subagent.py --request subagent_tasks.json")
        assemble = self.step.index("tools/map_orchestration.py assemble")
        review = self.step.index("tools/map_orchestration.py review-request")
        handoff_request = self.step.index("tools/map_orchestration.py review-handoff-request")
        handoff_helper = self.step.index("python tools/gemini_subagent.py --request map_review_handoff_request.json")
        handoff_accept = self.step.index("python tools/map_orchestration.py accept-handoff")
        local_accept = self.step.index("python tools/map_orchestration.py accept --")
        builder = self.step.index("python tools/build_story_map.py")
        self.assertLess(helper, assemble)
        self.assertLess(assemble, review)
        self.assertLess(review, handoff_request)
        self.assertLess(handoff_request, handoff_helper)
        self.assertLess(handoff_helper, handoff_accept)
        self.assertLess(handoff_accept, builder)
        self.assertLess(local_accept, builder)
        self.assertIn("--stdout", self.step, "sub-agent answers and actual tool use remain live and visible")
        self.assertIn("selected local model review stalled after its same-model retry", self.step)
        self.assertIn("No other local model was tried", self.step)
        self.assertIn("touch map_subagent_review.done", self.step)

    def test_local_map_calls_have_hard_deadlines_and_never_switch_models(self) -> None:
        self.assertIn("--max-seconds 600", self.step)
        self.assertIn("--max-seconds 300", self.step)
        self.assertIn('"$AI_MODEL"', self.step)
        self.assertIn("No other local model was tried", self.step)
        self.assertNotIn("--fallback-model", self.step)

    def test_map_failure_is_not_hidden_by_a_procedural_substitute(self) -> None:
        self.assertIn("no local or procedural map will be substituted", self.step)
        self.assertIn("stopping without a procedural replacement", self.step)
        self.assertNotIn("--fallback", self.step)

    def test_console_keeps_color_coded_progress_and_structured_artifacts(self) -> None:
        self.assertIn("AI_COLOR: '1'", self.text)
        self.assertIn("python tools/say.py plan", self.step)
        self.assertIn("python tools/say.py tool", self.step)
        self.assertIn("python tools/say.py success", self.step)
        self.assertIn("dist/ai_activity.jsonl", self.text)
        self.assertIn("from console_style import paint", (ROOT / "tools/map_orchestration.py").read_text(encoding="utf-8"))
        self.assertNotIn("            cat map_delegation.log", self.step)
        self.assertNotIn("            cat map_validation.log", self.step)
        self.assertIn('python tools/say.py success "$(cat map_validation.log)"', self.step)
        self.assertNotIn("[ai-log]", self.step)

    def test_workflow_never_auto_falls_back_to_another_ollama_model(self) -> None:
        for path in (ROOT / ".github/workflows/main.yml",
                     ROOT / ".github/workflows/agent.yml",
                     ROOT / "tools/nish_agent.py",
                     ROOT / "tools/ollama_stream.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("--fallback-model", text, str(path))
            self.assertNotIn("AI_FALLBACK_MODEL", text, str(path))
        self.assertNotIn("AI_MODEL_STICKY", (ROOT / "tools/ollama_stream.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
