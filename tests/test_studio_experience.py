from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class StudioExperienceTests(unittest.TestCase):
    def test_mobile_workflow_form_hides_manual_audio_id_and_supports_auto_or_explicit_theme(self):
        workflow = (ROOT / ".github/workflows/main.yml").read_text(encoding="utf-8")
        self.assertNotIn("narration_audio_asset_id", workflow)
        self.assertNotIn("--audio-asset-id \"$NARRATION_AUDIO_ASSET_ID\"", workflow)
        self.assertIn("Optional theme cue (e.g., daylight); blank = AI derives it from your story.", workflow)
        self.assertIn('"${WORLD_THEME:-AUTO FROM STORY}"', workflow)
        self.assertIn("treat the user's cue as a required design constraint", workflow)
        self.assertIn("daylight cue means a clearly bright, naturally sunlit daytime world", workflow)

    def test_builder_packages_playable_place_with_world_cast_and_captions(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            map_plan = {
                "name": "Sunny Plaza",
                "theme": "A bright town with a market and a fountain.",
                "ground_color": [20, 20, 20],
                "props": [
                    {"name": f"AI landmark {index}", "shape": "Block", "material": "Brick",
                     "position": [index - 3, 5, 0], "size": [8, 10, 8], "color": [80, 140, 220]}
                    for index in range(8)
                ],
                "character_placements": [
                    {"username": "LeadUser", "role": "lead", "position": [0, 0, 24]},
                    {"username": "FriendUser", "role": "supporting", "position": [-4, 0, 24]},
                ],
                "camera_shots": [
                    {"time": 0, "position": [0, 30, 75], "target": [0, 3, 24], "transition": "smooth"},
                    {"time": 60, "position": [-12, 14, 35], "target": [0, 3, 24], "transition": "snap"},
                ],
            }
            (work / "map.json").write_text(json.dumps(map_plan), encoding="utf-8")
            (work / "cast.json").write_text(json.dumps(["LeadUser", "FriendUser"]), encoding="utf-8")
            (work / "narration.txt").write_text("A student returns a lost wallet.", encoding="utf-8")
            (work / "captions.srt").write_text(
                "1\n00:00:00,000 --> 00:00:02,000\nA student returns a lost wallet.\n",
                encoding="utf-8",
            )
            output = work / "Experience.rbxlx"
            command = [
                sys.executable, str(ROOT / "tools/build_studio_experience.py"),
                "--map", str(work / "map.json"), "--cast", str(work / "cast.json"),
                "--duration", "60", "--narration", str(work / "narration.txt"),
                "--srt", str(work / "captions.srt"),
                "--audio-asset-id", "12345", "--output", str(output),
                "--lua-output", str(work / "World.lua"), "--readme", str(work / "README.md"),
            ]
            subprocess.run(command, check=True, capture_output=True, text=True)

            root = ET.parse(output).getroot()
            server = root.find('.//Item[@class="Script"]/Properties/ProtectedString')
            client = root.find('.//Item[@class="LocalScript"]/Properties/ProtectedString')
            self.assertIsNotNone(server)
            self.assertIsNotNone(client)
            self.assertIn('for _, castMember in ipairs(CONFIG.cast or {}) do', server.text)
            self.assertIn('CreateHumanoidModelFromUserIdAsync', server.text)
            self.assertGreaterEqual(len(root.findall('.//Item[@class="Part"]')), 10)
            self.assertIsNotNone(root.find('.//Item[@class="Sky"]'))
            self.assertIn('SkyboxBk = "rbxasset://textures/sky/sky512_bk.tex"', server.text)
            self.assertIn('World Title Sign', server.text)
            part_names = {node.text for node in root.findall('.//Item[@class="Part"]/Properties/string[@name="Name"]')}
            self.assertIn('AI landmark 0', part_names)
            self.assertIn('NarrationCaption', client.text)
            self.assertIn('A student returns a lost wallet.', client.text)
            self.assertIn('12345', client.text)
            self.assertIn('caption.Visible = true', client.text)
            self.assertNotIn('motor.Transform', client.text)
            self.assertNotIn('Story Lead Torso', server.text)
            self.assertTrue((work / "README.md").exists())
            self.assertTrue((work / "World.lua").exists())

    def test_prompt_themed_map_requires_full_ai_authored_scene(self):
        from tools.build_story_map import validate

        props = [
            {"name": f"Theme part {index}", "shape": "Block", "material": "SmoothPlastic",
             "position": [index - 25, 4, 0], "size": [4, 8, 4], "color": [95, 145, 210]}
            for index in range(120)
        ]
        plan = {"name": "Crystal Reef", "theme": "A luminous underwater crystal kingdom",
                "ground_material": "Slate", "ground_color": [54, 113, 140], "props": props}
        normalized = validate(plan, 60, (), min_props=70)
        self.assertEqual(normalized["theme"], plan["theme"])
        self.assertEqual(normalized["ground_material"], "Slate")
        self.assertEqual(len(normalized["props"]), 120)
        with self.assertRaises(ValueError):
            validate({**plan, "props": props[:69]}, 60, (), min_props=70)

    def test_captions_have_valid_subtitle_and_fallback_cues(self):
        from tools.build_studio_experience import fallback_captions, parse_srt

        fallback = fallback_captions("A long story begins. It reaches a kind ending.", 30)
        self.assertGreaterEqual(len(fallback), 2)
        self.assertEqual(fallback[0]["start"], 0)
        self.assertEqual(fallback[-1]["finish"], 30)
        with tempfile.TemporaryDirectory() as temporary:
            subtitles = Path(temporary) / "captions.srt"
            subtitles.write_text("\ufeff1\n00:00:00.000 --> 00:00:02.500\nVisible caption text.\n", encoding="utf-8")
            parsed = parse_srt(subtitles)
            self.assertEqual(parsed[0]["text"], "Visible caption text.")
            self.assertEqual(parsed[0]["finish"], 2.5)

    def test_report_and_zip_include_generation_summary_and_studio_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            dist = work / "dist"
            dist.mkdir()
            plan = {"name": "Crystal Reef", "theme": "A crystal garden", "props": [{"name": "Glass Arch"}], "camera_shots": [{"time": 0}]}
            (work / "map.json").write_text(json.dumps(plan), encoding="utf-8")
            (work / "cast.json").write_text("[]", encoding="utf-8")
            (work / "research.json").write_text("[]", encoding="utf-8")
            (work / "summary.txt").write_text("A crystal garden with a glass arch and a gentle camera tour.", encoding="utf-8")
            (dist / "Roblox_Studio_Experience.rbxlx").write_text("<roblox/>", encoding="utf-8")
            (dist / "narration.srt").write_text("1\\ncue", encoding="utf-8")
            (dist / "Roblox_2K_YouTube_Short.mp4").write_bytes(b"mp4 test fixture")
            (dist / "short_silent.mp4").write_bytes(b"temporary silent video")
            subprocess.run([
                sys.executable, str(ROOT / "tools/package_studio_deliverables.py"),
                "--directory", str(dist), "--map", str(work / "map.json"),
                "--cast", str(work / "cast.json"), "--research", str(work / "research.json"),
                "--summary", str(work / "summary.txt"), "--model", "qwen3:test",
                "--voice", "en-US-GuyNeural", "--duration", "60",
            ], check=True, capture_output=True, text=True)
            pdf = dist / "AI_Design_and_Tools_Report.pdf"
            bundle = dist / "Roblox_Studio_Complete_Package.zip"
            self.assertTrue(pdf.read_bytes().startswith(b"%PDF"))
            with zipfile.ZipFile(bundle) as archive:
                self.assertIn("AI_Design_and_Tools_Report.pdf", archive.namelist())
                self.assertIn("Roblox_Studio_Experience.rbxlx", archive.namelist())
                self.assertIn("Roblox_2K_YouTube_Short.mp4", archive.namelist())
                self.assertNotIn("short_silent.mp4", archive.namelist())
                self.assertNotIn("Roblox_Studio_Complete_Package.zip", archive.namelist())

    def test_long_bracket_avoids_closing_delimiter_collision(self):
        from tools.build_studio_experience import long_bracket

        value = "embedded ]] content"
        wrapped = long_bracket(value)
        self.assertTrue(wrapped.startswith("[=["))
        self.assertTrue(wrapped.endswith("]=]"))
        self.assertIn(value, wrapped)


if __name__ == "__main__":
    unittest.main()
