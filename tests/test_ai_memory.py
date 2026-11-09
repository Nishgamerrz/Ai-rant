"""The AI must remember the whole run, and must not mistake the workflow for the user.

Every call used to be one `user` message rebuilt from scratch, so a later step
could ask for facts it already had, or write as if talking to the person who
filled in the form. The run now keeps `dist/ai_memory.json` and sends a real
`system` message in front of every request.
"""
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

import ai_memory  # noqa: E402

WORKFLOW = ROOT / ".github" / "workflows" / "main.yml"


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.memory_path = self.root / "dist" / "ai_memory.json"

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(ROOT / "tools" / "ai_memory.py"),
             "--memory", str(self.memory_path), *args],
            cwd=self.root, capture_output=True, text=True)

    def test_facts_survive_between_steps(self):
        self.assertEqual(self._run("--set", "story_topic=a world where gravity naps",
                                   "--set", "cast=normal, noob").returncode, 0)
        self.assertEqual(self._run("--fact", "kept the bakery model").returncode, 0)
        memory = ai_memory.load(self.memory_path)
        self.assertEqual(memory["story_topic"], "a world where gravity naps")
        self.assertEqual(memory["cast"], "normal, noob")
        self.assertIn("kept the bakery model", memory["facts"])

    def test_the_narration_is_remembered_from_a_file(self):
        (self.root / "dist").mkdir(parents=True, exist_ok=True)
        (self.root / "dist" / "narration.txt").write_text("Max waits.\n", encoding="utf-8")
        self._run("--set-file", "narration=dist/narration.txt")
        self.assertIn("Max waits", ai_memory.load(self.memory_path)["narration"])

    def test_subagent_work_and_its_seconds_are_remembered(self):
        (self.root / "dist").mkdir(parents=True, exist_ok=True)
        results = self.root / "subagent_results.json"
        results.write_text(json.dumps({"results": [
            {"id": "t1", "kind": "write", "ok": True, "provider": "groq",
             "seconds": 12.4, "applied_to": "dist/Roblox_Story_Map.json",
             "text": "designed the bakery shell"}]}), encoding="utf-8")
        self._run("--add-subagent", "subagent_results.json")
        task = ai_memory.load(self.memory_path)["subagent_tasks"][0]
        self.assertEqual(task["seconds"], 12.4)
        self.assertEqual(task["applied_to"], "dist/Roblox_Story_Map.json")
        self.assertIn("bakery", task["summary"])

    def test_the_system_prompt_names_who_is_speaking_and_keeps_the_memory(self):
        memory = ai_memory.empty_memory()
        memory.update({"story_topic": "a world where gravity naps", "duration": "145",
                       "duration_label": "2:25", "cast": "normal, noob",
                       "narration": "Max waits for Ben to fall asleep."})
        ai_memory.add_fact(memory, "the world is called Naptime Heights")
        text = ai_memory.system_prompt(memory)
        self.assertIn("SYSTEM MESSAGE", text)
        self.assertIn("not the person who filled in the form", text)
        self.assertIn("never say \"you\" to the user", text)
        self.assertIn("a world where gravity naps", text)
        self.assertIn("145 seconds (2:25)", text)
        self.assertIn("normal, noob", text)
        self.assertIn("Max waits for Ben to fall asleep.", text)
        self.assertIn("Naptime Heights", text)

    def test_it_tells_the_model_not_to_ask_for_what_it_already_knows(self):
        text = ai_memory.system_prompt(ai_memory.empty_memory())
        self.assertIn("never ask the user a question", text)
        self.assertIn("already in RUN MEMORY", text)
        self.assertIn("Never invent a new cast", text)

    def test_duplicates_are_not_stored_twice(self):
        memory = ai_memory.empty_memory()
        ai_memory.add_fact(memory, "same note")
        ai_memory.add_fact(memory, "same note")
        self.assertEqual(memory["facts"], ["same note"])

    def test_a_corrupt_memory_file_is_not_fatal(self):
        self.memory_path.parent.mkdir(parents=True, exist_ok=True)
        self.memory_path.write_text("{not json", encoding="utf-8")
        memory = ai_memory.load(self.memory_path)
        self.assertEqual(memory["facts"], [])


class WorkflowMemoryTests(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text(encoding="utf-8")

    def test_every_ai_request_sends_a_real_system_message(self):
        # Seven jq-built requests (story, story re-ask, narration repair, world
        # plan, helper round, map retry, creation summary) + the python-built
        # confirmation request.
        self.assertEqual(self.text.count('role:"system"'), 7)
        self.assertIn("{'role': 'system', 'content': system}", self.text)

    def test_the_memory_is_filled_before_the_first_call_and_reused_after(self):
        self.assertIn('--set "story_topic=${STORY_TOPIC}"', self.text)
        self.assertIn("--set-file narration=dist/narration.txt", self.text)
        self.assertIn("--add-subagent subagent_results.json", self.text)
        # The topic is remembered before the story request is even built.
        self.assertLess(self.text.index('--set "story_topic='),
                        self.text.index("narration_request.json"))

    def test_each_run_starts_with_an_empty_memory(self):
        # Run #109 was told "a world where gravity naps" on its first story call
        # because the memory file still held the previous run's topic.
        self.assertIn("python tools/ai_memory.py --reset", self.text)
        self.assertLess(self.text.index("python tools/ai_memory.py --reset"),
                        self.text.index("story narration"))

    def test_the_memory_holds_the_world_before_the_summary(self):
        self.assertIn("ai_memory.add_fact(memory, 'Final world:", self.text)


if __name__ == "__main__":
    unittest.main()
