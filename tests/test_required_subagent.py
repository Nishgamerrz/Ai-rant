"""The Gemini sub-agent is required for the map and the cameras, optional elsewhere.

The map step is where the world and the shot list are designed, so the AI has to
hand at least one job about them to the sub-agent. The story, narration and
summary steps stay free to plan alone. Both halves are enforced here: the schema
for the map step, the prompt wording, and the workflow's own fallback review so a
forgetful model can never ship an unreviewed map.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import plan_schema  # noqa: E402

WORKFLOW = ROOT / ".github" / "workflows" / "main.yml"


def workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


class MapSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = plan_schema.build_schema([])

    def test_map_plan_must_delegate_at_least_one_task(self) -> None:
        tasks = self.schema["properties"]["subagent_tasks"]
        self.assertEqual(tasks["minItems"], 1)
        self.assertEqual(tasks["items"]["properties"]["topic"]["enum"],
                         ["map", "cameras", "faces", "narration",
                          "animation", "models", "code"])

    def test_subagent_tasks_is_required(self) -> None:
        self.assertIn("subagent_tasks", self.schema["required"])

class WorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = workflow_text()

    def test_map_prompt_says_the_subagent_is_not_optional(self) -> None:
        self.assertIn("THE GEMINI SUB-AGENT IS NOT OPTIONAL FOR THIS STEP", self.text)
        self.assertIn('"topic":"map", "cameras" or "faces"', self.text)
        self.assertIn('"topic":"models"', self.text)

    def test_story_prompt_keeps_delegation_optional(self) -> None:
        self.assertIn("for the STORY, asking is never compulsory", self.text)

    def test_workflow_sends_the_review_itself_when_nothing_was_delegated(self) -> None:
        self.assertIn("MAP_TOPICS = {'map', 'cameras', 'faces'}", self.text)
        self.assertIn("'required-map-camera-review'", self.text)
        self.assertIn("map_subagent_review.done", self.text)

    def test_a_models_job_is_required_too(self) -> None:
        # "create 1-2 parts/models with the sub-agent" - the prompt asks for it and
        # the workflow sends it when the model forgot.
        self.assertIn("at least one MODELS job", self.text)
        self.assertIn("'required-model-design'", self.text)
        self.assertIn("required 1-2 finished model designs", self.text)

    def test_the_ai_is_told_the_time_and_the_edits_it_made(self) -> None:
        self.assertIn("it tells you how long each job took and whether it edited a file", self.text)
        self.assertIn("CONFIRM BEFORE YOU CONTINUE", self.text)
        self.assertIn('"subagent_review"', self.text)

    def test_the_three_task_cap_cannot_drop_a_required_job(self) -> None:
        self.assertIn("Never let the cap of three steal", self.text)
        self.assertIn("tasks = required[:3] + others[:max(0, 3 - len(required[:3]))]", self.text)

    def test_the_map_step_cannot_loop_on_required_tasks(self) -> None:
        self.assertIn("SUBA_ROUNDS=0", self.text)
        self.assertIn('if [ "$SUBA_ROUNDS" -ge 2 ]; then', self.text)
        self.assertIn("the world plan is final and the run moves on", self.text)

    def test_the_helper_loop_cannot_skip_the_review(self) -> None:
        self.assertIn('if [ -z "$QUERIES" ] && [ "$TASKS" = "[]" ] '
                      '&& [ -f map_subagent_review.done ]; then break; fi', self.text)

    def test_a_belt_and_braces_review_runs_after_the_loop(self) -> None:
        self.assertIn('if [ ! -f map_subagent_review.done ]; then', self.text)
        self.assertIn("never shipped unreviewed", self.text)


if __name__ == "__main__":
    unittest.main()
