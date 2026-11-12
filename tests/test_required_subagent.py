"""Map delegation is mandatory, AI-authored, and never workflow-injected."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import map_delegation  # noqa: E402
import plan_schema  # noqa: E402

WORKFLOW = ROOT / ".github" / "workflows" / "main.yml"


def workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


class MapSchemaTests(unittest.TestCase):
    def test_first_map_response_requires_a_subagent_task(self) -> None:
        schema = plan_schema.build_schema([])
        tasks = schema["properties"]["subagent_tasks"]
        self.assertEqual(tasks["minItems"], 1)
        self.assertEqual(tasks["items"]["properties"]["topic"]["enum"],
                         ["map", "cameras", "faces", "narration",
                          "animation", "models", "code"])
        self.assertIn("subagent_tasks", schema["required"])

    def test_followup_plan_can_return_no_more_tasks(self) -> None:
        schema = plan_schema.build_schema([], require_subagent_tasks=False)
        self.assertEqual(schema["properties"]["subagent_tasks"]["minItems"], 0)
        self.assertIn("subagent_tasks", schema["required"])


class FirstResponseValidationTests(unittest.TestCase):
    @staticmethod
    def task(topic: str, task_id: str) -> dict:
        return {"id": task_id, "kind": "write", "topic": topic,
                "instruction": f"Design or review the {topic} for this story."}

    def test_valid_first_response_authors_both_required_topics(self) -> None:
        response = {"message": {"content": json.dumps({
            "subagent_tasks": [self.task("map", "t1"), self.task("models", "t2")]
        })}}
        self.assertEqual(map_delegation.missing_required_topics(response), [])
        self.assertEqual(map_delegation.authored_topics(response), {"map", "models"})

    def test_workflow_generated_review_cannot_substitute_for_ai_authored_map_call(self) -> None:
        # This is what the validator sees: the model's untouched response. A later
        # workflow append would make a different object valid, but cannot repair it.
        ai_response = {"subagent_tasks": [self.task("models", "t1")]}
        workflow_appended = {
            **ai_response,
            "subagent_tasks": ai_response["subagent_tasks"] + [
                self.task("cameras", "workflow-generated-review")
            ],
        }
        self.assertIn("map/camera", " ".join(
            map_delegation.missing_required_topics(ai_response)))
        self.assertEqual(map_delegation.missing_required_topics(workflow_appended), [])

    def test_map_camera_task_does_not_replace_the_models_call(self) -> None:
        response = {"subagent_tasks": [self.task("cameras", "t1")]}
        self.assertIn("models", " ".join(
            map_delegation.missing_required_topics(response)))

    def test_tasks_without_instructions_do_not_count_as_authored_calls(self) -> None:
        response = {"subagent_tasks": [
            {"topic": "map", "kind": "verify", "instruction": "  "},
            self.task("models", "t1"),
        ]}
        self.assertIn("map/camera", " ".join(
            map_delegation.missing_required_topics(response)))


class WorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = workflow_text()

    def map_prompt(self) -> str:
        prompt_start = self.text.index("cat > map_prompt.txt <<PROMPT")
        prompt_end = self.text.index("\n          PROMPT", prompt_start)
        return self.text[prompt_start:prompt_end]

    def test_prompt_says_the_ai_must_manually_author_both_calls_first(self) -> None:
        prompt = self.map_prompt()
        self.assertIn("MANUALLY AUTHOR THE SUB-AGENT TOOL CALLS YOURSELF", prompt)
        self.assertIn("FIRST JSON response", prompt)
        self.assertIn('"topic":"models"', prompt)
        self.assertIn('"topic":"map"', prompt)
        self.assertIn("workflow will not create, append, repair, or substitute", prompt)

    def test_manual_call_requirement_precedes_map_design_instructions(self) -> None:
        prompt = self.map_prompt()
        requirement = prompt.index("MANDATORY FIRST ACTION")
        design = prompt.index("Think through the complete story")
        self.assertLess(requirement, design)

    def test_story_prompt_keeps_delegation_optional(self) -> None:
        self.assertIn("There is no quota and no rule that you must ask", self.text)
        self.assertIn('if you can write the story yourself, just write it and return '
                      '"subagent_tasks":[]', self.text)

    def test_original_response_is_validated_before_any_helper_task_is_built(self) -> None:
        validation = self.text.index("python tools/map_delegation.py map_response.json")
        helper_loop = self.text.index("for helper_round in 1 2 3 4; do")
        self.assertLess(validation, helper_loop)
        self.assertIn("untouched AI response", self.text)

    def test_workflow_never_injects_a_required_subagent_task(self) -> None:
        for forbidden in (
            "required-map-camera-review",
            "required-model-design",
            "The AI delegated nothing for the map/cameras",
            "The AI delegated nothing for the models",
            "sending it once from the draft plan",
            "workflow will itself inject",
        ):
            self.assertNotIn(forbidden, self.text)
        self.assertIn("never synthesize a replacement task", self.text)

    def test_map_response_is_forwarded_without_synthesized_required_jobs(self) -> None:
        self.assertIn("(plan.get('subagent_tasks') or [])[:3]", self.text)
        self.assertIn("'tasks': tasks", self.text)
        self.assertNotIn("MAP_TOPICS =", self.text)
        self.assertIn("cannot execute the AI-authored mandatory map sub-agent calls", self.text)

    def test_a_missing_delegation_is_reprompted_without_marking_review_done(self) -> None:
        retry_loop = self.text.index("for delegation_retry in 1 2 3; do")
        validation = self.text.index("python tools/map_delegation.py map_response.json", retry_loop)
        helper_loop = self.text.index("for helper_round in 1 2 3 4; do", validation)
        self.assertLess(retry_loop, validation)
        self.assertLess(validation, helper_loop)
        self.assertIn("Return a complete corrected map-plan JSON yourself", self.text)
        self.assertIn("manually author BOTH required entries", self.text)
        self.assertIn("map_repair_request.json", self.text)
        self.assertIn("map_repair_response.json", self.text)
        self.assertIn("cp map_repair_response.json map_response.json", self.text)
        self.assertIn("after two explicit re-prompts", self.text)
        self.assertIn("no workflow-generated substitute will be run", self.text)
        self.assertIn("exit 1", self.text)

    def test_followup_schema_allows_the_ai_to_return_an_empty_task_list(self) -> None:
        self.assertIn("--allow-empty-subagent-tasks --output map_followup_schema.json", self.text)
        self.assertGreaterEqual(self.text.count("--slurpfile schema map_followup_schema.json"), 2)

    def test_the_helper_results_still_require_accept_or_decline(self) -> None:
        self.assertIn("YOU MUST ACCEPT OR DECLINE BEFORE YOU CONTINUE", self.text)
        self.assertIn('"subagent_review"', self.text)
        self.assertIn("The AI asked for changes, so it gets one more world plan round", self.text)

    def test_a_real_ai_authored_subagent_round_marks_the_review_done(self) -> None:
        self.assertIn("python tools/gemini_subagent.py", self.text)
        self.assertIn("touch map_subagent_review.done", self.text)


if __name__ == "__main__":
    unittest.main()
