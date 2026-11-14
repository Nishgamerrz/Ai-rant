from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "prepare_narration.py"


class ProofreadNarrationTests(unittest.TestCase):
    def run_proofread(self, results: dict, *, minimum: int = 1, maximum: int = 100,
                      cast_names: str = "", expected_id: str = "t1"):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        work = Path(temporary.name)
        result_path = work / "story_subagent_results.json"
        output_path = work / "dist" / "narration.txt"
        result_path.write_text(json.dumps(results), encoding="utf-8")
        env = {
            **os.environ,
            "MIN_WORDS": str(minimum),
            "MAX_WORDS": str(maximum),
            "CAST_NAMES": cast_names,
        }
        command = [sys.executable, str(SCRIPT), "--subagent", str(result_path),
                   str(output_path), "15"]
        if expected_id != "t1":
            command.extend(["--task-id", expected_id])
        result = subprocess.run(
            command,
            cwd=work, env=env, capture_output=True, text=True, check=False,
        )
        return work, output_path, result

    @staticmethod
    def result(text: str, *, task_id: str = "t1", kind: str = "edit",
               ok: bool = True, status: str = "complete") -> dict:
        return {"results": [{"id": task_id, "kind": kind, "ok": ok,
                             "status": status, "text": text}]}

    def test_the_complete_proofread_is_the_exact_narration_written_for_downstream(self):
        corrected = "Maya didn't notice the wallet.\nLeo noticed it and returned it."
        work, output_path, result = self.run_proofread(
            self.result(corrected), minimum=11, maximum=11)
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        expected = corrected
        self.assertEqual(output_path.read_text(encoding="utf-8"), expected)
        self.assertIn("This exact corrected text is now the narration source used downstream", result.stdout)
        self.assertNotIn("[ai-log]", result.stdout + result.stderr)

        events_path = work / "dist" / "ai_activity.jsonl"
        event = json.loads(events_path.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(event["type"], "narration_finalized")
        self.assertEqual(event["source"], "narration sub-agent proofread")
        self.assertEqual(event["output"], expected.strip())
        self.assertEqual(event["word_count"], 11)

    def test_workflow_proofread_uses_the_ai_authored_second_task_id(self):
        corrected = "Maya found the wallet, then returned it to its owner."
        work, output_path, result = self.run_proofread(
            self.result(corrected, task_id="t2"), expected_id="t2")
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertEqual(output_path.read_text(encoding="utf-8"), corrected)

    def test_invalid_or_incomplete_helper_results_are_never_used(self):
        corrected = "Maya found the wallet and returned it to Leo."
        invalid_results = (
            {"results": []},
            {"results": [self.result(corrected)["results"][0],
                          self.result(corrected, task_id="t2")["results"][0]]},
            self.result(corrected, task_id="wrong"),
            self.result(corrected, kind="answer"),
            self.result(corrected, ok=False),
            self.result(corrected, status="failed"),
            self.result("   "),
            self.result("```text\n" + corrected + "\n```"),
        )
        for payload in invalid_results:
            with self.subTest(payload=payload):
                _, output_path, result = self.run_proofread(payload)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(output_path.exists())
                self.assertIn("draft was not used", result.stderr)

    def test_out_of_range_correction_does_not_trigger_a_rewrite_or_truncation(self):
        corrected = "Maya found the wallet."
        _, output_path, result = self.run_proofread(
            self.result(corrected), minimum=8, maximum=12)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(output_path.exists())
        self.assertIn("target 8–12 words", result.stderr)
        self.assertNotIn("Final short-story guard applied", result.stdout)

    def test_subagent_result_with_a_selected_username_is_rejected_not_rewritten(self):
        corrected = "noob found the wallet and returned it to Maya."
        _, output_path, result = self.run_proofread(
            self.result(corrected), cast_names="noob")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(output_path.exists())
        self.assertIn("included a selected username", result.stderr)

    def test_workflow_passes_the_same_word_budget_to_prepare_and_final_validation(self):
        workflow = (ROOT / ".github" / "workflows" / "main.yml").read_text(encoding="utf-8")
        validator = (ROOT / "tools" / "validate_short.py").read_text(encoding="utf-8")
        self.assertIn("MIN_WORDS=$((DURATION_SECONDS * 22 / 10))", workflow)
        self.assertIn("MAX_WORDS=$((DURATION_SECONDS * 27 / 10))", workflow)
        self.assertIn("--min-words \"$((DURATION_SECONDS * 22 / 10))\"", workflow)
        self.assertIn("--max-words \"$((DURATION_SECONDS * 27 / 10))\"", workflow)
        self.assertIn('parser.add_argument("--min-words"', validator)
        self.assertIn('parser.add_argument("--max-words"', validator)
        self.assertIn("args.min_words if args.min_words is not None", validator)
        self.assertIn("args.max_words if args.max_words is not None", validator)


if __name__ == "__main__":
    unittest.main()
