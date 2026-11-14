from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
EXPECTED_PROMPT = (
    "In this world, the last person to fall asleep each night gets one wish, "
    "so two brothers keep each other awake on purpose in their shared bedroom."
)


class DefaultStoryPromptTests(unittest.TestCase):
    def test_ui_workflow_and_story_ideas_use_the_same_premise_and_setting(self):
        paths = (
            ROOT / ".github/workflows/main.yml",
            ROOT / "web/components/NewChatModal.tsx",
            ROOT / "web/app/rbxshort/page.tsx",
            ROOT / "STORY_TOPICS.md",
        )
        for path in paths:
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertIn(EXPECTED_PROMPT, path.read_text(encoding="utf-8"))

        workflow = paths[0].read_text(encoding="utf-8")
        self.assertEqual(workflow.count(EXPECTED_PROMPT), 2, "dispatch and reusable-workflow defaults must agree")

    def test_fallback_to_the_users_wording_keeps_the_premise_and_shared_bedroom(self):
        from gemini_topic import refine, starts_with_premise

        self.assertTrue(starts_with_premise(EXPECTED_PROMPT))
        with patch("gemini_topic.call_any", return_value=("At midnight, two brothers try to stay awake.", "gemini")):
            result = refine(EXPECTED_PROMPT, api_key="test-key")

        self.assertFalse(result["ok"])
        self.assertEqual(result["text"], EXPECTED_PROMPT)
        self.assertIn("shared bedroom", result["text"])


if __name__ == "__main__":
    unittest.main()
