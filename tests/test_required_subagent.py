"""Map creation is delegated; the selected local model only orchestrates/reviews."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

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
    return {
        "design_brief": "A warm, sunlit market where a lost parcel brings two friends together.",
        "model_anchor_names": ["Parcel Lantern"],
        "search_queries": [],
        "subagent_tasks": [
            task("t1", "map", "Create the complete story map, camera storyboard, and face timeline as JSON."),
            task("t2", "models", "Create the Parcel Lantern as one additional valid map prop anchor in JSON."),
        ],
    }


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
        self.assertEqual(schema["properties"]["model_anchor_names"]["minItems"], 1)
        self.assertEqual(set(schema["required"]),
                         {"design_brief", "model_anchor_names", "search_queries", "subagent_tasks"})
        self.assertNotIn("props", schema["properties"], "the local model must not emit the map")
        self.assertNotIn("camera_shots", schema["properties"])

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

    def test_task_instructions_are_forwarded_without_workflow_synthesis(self) -> None:
        original = orchestration()
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
            self.assertIn("Parcel Lantern", request["context"])
            self.assertIn("Story and interior-room constraints", request["context"])


class SubagentAssemblyTests(unittest.TestCase):
    def test_map_camera_and_model_outputs_are_assembled_before_review(self) -> None:
        original = orchestration()
        helper_results = {
            "results": [
                {"id": "t1", "topic": "map", "ok": True,
                 "provider": "bazaarlink", "seconds": 12.0,
                 "text": json.dumps(blueprint())},
                {"id": "t2", "topic": "models", "ok": True,
                 "provider": "gemini", "seconds": 4.0,
                 "text": json.dumps({"props": [
                     {"name": "Parcel Lantern", "model": "lamp", "shape": "Block",
                      "material": "Metal", "position": [72, 3, -40], "size": [2, 4, 2],
                      "color": [230, 190, 100]}
                 ]})},
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
            self.assertEqual(json.loads(plan_file.read_text(encoding="utf-8")), plan)

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
                {"id": "t2", "topic": "models", "ok": True,
                 "text": json.dumps({"props": [{"name": "Parcel Lantern"}]})},
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
        self.assertIn("Do NOT write props, coordinates, camera shots, face beats", prompt)
        self.assertIn("two task calls that you author now", prompt)
        self.assertIn("actual sub-agent calls", prompt)
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

    def test_subagent_creates_map_camera_and_models_then_local_model_reviews(self) -> None:
        helper = self.step.index("python tools/gemini_subagent.py")
        assemble = self.step.index("tools/map_orchestration.py assemble")
        review = self.step.index("tools/map_orchestration.py review-request")
        accept = self.step.index("tools/map_orchestration.py accept")
        builder = self.step.index("python tools/build_story_map.py")
        self.assertLess(helper, assemble)
        self.assertLess(assemble, review)
        self.assertLess(review, accept)
        self.assertLess(accept, builder)
        self.assertIn("--stdout", self.step, "the sub-agent answer remains live and visible")
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
