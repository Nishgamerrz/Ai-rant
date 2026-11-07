"""A finished video must never be refused for speaking a Roblox username.

Run #85 (30 s, `normal, noob`, medium) rendered all 1320 frames, muxed the
narration and then died on the last line of the quality gate:

    SHORT NOT APPROVED: narration reads out selected usernames: noob

The prompt already told the model not to do that. The text is now scrubbed
before the text-to-speech call - which is also what generates the captions - so
a username can never reach the voiceover, and the run cannot lose another render.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import prepare_narration  # noqa: E402
from prepare_narration import (  # noqa: E402
    cast_usernames, invented_names, scrub_usernames,
)
from validate_short import WORD_RE  # noqa: E402


class SpokenNameTests(unittest.TestCase):
    def test_a_spoken_username_is_replaced_with_a_first_name(self):
        text, replaced = scrub_usernames(
            "Noob found the jar first, and noob would not let go of it.",
            ["noob"], {"noob": "Ruby"})
        self.assertEqual(replaced, ["noob"])
        self.assertEqual(text, "Ruby found the jar first, and Ruby would not let go of it.")

    def test_the_gate_agrees_the_text_is_clean(self):
        text, _ = scrub_usernames(
            "normal counted the clocks while noob held the lantern.",
            ["normal", "noob"])
        spoken = {word.casefold() for word in WORD_RE.findall(text)}
        self.assertFalse({"normal", "noob"} & spoken)

    def test_a_username_inside_a_longer_word_is_left_alone(self):
        text, replaced = scrub_usernames("The noobmaster account was never named.", ["noob"])
        self.assertEqual(replaced, [])
        self.assertIn("noobmaster", text)

    def test_every_cast_member_gets_a_different_name(self):
        names = invented_names(["normal", "noob", "builder"], "a drowned station")
        self.assertEqual(len(set(names.values())), 3)
        for name in names.values():
            self.assertRegex(name, r"^[A-Z][a-z]+$")

    def test_the_same_cast_always_maps_to_the_same_people(self):
        first = invented_names(["normal", "noob"], "a drowned station")
        second = invented_names(["normal", "noob"], "a drowned station")
        self.assertEqual(first, second)
        # A different story may cast different people, but never the same name twice.
        other = invented_names(["normal", "noob"], "a lighthouse")
        self.assertEqual(len(set(other.values())), 2)

    def test_usernames_come_from_the_environment_or_the_cast_file(self):
        with mock.patch.dict(os.environ, {"CAST_NAMES": "normal, noob"}, clear=False):
            self.assertEqual(cast_usernames(), ["normal", "noob"])
        with tempfile.TemporaryDirectory() as temporary:
            cwd = os.getcwd()
            os.chdir(temporary)
            try:
                Path("dist").mkdir()
                Path("dist/characters.json").write_text(json.dumps(["normal", "noob"]))
                with mock.patch.dict(os.environ, {"CAST_NAMES": ""}, clear=False):
                    self.assertEqual(cast_usernames(), ["normal", "noob"])
            finally:
                os.chdir(cwd)

    def test_the_written_narration_has_no_username_left(self):
        """End to end through prepare_narration.main()."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            response = root / "narration_response.json"
            output = root / "narration.txt"
            story = ("In a world where the last train never leaves, noob keeps the station clock "
                     "wrong on purpose so nobody notices the missing hour. ")
            response.write_text(json.dumps({"response": json.dumps({"narration": story * 3})}))
            with mock.patch.dict(os.environ, {"CAST_NAMES": "noob"}, clear=False), \
                    mock.patch.object(sys, "argv", ["prepare_narration.py", str(response),
                                                    str(output), "60", "--truncate", "trains"]):
                prepare_narration.main()
            written = output.read_text(encoding="utf-8")
            self.assertFalse(re.search(r"(?<!\w)noob(?!\w)", written, re.IGNORECASE))
            self.assertTrue(written.strip())


    def test_the_workflow_scrubs_the_file_just_before_the_voice(self):
        workflow = (ROOT / ".github" / "workflows" / "main.yml").read_text(encoding="utf-8")
        self.assertIn("prepare_narration.py --scrub dist/narration.txt", workflow)
        self.assertLess(workflow.index("prepare_narration.py --scrub dist/narration.txt"),
                        workflow.index('--file dist/narration.txt --write-media'))

    def test_scrub_file_rewrites_in_place(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "narration.txt"
            path.write_text("Noob met normal by the crossing.\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"CAST_NAMES": "normal, noob"}, clear=False):
                self.assertEqual(prepare_narration.scrub_file(path), 0)
            written = path.read_text(encoding="utf-8")
            spokennames = {word.casefold() for word in WORD_RE.findall(written)}
            self.assertFalse({"normal", "noob"} & spokennames)

    def test_scrub_file_leaves_a_clean_script_untouched(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "narration.txt"
            path.write_text("Maya met Leo by the crossing.\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"CAST_NAMES": "normal, noob"}, clear=False):
                self.assertEqual(prepare_narration.scrub_file(path), 0)
            self.assertEqual(path.read_text(encoding="utf-8"), "Maya met Leo by the crossing.\n")


if __name__ == "__main__":
    unittest.main()
