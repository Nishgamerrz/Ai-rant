"""Shared parent/sub-agent tools stay useful while remaining workspace-bounded."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import agent_tools  # noqa: E402
import nish_agent  # noqa: E402


class SharedToolTests(unittest.TestCase):
    def test_exactly_twenty_five_tools_are_shared(self):
        self.assertEqual(len(agent_tools.TOOL_NAMES), 25)
        for name in agent_tools.TOOL_NAMES:
            self.assertIn(name, agent_tools._DISPATCH)
        self.assertIn("inspect_image", agent_tools.TOOL_GUIDE)
        self.assertIn("find_model_reference", agent_tools.TOOL_GUIDE)
        self.assertIn("you must write every requested call yourself", agent_tools.TOOL_GUIDE)
        for name in ("analyze_short_script", "plan_short_lighting", "audit_roblox_map",
                     "audit_short_captions", "inspect_roblox_short"):
            self.assertIn(name, agent_tools.TOOL_GUIDE)

    def test_short_story_and_lighting_tools_analyze_auto_planning_cues(self):
        story = ("In a world where night arrives early, Ruby guards a lantern. "
                 "At sunrise, her brother finds the hidden note. By sunset, they share the wish.")
        script = agent_tools.execute_tool("analyze_short_script", {
            "text": story, "duration": 60,
        }, ROOT)
        lighting = agent_tools.execute_tool("plan_short_lighting", {
            "text": story, "duration": 60,
        }, ROOT)
        self.assertTrue(script["ok"])
        self.assertEqual(script["story_beats"][0]["role"], "hook")
        self.assertGreater(script["word_count"], 10)
        self.assertTrue(lighting["ok"])
        self.assertEqual(lighting["global_hour"], "night")
        self.assertEqual(lighting["scene_hour_cues"], ["night", "dawn", "sunset"])
        self.assertEqual(len(lighting["suggested_overrides"]), 2)

    def test_map_and_caption_auditors_report_actionable_short_metrics(self):
        from build_story_map import default_camera_shots, default_plan

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = default_plan()
            plan["time_of_day"] = "night"
            plan["camera_shots"] = default_camera_shots(90, ["Lead"])
            plan["camera_shots"][0]["time_of_day"] = "night"
            plan["camera_shots"][1]["time_of_day"] = "sunset"
            (root / "map.json").write_text(json.dumps(plan), encoding="utf-8")
            map_report = agent_tools.execute_tool("audit_roblox_map", {
                "path": "map.json", "duration": 90, "cast": ["Lead"],
            }, root)
            self.assertTrue(map_report["ok"], map_report)
            self.assertEqual(map_report["global_hour"], "night")
            self.assertIn({"time": 0.0, "hour": "night"}, map_report["scene_hour_overrides"])
            self.assertTrue(map_report["world_parts"] >= 8)

            plan["camera_shots"][2]["position"] = [999, 0, 0]
            (root / "bad-camera-map.json").write_text(json.dumps(plan), encoding="utf-8")
            repaired_report = agent_tools.execute_tool("audit_roblox_map", {
                "path": "bad-camera-map.json", "duration": 90, "cast": ["Lead"],
            }, root)
            self.assertTrue(repaired_report["ok"], repaired_report)
            self.assertTrue(any("safe default path" in warning
                                for warning in repaired_report["warnings"]))

            captions = root / "captions.srt"
            captions.write_text(
                "1\n00:00:00,000 --> 00:00:00,400\nOpen\n\n"
                "2\n00:00:00,450 --> 00:00:00,850\nThe\n\n"
                "3\n00:00:00,900 --> 00:00:01,400\nDoor.\n",
                encoding="utf-8")
            caption_report = agent_tools.execute_tool("audit_short_captions", {
                "path": "captions.srt", "duration": 2,
            }, root)
            self.assertTrue(caption_report["ok"], caption_report)
            self.assertEqual(caption_report["single_word_cues"], 3)
            self.assertEqual(caption_report["largest_gap_seconds"], 0.05)

    def test_roblox_short_visual_audit_reports_missing_video_clearly(self):
        with tempfile.TemporaryDirectory() as temp:
            result = agent_tools.execute_tool("inspect_roblox_short", {
                "path": "missing.mp4",
            }, Path(temp))
            self.assertFalse(result["ok"])
            self.assertIn("video not found", result["error"])

    def test_roblox_short_visual_audit_uses_bounded_runner_and_relative_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "short.mp4").write_bytes(b"test video")
            with patch("rbx_short_tools.subprocess.run", return_value=SimpleNamespace(
                    returncode=0, stdout="MP4 audit passed", stderr="")) as run:
                result = agent_tools.execute_tool("inspect_roblox_short", {
                    "path": "short.mp4", "report": "reports/audit.md",
                    "frames_dir": "preview", "samples": 99, "timeout": 999,
                }, root)
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["report"], "reports/audit.md")
            self.assertEqual(result["frames_dir"], "preview")
            self.assertIn("MP4 audit passed", result["diagnostics"])
            command = run.call_args.args[0]
            self.assertIn(str(ROOT / "tools" / "inspect_short.py"), command)
            self.assertEqual(command[command.index("--samples") + 1], "12")
            self.assertEqual(run.call_args.kwargs["timeout"], 300)
            collision = agent_tools.execute_tool("inspect_roblox_short", {
                "path": "short.mp4", "report": "short.mp4",
            }, root)
            self.assertFalse(collision["ok"])
            self.assertIn("must not overwrite", collision["error"])

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
