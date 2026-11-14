from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from narration_delegation import (  # noqa: E402
    DelegationError,
    extract_tasks,
    prepare_proofread_request,
)


class NarrationDelegationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.response_path = self.root / "narration_response.json"
        self.creation_request_path = self.root / "story_creation_tasks.json"
        self.proofread_template_path = self.root / "story_proofread_template.json"
        self.first_draft_path = self.root / "dist" / "narration_first_draft.txt"
        self.narration = (
            "The boat stalled near the riverbank. Maya called for help, then stayed "
            "beside her friend until the lights came on."
        )
        self.reply = {
            "narration": self.narration,
            "public_rationale": "A small act of courage turns the delay into a warm ending.",
            "subagent_tasks": [
                {
                    "id": "t1", "kind": "write", "topic": "narration",
                    "instruction": "Create and develop the complete spoken story from this draft.",
                    "input": self.narration,
                },
                {
                    "id": "t2", "kind": "edit", "topic": "narration",
                    "instruction": "Proofread grammar and return the complete corrected narration only.",
                    "input": "USE_T1_CREATION_RESULT",
                },
            ],
        }

    def save_response(self, reply=None):
        content = json.dumps(reply if reply is not None else self.reply)
        self.response_path.write_text(json.dumps({
            "message": {"role": "assistant", "content": content},
            "response": content,
        }), encoding="utf-8")

    def extract(self, reply=None):
        self.save_response(reply)
        return extract_tasks(self.response_path, self.creation_request_path,
                             self.proofread_template_path, self.first_draft_path,
                             "120")

    def test_local_model_authors_separate_creation_and_proofreading_calls(self):
        result = self.extract()
        creation = json.loads(self.creation_request_path.read_text(encoding="utf-8"))
        template = json.loads(self.proofread_template_path.read_text(encoding="utf-8"))

        self.assertEqual([task["id"] for task in creation["tasks"]], ["t1"])
        self.assertEqual(creation["tasks"][0]["kind"], "write")
        self.assertEqual(creation["tasks"][0]["topic"], "narration")
        self.assertEqual(creation["tasks"][0]["input"], self.narration)
        self.assertEqual([task["id"] for task in template["tasks"]], ["t2"])
        self.assertEqual(template["tasks"][0]["kind"], "edit")
        self.assertEqual(template["tasks"][0]["topic"], "narration")
        self.assertEqual(template["tasks"][0]["input"], "USE_T1_CREATION_RESULT")
        self.assertEqual(template["public_rationale"], self.reply["public_rationale"])
        self.assertEqual(self.first_draft_path.read_text(encoding="utf-8"), self.narration + "\n")
        self.assertEqual(result["creation_task"], creation["tasks"][0])
        self.assertEqual(result["proofread_task"], template["tasks"][0])

    def test_only_the_exact_two_valid_ai_authored_tasks_are_forwarded(self):
        invalid_replies = []
        invalid_replies.append({**self.reply, "subagent_tasks": self.reply["subagent_tasks"][:1]})
        invalid_replies.append({**self.reply, "subagent_tasks": self.reply["subagent_tasks"] + [self.reply["subagent_tasks"][0]]})
        invalid_replies.append({**self.reply, "subagent_tasks": [
            {**self.reply["subagent_tasks"][0], "kind": "edit"}, self.reply["subagent_tasks"][1]]})
        invalid_replies.append({**self.reply, "subagent_tasks": [
            self.reply["subagent_tasks"][0], {**self.reply["subagent_tasks"][1], "topic": "map"}]})
        invalid_replies.append({**self.reply, "subagent_tasks": [
            {**self.reply["subagent_tasks"][0], "input": "short note only"}, self.reply["subagent_tasks"][1]]})
        invalid_replies.append({**self.reply, "subagent_tasks": [
            {**self.reply["subagent_tasks"][0], "input": 123}, self.reply["subagent_tasks"][1]]})
        invalid_replies.append({**self.reply, "subagent_tasks": [
            self.reply["subagent_tasks"][0], {**self.reply["subagent_tasks"][1], "instruction": "Review it."}]})
        for reply in invalid_replies:
            with self.subTest(tasks=reply["subagent_tasks"]):
                with self.assertRaises(DelegationError):
                    self.extract(reply)
                self.assertFalse(self.creation_request_path.exists())
                self.assertFalse(self.proofread_template_path.exists())

    def test_missing_or_private_public_rationale_is_rejected(self):
        for rationale in ("", "My private reasoning is to add a twist.", "x" * 321, {"reason": "private"}):
            with self.subTest(rationale=str(rationale)[:32]):
                reply = {**self.reply, "public_rationale": rationale}
                with self.assertRaises(DelegationError):
                    self.extract(reply)

    def test_proofreading_receives_the_complete_creation_result_verbatim(self):
        self.extract()
        created = (
            "Maya's boat stalled near the bank.\n"
            "She stayed with her friend until the rescue lights appeared."
        )
        result_path = self.root / "story_creation_results.json"
        result_path.write_text(json.dumps({"results": [{
            "id": "t1", "kind": "write", "ok": True, "status": "complete",
            "text": created,
        }]}), encoding="utf-8")
        proofread_request_path = self.root / "story_subagent_tasks.json"
        created_draft_path = self.root / "dist" / "narration_created_draft.txt"

        returned = prepare_proofread_request(
            self.proofread_template_path, result_path,
            proofread_request_path, created_draft_path)
        request = json.loads(proofread_request_path.read_text(encoding="utf-8"))
        task = request["tasks"][0]

        self.assertEqual(returned, created)
        self.assertEqual(task["id"], "t2")
        self.assertEqual(task["kind"], "edit")
        self.assertEqual(task["topic"], "narration")
        self.assertEqual(task["instruction"], self.reply["subagent_tasks"][1]["instruction"])
        self.assertEqual(task["input"], created)
        self.assertEqual(created_draft_path.read_text(encoding="utf-8"), created)

    def test_missing_failed_wrong_kind_or_fenced_creation_output_is_rejected(self):
        self.extract()
        cases = (
            {"results": []},
            {"results": [{"id": "other", "kind": "write", "ok": True,
                          "status": "complete", "text": "A complete story."}]},
            {"results": [{"id": "t1", "kind": "edit", "ok": True,
                          "status": "complete", "text": "A complete story."}]},
            {"results": [{"id": "t1", "kind": "write", "ok": False,
                          "status": "failed", "text": "A complete story."}]},
            {"results": [{"id": "t1", "kind": "write", "ok": True,
                          "status": "complete", "text": "```text\\nA story.\\n```"}]},
        )
        for payload in cases:
            with self.subTest(payload=payload):
                result_path = self.root / "story_creation_results.json"
                result_path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises(DelegationError):
                    prepare_proofread_request(
                        self.proofread_template_path, result_path,
                        self.root / "story_subagent_tasks.json",
                        self.root / "dist" / "narration_created_draft.txt")


if __name__ == "__main__":
    unittest.main()
