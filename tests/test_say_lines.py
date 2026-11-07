"""The workflow's own status lines use the same palette as the AI log.

Before this, the pipeline spoke in plain ``echo``: a section heading, a warning
and a successful gate all looked identical, and the only colour on screen was
the model's own output. These tests pin the helper and the conversion, and pin
the lines that must stay plain because they are written to a file rather than
shown to a person.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github" / "workflows" / "main.yml").read_text(encoding="utf-8")
SAY = ROOT / "tools" / "say.py"


def say(*args: str, colour: bool = False) -> str:
    env = {**os.environ}
    env.pop("AI_COLOR", None)
    env["NO_COLOR"] = "1"
    if colour:
        env.pop("NO_COLOR")
        env["AI_COLOR"] = "1"
    result = subprocess.run([sys.executable, str(SAY), *args], capture_output=True,
                            text=True, env=env, check=True)
    return result.stdout


class SayHelperTests(unittest.TestCase):
    def test_it_prints_the_text_with_a_colour_when_the_console_has_colour(self):
        out = say("warning", "Blueprint rejected; correcting.", colour=True)
        self.assertIn("Blueprint rejected; correcting.", out)
        self.assertTrue(out.startswith("\x1b[38;5;"), out[:20])
        self.assertTrue(out.endswith("\x1b[0m\n"), repr(out[-12:]))

    def test_it_stays_plain_when_colour_is_off(self):
        self.assertEqual(say("warning", "Blueprint rejected; correcting."),
                         "Blueprint rejected; correcting.\n")

    def test_each_kind_gets_its_own_colour(self):
        warn = say("warning", "x", colour=True)
        ok = say("success", "x", colour=True)
        tool = say("tool", "x", colour=True)
        self.assertEqual(len({warn, ok, tool}), 3)

    def test_an_unknown_kind_still_prints_the_text(self):
        self.assertEqual(say("nonsense", "hello", "world"), "hello world\n")

    def test_it_says_how_to_call_it(self):
        result = subprocess.run([sys.executable, str(SAY)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("say.py <kind> <text...>", result.stderr)


class WorkflowNarrationTests(unittest.TestCase):
    def test_the_story_step_announces_itself_in_colour(self):
        self.assertIn('python tools/say.py plan "Token budget for this '
                      '${DURATION_SECONDS}s story:', WORKFLOW)

    def test_a_retry_is_not_the_same_colour_as_a_success(self):
        self.assertIn('python tools/say.py success "Narration passed the', WORKFLOW)
        self.assertIn('python tools/say.py warning "Blueprint rejected', WORKFLOW)
        self.assertIn('python tools/say.py tool "The AI asked for more web research', WORKFLOW)

    def test_the_summary_file_is_still_written_plain(self):
        # These echo into $GITHUB_STEP_SUMMARY: an escape code there would show up
        # as literal junk in the run summary page.
        self.assertIn('echo "## Selected narrator"', WORKFLOW)
        self.assertIn('echo "- Style: $VOICE_STYLE', WORKFLOW)
        self.assertIn('echo "## Final ZIP bundle"', WORKFLOW)

    def test_files_never_get_a_coloured_line(self):
        for line in WORKFLOW.splitlines():
            if "tools/say.py" in line:
                self.assertNotIn(">", line.replace("->", ""), line)
                self.assertNotIn(">>", line, line)

    def test_the_rest_of_the_console_tools_are_coloured(self):
        helper = (ROOT / "tools" / "console_style.py").read_text(encoding="utf-8")
        self.assertIn('"plan"', helper)
        for tool in ("ai_web_search.py", "gemini_subagent.py", "gemini_topic.py"):
            text = (ROOT / "tools" / tool).read_text(encoding="utf-8")
            self.assertIn("paint(", text, tool)


if __name__ == "__main__":
    unittest.main()
