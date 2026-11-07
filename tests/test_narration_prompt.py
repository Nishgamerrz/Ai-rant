"""The story prompt has to make the model write a hook, not a synopsis.

A short lives or dies on its first line: it is the first caption on screen and
the only thing a viewer hears before deciding to stay. The prompt therefore asks
for one "In a world where ..." sentence that plants the world and the hook at
once, and hands the model a shape to copy.
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github" / "workflows" / "main.yml").read_text(encoding="utf-8")


class OpeningLineTests(unittest.TestCase):
    def test_the_prompt_asks_for_a_single_hook_line(self):
        self.assertIn("OPENING LINE (required)", WORKFLOW)
        self.assertIn('in the "In a world where ..." spirit', WORKFLOW)

    def test_it_gives_the_model_a_shape_to_copy(self):
        self.assertIn('"In a world where gravity clocks off for ten minutes every morning, '
                      'Max sleeps through it."', WORKFLOW)

    def test_it_rules_out_titles_questions_and_what_if(self):
        for forbidden in ("never a title", "a question to the viewer", 'the words "what if"'):
            self.assertIn(forbidden, WORKFLOW)

    def test_the_line_is_tied_to_the_first_caption(self):
        self.assertIn("That line is the first caption on screen", WORKFLOW)

    def test_it_survives_the_repair_rounds(self):
        self.assertIn("preserving the hook, choice, and ending", WORKFLOW)

    def test_the_default_topic_is_one_in_a_world_where_line(self):
        start = WORKFLOW.index("      story_topic:")
        block = WORKFLOW[start:WORKFLOW.index("      character_usernames:", start)]
        self.assertIn("default: 'In a world where", block)
        self.assertNotIn("gravity", block)
        self.assertIn('"In a world where ..." works best', WORKFLOW)

    def test_the_sub_agent_is_offered_for_the_hard_parts(self):
        self.assertIn("handwriting a tricky sentence", WORKFLOW)
        self.assertIn("checking whether a name sounds like a real person", WORKFLOW)


if __name__ == "__main__":
    unittest.main()


class StoryTopicIdeasTests(unittest.TestCase):
    """A list of ready-to-paste premised topics, so a run never starts blank."""

    def setUp(self):
        self.topics = (ROOT / "STORY_TOPICS.md").read_text(encoding="utf-8")
        self.lines = [line for line in self.topics.splitlines()
                      if line.strip() and line[0].isdigit()]

    def test_the_list_exists_and_is_long_enough_to_pick_from(self):
        self.assertGreaterEqual(len(self.lines), 20)

    def test_every_topic_is_one_screen_short_line(self):
        for line in self.lines:
            text = line.split(". ", 1)[1]
            self.assertLessEqual(len(text.split()), 40, line)
            self.assertNotIn("\n", text)

    def test_most_topics_start_with_a_world_rule(self):
        world = [line for line in self.lines if "In a world where" in line]
        self.assertGreaterEqual(len(world), len(self.lines) * 0.6)

    def test_the_form_points_at_the_list(self):
        self.assertIn("24 ideas in STORY_TOPICS.md", WORKFLOW)

    def test_the_list_explains_what_makes_a_topic_work(self):
        self.assertIn("One everyday problem", self.topics)
        self.assertIn("A specific ending moment", self.topics)
