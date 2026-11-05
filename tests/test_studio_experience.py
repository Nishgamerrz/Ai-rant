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
        username_step = workflow.index("- name: Require a username for the avatar cast")
        model_step = workflow.index("- name: Download the selected AI model for story and world/camera planning")
        self.assertLess(username_step, model_step)
        self.assertIn("description: 'Enter 1–6 Roblox usernames only (first is lead); checks users/<username>.rbxm automatically.'\n        required: false", workflow)
        self.assertIn("Optional theme cue (e.g., daylight); blank = AI derives it from your story.", workflow)
        self.assertIn('"${WORLD_THEME:-AUTO FROM STORY}"', workflow)
        self.assertIn("treat the user's cue as a required design constraint", workflow)
        self.assertIn("daylight cue means a clearly bright, naturally sunlit daytime world", workflow)
        self.assertIn("ROBLOX_OPEN_CLOUD_API_KEY: ${{ secrets.ROBLOX_OPEN_CLOUD_API_KEY }}", workflow)
        self.assertIn("public Roblox Users API resolves entered usernames to IDs keylessly", workflow)
        self.assertIn("users/<username>.rbxm", workflow)
        self.assertIn("Mesh access:", workflow)
        renderer_tests = (ROOT / ".github/workflows/studio-experience-tests.yml").read_text(encoding="utf-8")
        self.assertIn("npm run test:avatar-rig", renderer_tests)
        self.assertIn("npm run test:module-resolution", renderer_tests)
        self.assertIn("uses: actions/cache/restore@v4", workflow)
        disk_cleanup_step = workflow.index("- name: Reclaim runner disk space for the selected model")
        cache_restore_step = workflow.index("- name: Restore cached selected Ollama model")
        model_pull_step = workflow.index("- name: Download the selected AI model for story and world/camera planning")
        self.assertLess(disk_cleanup_step, cache_restore_step)
        self.assertLess(cache_restore_step, model_pull_step)
        self.assertIn("id: disk-space", workflow)
        self.assertIn("12 * 1024 * 1024", workflow)
        self.assertIn("8 * 1024 * 1024", workflow)
        self.assertIn("steps.disk-space.outputs.cache_restore_allowed == 'true'", workflow)
        self.assertIn("sudo rm -rf /usr/local/lib/android/sdk", workflow)
        self.assertIn("8 GiB for download and working files", workflow)
        self.assertIn("rm -f ollama.tar.zst", workflow)
        self.assertIn("ollama-${{ runner.os }}-${{ inputs.model_quality }}-${{ inputs.model_quality == 'hard' && 'qwen3-8b-v3' || 'qwen3-v2' }}", workflow)
        self.assertIn("fast) SELECTED_MODEL=qwen3:1.7b", workflow)
        self.assertIn("medium) SELECTED_MODEL=qwen3:4b", workflow)
        self.assertIn("hard) SELECTED_MODEL=qwen3:8b", workflow)
        self.assertNotIn("qwen3:14b", workflow)
        self.assertIn("for attempt in 1 2; do", workflow)
        self.assertIn("--min-props 8 --target-props 220", workflow)
        self.assertIn("num_predict:6000", workflow)
        self.assertIn("--max-time 480", workflow)
        self.assertIn("--fallback --theme", workflow)
        self.assertIn("producing at least 220 individually named editable Parts", workflow)
        self.assertIn("Show the public AI build plan and tools", workflow)
        self.assertIn("not private chain-of-thought", workflow)

    def test_studio_runtime_uses_native_rbxm_animation_tracks(self):
        from tools.build_studio_experience import make_config, server_lua

        profiles = [{
            "username": "Normal",
            "rbxm_animation_ids": {"idle": "rbxassetid://123", "walk": "rbxassetid://456"},
        }]
        config = make_config({}, [{"username": "Normal", "role": "lead", "position": [0, 0, 0]}],
                             60, "", [], "", profiles)
        self.assertEqual(config["rbxm_animations"]["normal"]["idle"], "rbxassetid://123")
        runtime = server_lua(json.dumps(config))
        self.assertIn("animator:LoadAnimation(animation)", runtime)
        self.assertIn("tracks.walk", runtime)
        self.assertIn("humanoid:MoveTo(waypoints[index])", runtime)
        self.assertIn('FindFirstChild("Animate")', runtime)

    def test_mp4_renderer_applies_procedural_motion_to_authentic_avatar_models(self):
        renderer = (ROOT / "tools/video_renderer/render_short.mjs").read_text(encoding="utf-8")
        report = (ROOT / "tools/package_studio_deliverables.py").read_text(encoding="utf-8")
        renderer_package = json.loads((ROOT / "tools/video_renderer/package.json").read_text(encoding="utf-8"))
        self.assertIn("test:avatar-rig", renderer_package["scripts"])
        self.assertIn("test:module-resolution", renderer_package["scripts"])
        self.assertIn("function animateActor(actor,t)", renderer)
        self.assertIn("actor.root.rotation.y", renderer)
        self.assertIn("story-paced motion", renderer)
        self.assertIn("await RAPIER.init()", renderer)
        self.assertIn("physicsWorld.step();physicsWorld.step();", renderer)
        self.assertIn("dynamicPropInstances", renderer)
        self.assertIn('<script type="importmap">', renderer)
        self.assertIn('"three":"/modules/three/build/three.module.js"', renderer)
        self.assertLess(renderer.index('type="importmap"'), renderer.index('type="module"'))
        self.assertIn("buildAvatarRig", renderer)
        self.assertIn("animateAvatarRig", renderer)
        self.assertIn("Automatic avatar limb rigs", renderer)
        self.assertIn("Avatar sources:", renderer)
        self.assertIn("type:'jpeg',quality:92", renderer)
        self.assertIn("estimated ${remaining.toFixed(0)}s remaining", renderer)
        self.assertIn("DATA.plan.ground_color", renderer)
        self.assertIn("horizon.position.y=-.08", renderer)
        self.assertIn("rather than using native Roblox R15 animation clips", report)

    def test_builder_packages_playable_place_with_world_cast_and_captions(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            map_plan = {
                "name": "Sunny Plaza",
                "theme": "A bright town with a market and a fountain.",
                "ground_color": [20, 20, 20],
                "props": [
                    {"name": f"AI landmark {index}", "shape": "Block", "material": "Brick",
                     "position": [index - 3, 5, 0], "size": [8, 10, 8], "color": [80, 140, 220],
                     "physics": "dynamic" if index == 0 else "static"}
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
            part_by_name = {
                node.find('Properties/string[@name="Name"]').text: node
                for node in root.findall('.//Item[@class="Part"]')
            }
            self.assertEqual(part_by_name['AI landmark 0'].find('Properties/bool[@name="Anchored"]').text, 'false')
            self.assertEqual(part_by_name['AI landmark 1'].find('Properties/bool[@name="Anchored"]').text, 'true')
            self.assertIn('NarrationCaption', client.text)
            self.assertIn('A student returns a lost wallet.', client.text)
            self.assertIn('12345', client.text)
            self.assertIn('caption.Visible = true', client.text)
            self.assertNotIn('motor.Transform', client.text)
            self.assertNotIn('Story Lead Torso', server.text)
            self.assertTrue((work / "README.md").exists())
            readme = (work / "README.md").read_text(encoding="utf-8")
            self.assertIn("ROBLOX_OPEN_CLOUD_API_KEY", readme)
            self.assertIn("public Users API", readme)
            self.assertIn("users/<username>.rbxm", readme)
            self.assertIn("procedural R15-style joints", readme)
            self.assertTrue((work / "World.lua").exists())

    def test_prompt_themed_map_requires_full_ai_authored_scene(self):
        from tools.build_story_map import emit_lua, validate

        props = [
            {"name": f"Theme part {index}", "shape": "Block", "material": "SmoothPlastic",
             "position": [index - 25, 4, 0], "size": [4, 8, 4], "color": [95, 145, 210],
             "physics": "dynamic" if index < 3 else "static"}
            for index in range(120)
        ]
        plan = {"name": "Crystal Reef", "theme": "A luminous underwater crystal kingdom",
                "ground_material": "Slate", "ground_color": [54, 113, 140],
                "ambient_color": [120, 160, 190], "props": props}
        normalized = validate(plan, 60, (), min_props=120)
        self.assertEqual(normalized["theme"], plan["theme"])
        self.assertEqual(normalized["ground_material"], "Slate")
        self.assertEqual(len(normalized["props"]), 120)
        self.assertEqual(normalized["props"][0]["physics"], "dynamic")
        self.assertEqual(normalized["props"][3]["physics"], "static")
        with tempfile.TemporaryDirectory() as temporary:
            lua_output = Path(temporary) / "GeneratedStoryWorld.lua"
            emit_lua(normalized, lua_output)
            generated_lua = lua_output.read_text(encoding="utf-8")
            self.assertIn("p.Anchored = physicsMode ~= 'dynamic'", generated_lua)
            self.assertIn('"dynamic")', generated_lua)
        with self.assertRaises(ValueError):
            validate({**plan, "props": props[:119]}, 60, (), min_props=120)

    def test_compact_ai_blueprint_expands_to_a_large_theme_furnished_map(self):
        from tools.build_story_map import expand_plan, procedural_fallback_plan, validate

        anchors = [
            {"name": "Coral Market", "shape": "Block", "material": "Brick", "position": [-45, 7, -70],
             "size": [34, 14, 30], "color": [210, 115, 130]},
            {"name": "Tide Hall", "shape": "Block", "material": "Slate", "position": [45, 9, -70],
             "size": [42, 18, 34], "color": [65, 150, 190]},
            {"name": "Pearl Workshop", "shape": "Block", "material": "SmoothPlastic", "position": [0, 7, 88],
             "size": [30, 14, 28], "color": [120, 185, 205]},
        ]
        anchors.extend(
            {"name": f"Reef Story Landmark {index}", "shape": "Block", "material": "SmoothPlastic",
             "position": [index * 5 - 50, 2, 120 - index * 7], "size": [3, 4, 3], "color": [60, 160, 190]}
            for index in range(19)
        )
        blueprint = validate({"name": "Coral Reef", "theme": "Bright daylight underwater coral reef",
                              "ground_material": "Slate", "ground_color": [45, 125, 150],
                              "ambient_color": [140, 210, 225], "props": anchors}, 60, (), min_props=8)
        expanded = validate(expand_plan(blueprint, 220), 60, (), min_props=220)
        names = [part["name"] for part in expanded["props"]]
        self.assertGreaterEqual(len(names), 220)
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(any(name == "Coral Market Interior Floor" for name in names))
        self.assertTrue(any("Wood Entrance Door" in name for name in names))
        self.assertTrue(any("Glass Window" in name for name in names))
        self.assertTrue(any("Welcome Rug" in name for name in names))
        self.assertTrue(any("Sea Floor Stone" in name for name in names))
        self.assertGreater(max(abs(part["position"][0]) for part in expanded["props"]), 180)
        self.assertEqual(expanded["theme"], blueprint["theme"])
        with tempfile.TemporaryDirectory() as temporary:
            lua_path = Path(temporary) / "ReefWorld.lua"
            from tools.build_story_map import emit_lua
            emit_lua(expanded, lua_path)
            lua = lua_path.read_text(encoding="utf-8")
            self.assertIn("{640, 2, 640}", lua)
            self.assertNotIn("Central Avenue", lua)

        sparse_anchors = [{"name": f"Story Landmark {index}", "shape": "Block", "material": "SmoothPlastic",
                           "position": [index * 4 - 40, 2, 70 - index * 7], "size": [4, 4, 4],
                           "color": [80, 160, 200]} for index in range(22)]
        sparse_plan = validate({"name": "Wildwood", "theme": "Mystery forest", "props": sparse_anchors},
                               60, (), min_props=8)
        sparse_world = validate(expand_plan(sparse_plan, 220), 60, (), min_props=220)
        self.assertTrue(all(any(building in part["name"] for part in sparse_world["props"])
                            for building in ("Forest Market", "Canopy Hall", "Moss Workshop")))

        fallback = procedural_fallback_plan("daylight", "Friends discover a hidden coral reef.", 60, ["Lead", "Friend"])
        fallback_world = validate(expand_plan(validate(fallback, 60, ["Lead", "Friend"], 8), 220),
                                  60, ["Lead", "Friend"], 220)
        self.assertIn("daylight", fallback_world["theme"])
        self.assertIn("coral reef", fallback_world["theme"])
        self.assertEqual(len(fallback_world["character_placements"]), 2)

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
            model_copy = dist / "avatar-assets" / "source-rbxm" / "normal.rbxm"
            model_copy.parent.mkdir(parents=True)
            model_copy.write_bytes(b"RBXM package fixture")
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
                self.assertIn("avatar-assets/source-rbxm/normal.rbxm", archive.namelist())
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
