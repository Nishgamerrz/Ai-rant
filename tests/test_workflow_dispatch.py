"""Both "Run workflow" buttons must ask for the same thing.

GitHub's dispatch button on the long workflow occasionally refuses to fire
("Workflow could not be run. Please try again."). .github/workflows/start.yml is
a twenty-line workflow whose only job is to call the real one, so there is always
a button that works. These tests keep the two forms in step: a new input added to
one and forgotten in the other would silently run the short with a default.
"""
from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
MAIN = WORKFLOWS / "main.yml"
START = WORKFLOWS / "start.yml"


def load(path: Path) -> dict:
    # PyYAML reads the bare key "on" as the boolean True.
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def triggers(document: dict) -> dict:
    return document.get(True) or document.get("on") or {}


def dispatch_inputs(path: Path) -> dict:
    return triggers(load(path))["workflow_dispatch"]["inputs"]


def call_inputs() -> dict:
    return triggers(load(MAIN))["workflow_call"]["inputs"]


class BackupButtonTests(unittest.TestCase):
    def test_both_files_are_valid_yaml_workflows(self):
        for path in (MAIN, START):
            document = load(path)
            self.assertIn("jobs", document, path.name)
            self.assertIsInstance(document["jobs"], dict, path.name)

    def test_the_real_workflow_can_be_called_by_another_workflow(self):
        self.assertIn("workflow_call", triggers(load(MAIN)))
        self.assertIn("workflow_dispatch", triggers(load(MAIN)))

    def test_the_backup_button_calls_the_real_workflow(self):
        jobs = load(START)["jobs"]
        self.assertEqual(len(jobs), 1, "the backup button should do nothing but call the generator")
        job = next(iter(jobs.values()))
        self.assertEqual(job["uses"], "./.github/workflows/main.yml")
        self.assertEqual(job.get("secrets"), "inherit", "the Gemini key must reach the generator")

    def test_both_forms_ask_for_the_same_inputs(self):
        self.assertEqual(sorted(dispatch_inputs(START)), sorted(dispatch_inputs(MAIN)))
        self.assertEqual(sorted(dispatch_inputs(MAIN)), sorted(call_inputs()))

    def test_the_backup_button_passes_every_input_through(self):
        job = next(iter(load(START)["jobs"].values()))
        passed = set(job["with"])
        self.assertEqual(passed, set(call_inputs()))
        for name, value in job["with"].items():
            self.assertEqual(value, "${{ inputs.%s }}" % name)

    def test_defaults_and_requiredness_match(self):
        main_form = dispatch_inputs(MAIN)
        call_form = call_inputs()
        backup_form = dispatch_inputs(START)
        for name in call_form:
            self.assertEqual(call_form[name].get("type"), "string",
                             f"{name}: workflow_call only understands string/boolean/number")
            self.assertEqual(main_form[name].get("default"), call_form[name].get("default"),
                             f"{name}: the two forms disagree about the default")
            self.assertEqual(bool(main_form[name].get("required")), bool(call_form[name].get("required")),
                             f"{name}: the two forms disagree about whether it is required")
            self.assertEqual(main_form[name].get("default"), backup_form[name].get("default"),
                             f"{name}: the backup button disagrees about the default")

    def test_every_choice_default_is_one_of_its_options(self):
        for path in (MAIN, START):
            for name, spec in dispatch_inputs(path).items():
                if spec.get("type") != "choice":
                    continue
                self.assertIn(spec.get("default"), spec["options"], f"{path.name}: {name}")

    def test_the_workflow_still_reads_its_inputs_by_name(self):
        text = MAIN.read_text(encoding="utf-8")
        for name in call_inputs():
            if name == "world_theme":
                self.assertIn("inputs.world_theme", text)
                continue
            self.assertIn("inputs.%s" % name, text, f"main.yml never reads inputs.{name}")


if __name__ == "__main__":
    unittest.main()
