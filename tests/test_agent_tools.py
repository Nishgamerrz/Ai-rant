"""Shared parent/sub-agent tools stay useful while remaining workspace-bounded."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import agent_tools  # noqa: E402
import nish_agent  # noqa: E402


class SharedToolTests(unittest.TestCase):
    def test_exactly_twenty_tools_are_shared(self):
        self.assertEqual(len(agent_tools.TOOL_NAMES), 20)
        for name in agent_tools.TOOL_NAMES:
            self.assertIn(name, agent_tools._DISPATCH)
        self.assertIn("inspect_image", agent_tools.TOOL_GUIDE)
        self.assertIn("find_model_reference", agent_tools.TOOL_GUIDE)
        self.assertIn("you must write every requested call yourself", agent_tools.TOOL_GUIDE)

    def test_paths_cannot_escape_the_workspace(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for path in ("../outside", "/etc/passwd", "a/../../outside"):
                with self.assertRaises(ValueError):
                    agent_tools.safe_path(root, path)
            self.assertEqual(agent_tools.safe_path(root, "folder/file.txt"),
                             (root / "folder" / "file.txt").resolve())

    def test_create_read_search_and_exact_edit_share_one_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            created = agent_tools.execute_tool("create_file", {
                "path": "notes/face.txt", "content": "one dark eyebrow pair\n"}, root)
            self.assertTrue(created["ok"])
            self.assertEqual(agent_tools.execute_tool("read_file", {"path": "notes/face.txt"}, root)["content"],
                             "one dark eyebrow pair\n")
            self.assertEqual(len(agent_tools.execute_tool("search_files", {
                "query": "dark eyebrow", "path": "."}, root)["matches"]), 1)
            edited = agent_tools.execute_tool("edit_file", {
                "path": "notes/face.txt", "old_text": "dark eyebrow", "new_text": "bold dark eyebrow"}, root)
            self.assertTrue(edited["ok"])
            (root / "notes" / "duplicate.txt").write_text("same same", encoding="utf-8")
            ambiguous = agent_tools.execute_tool("edit_file", {
                "path": "notes/duplicate.txt", "old_text": "same", "new_text": "other"}, root)
            self.assertFalse(ambiguous["ok"])

    def test_asset_image_download_refuses_private_networks(self):
        for url in ("http://example.com/image.png", "https://127.0.0.1/image.png",
                    "https://localhost/image.png", "https://10.0.0.1/image.png"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                agent_tools._public_https(url)

    def test_video_and_zip_tools_return_clear_missing_input_errors(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertFalse(agent_tools.execute_tool("inspect_video", {"path": "missing.mp4"}, root)["ok"])
            self.assertFalse(agent_tools.execute_tool("package_files", {"path": "missing"}, root)["ok"])

    def test_main_agent_flattens_only_model_authored_nested_tool_arguments(self):
        normalized = nish_agent.normalize_agent_tool_call({
            "name": "subagent", "arguments": {"instruction": "Inspect the map", "use_tools": True}})
        self.assertEqual(normalized["tool"], "subagent")
        self.assertEqual(normalized["instruction"], "Inspect the map")
        self.assertTrue(normalized["use_tools"])

    def test_main_agent_retries_and_fails_if_it_never_authors_its_delegation(self):
        source = (ROOT / "tools" / "nish_agent.py").read_text(encoding="utf-8")
        self.assertIn("if not delegation_satisfied and not authored_subagent:", source)
        self.assertIn("local model never authored the mandatory subagent call", source)
        self.assertIn("raise RuntimeError(\"local model failed to author a non-empty subagent tool call", source)


if __name__ == "__main__":
    unittest.main()
