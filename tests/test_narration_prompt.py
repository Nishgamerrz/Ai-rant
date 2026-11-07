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
        self.assertIn('default: \'In a world where gravity switches off for exactly ten minutes',
                      WORKFLOW)
        self.assertIn('best when it starts "In a world where ..."', WORKFLOW)

    def test_the_sub_agent_is_asked_to_check_the_line(self):
        self.assertIn("whether that opening line lands and whether any name reads like a username",
                      WORKFLOW)


if __name__ == "__main__":
    unittest.main()
