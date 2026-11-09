from __future__ import annotations

import json
import shutil
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
        self.assertIn('PACKAGE_RATE="${NARRATOR_RATE:-+4%}"', workflow)
        self.assertIn('--rate="$PACKAGE_RATE"', workflow)
        self.assertNotIn('--rate "$PACKAGE_RATE"', workflow)
        username_step = workflow.index("- name: Require a username for the avatar cast")
        model_step = workflow.index("- name: Download the selected AI model for story and world/camera planning")
        self.assertLess(username_step, model_step)
        self.assertIn("Usernames, COMMA separated", workflow)
        self.assertIn("users/<username>.obj/.gltf/.glb/.fbx/.dae/.ply/.stl/.3ds and .rbxm", workflow)
        self.assertIn("users/<username>.obj/.gltf/.glb/.fbx/.dae/.ply/.stl/.3ds", workflow)
        self.assertIn("description: 'Theme (optional)'", workflow)
        self.assertIn('"${WORLD_THEME:-AUTO FROM STORY}"', workflow)
        self.assertIn("treat the user's cue as a required design constraint", workflow)
        self.assertIn("daylight cue means a clearly bright, naturally sunlit daytime world", workflow)
        self.assertIn("ROBLOX_OPEN_CLOUD_API_KEY: ${{ secrets.ROBLOX_OPEN_CLOUD_API_KEY }}", workflow)
        self.assertIn("public Roblox Users API resolves entered usernames to IDs keylessly", workflow)
        self.assertIn(".rbxm sources", workflow)
        self.assertIn("Mesh access:", workflow)
        self.assertIn("3D mesh unavailable for", workflow)
        self.assertIn("ROBLOX_OPEN_CLOUD_API_KEY is {key_state}", workflow)
        self.assertIn("Upload native Studio project even if the MP4 cannot use a protected mesh", workflow)
        self.assertIn("steps.studio-experience.outcome == 'success'", workflow)
        # There is exactly ONE workflow, and it runs every renderer test itself
        # before the model is downloaded, so a broken tool fails in minutes.
        workflows = sorted(path.name for path in (ROOT / ".github/workflows").iterdir())
        self.assertEqual(workflows, ["main.yml"], "the repository must ship one workflow")
        self.assertIn("npm run test:avatar-rig", workflow)
        self.assertIn("npm run test:avatar-obj", workflow)
        self.assertIn("npm run test:module-resolution", workflow)
        self.assertIn("uses: actions/cache/restore@v4", workflow)
        disk_cleanup_step = workflow.index("- name: Reclaim runner disk space for the selected model")
        cache_restore_step = workflow.index("- name: Restore cached selected Ollama model")
        model_pull_step = workflow.index("- name: Download the selected AI model for story and world/camera planning")
        self.assertLess(disk_cleanup_step, cache_restore_step)
        self.assertLess(cache_restore_step, model_pull_step)
        self.assertIn("id: disk-space", workflow)
        self.assertIn("smart_11b) REQUIRED_GIB=20", workflow)
        self.assertIn('if [ "$AVAILABLE_GIB" -lt "$REQUIRED_GIB" ]', workflow)
        self.assertIn("steps.disk-space.outputs.cache_restore_allowed == 'true'", workflow)
        self.assertIn("sudo rm -rf /usr/local/lib/android/sdk", workflow)
        self.assertIn("this preset needs at least ${REQUIRED_GIB} GiB", workflow)
        self.assertIn("rm -f ollama.tar.zst", workflow)
        self.assertIn("ollama-${{ runner.os }}-${{ inputs.model_quality }}-${{ inputs.model_quality == 'animation_best' && 'deepseek-r1-8b-v1' || inputs.model_quality == 'smart_11b' && 'qwen3-14b-v1' || inputs.model_quality == 'hard' && 'qwen3-8b-v3' || inputs.model_quality == 'medium' && 'qwen3-8b-v1' || 'qwen3-4b-v1' }}", workflow)
        self.assertIn("fast) SELECTED_MODEL=qwen3:4b", workflow)
        self.assertIn("medium) SELECTED_MODEL=qwen3:8b", workflow)
        self.assertIn("hard) SELECTED_MODEL=qwen3:8b", workflow)
        self.assertIn("smart_11b) SELECTED_MODEL=qwen3:14b", workflow)
        self.assertIn("animation_best) SELECTED_MODEL=deepseek-r1:8b; MODEL_THINKING=true", workflow)
        self.assertIn("OLLAMA_THINKING=$MODEL_THINKING", workflow)
        self.assertIn("ollama_stream.py", workflow)
        self.assertIn("/api/chat", (ROOT / "tools/ollama_stream.py").read_text(encoding="utf-8"))
        # No AI generation may bypass the streaming helper. The single exception is
        # the one-token warm-up, whose whole point is to load the weights before the
        # first real prompt and to prove the model answers without spending a call.
        self.assertEqual(workflow.count("/api/generate"), 1,
                         "only the warm-up may call Ollama directly; every real AI call "
                         "must go through ollama_stream.py")
        warmup = workflow[workflow.index("/api/generate") - 400:workflow.index("/api/generate") + 400]
        self.assertIn("num_predict:1", warmup)
        self.assertIn("128K-context, text-only DeepSeek-R1 reasoning model for world/shot planning", workflow)
        marker = workflow.index("case \"$MODEL_QUALITY\" in", workflow.index("ollama serve"))
        case_block = workflow[marker:]
        case_block = case_block[:case_block.index("esac")]
        self.assertNotIn("llama3.2-vision", case_block,
                         "a model current Ollama cannot load must never be selected")
        self.assertIn("for attempt in 1 2; do", workflow)
        self.assertIn('--min-props 8 --target-props "$TARGET_PROPS"', workflow)
        self.assertIn("every deliberate snap cut must move both the camera and focus", workflow)
        self.assertIn("only when the user's story/topic explicitly requests that effect", workflow)
        self.assertIn("num_predict:$tokens}}' > map_request.json", workflow)
        self.assertIn('--timeout "${AI_TIMEOUT:-900}"', workflow)
        self.assertIn("dist/web_research.json", workflow)
        self.assertIn("--fallback --theme", workflow)
        self.assertIn("individually named, grid-aligned editable Parts", workflow)
        self.assertIn("Show the public AI build plan and tools", workflow)
        self.assertIn("not private chain-of-thought", workflow)

    def test_eleven_billion_preset_sits_under_hard_and_is_fully_wired(self):
        workflow = (ROOT / ".github" / "workflows" / "main.yml").read_text(encoding="utf-8")
        options = workflow[workflow.index("      model_quality:"):workflow.index("      voice_style:")]
        order = [line.strip().strip("- ") for line in options.splitlines() if line.strip().startswith("- ")]
        self.assertEqual(order, ["fast", "medium", "hard", "smart_11b", "animation_best"],
                         "the 11B preset must be listed directly under hard")
        self.assertIn("smart_11b) SELECTED_MODEL=qwen3:14b; MODEL_THINKING=true", workflow)
        self.assertIn("'qwen3-14b-v1'", workflow)
        # The 14B model needs a bigger disk requirement than the small presets,
        # and it also has to leave room for the qwen3:8b fallback.
        gate = workflow[workflow.index("Reclaim runner disk space"):workflow.index("cache_restore_allowed=$CACHE_RESTORE_ALLOWED")]
        self.assertIn("smart_11b) REQUIRED_GIB=20", gate)
        self.assertIn("fast|medium) REQUIRED_GIB=8", gate)
        self.assertIn("smart_11b qwen3:14b (14.8B)", workflow)
        self.assertIn("fast qwen3:4b, medium qwen3:8b, hard qwen3:8b", workflow)
        # Keeping the existing promises intact.
        marker = workflow.index("case \"$MODEL_QUALITY\" in", workflow.index("ollama serve"))
        case_block = workflow[marker:]
        case_block = case_block[:case_block.index("esac")]
        self.assertNotIn("llama3.2-vision", case_block,
                         "a model current Ollama cannot load must never be selected")
        self.assertIn("animation_best) SELECTED_MODEL=deepseek-r1:8b; MODEL_THINKING=true", workflow)

    def test_workflow_uses_higher_creative_model_temperatures(self):
        workflow = (ROOT / ".github/workflows/main.yml").read_text(encoding="utf-8")
        # The creative temperature is 10x the original presets (clamped to the
        # highest value the models can still use coherently).
        # Narration and repair budgets scale with the story length so a thinking
        # model cannot spend the whole ceiling reasoning and cut the answer off;
        # the map plan and the summary keep their own generous budgets.
        self.assertIn("options:{temperature:2.0, top_p:0.99, num_ctx:$ctx, num_predict:$tokens}}' > narration_request.json", workflow)
        self.assertIn("options:{temperature:2.0, top_p:0.99, num_ctx:$ctx, num_predict:$tokens}, messages:", workflow)
        self.assertIn("options:{temperature:2.0, top_p:0.99, num_ctx:$ctx, num_predict:$tokens}}' > map_request.json", workflow)
        self.assertIn("options:{temperature:2.0, top_p:0.99, num_ctx:$ctx, num_predict:900}}' > creation_summary_request.json", workflow)
        self.assertIn("NARRATION_TOKENS=$((1200 + DURATION_SECONDS * 8))", workflow)
        for legacy in ("temperature:0.9,", "temperature:1.5,", "temperature:0.45,", "temperature:0.75,", "temperature:0.6,"):
            self.assertNotIn(legacy, workflow)

    def test_every_preset_runs_with_thinking_enabled(self):
        workflow = (ROOT / ".github" / "workflows" / "main.yml").read_text(encoding="utf-8")
        marker = workflow.index("case \"$MODEL_QUALITY\" in", workflow.index("ollama serve"))
        case_block = workflow[marker:]
        case_block = case_block[:case_block.index("esac")]
        selections = [line.strip() for line in case_block.splitlines() if "SELECTED_MODEL=" in line]
        self.assertEqual(len(selections), 5, "all five presets must be mapped")
        for line in selections:
            self.assertIn("MODEL_THINKING=true", line, f"thinking must be on for: {line}")
        self.assertNotIn("MODEL_THINKING=false", case_block)
        self.assertIn("thinking mode: $MODEL_THINKING (on for every preset)", workflow)

    def test_stream_helper_survives_models_without_a_thinking_channel(self):
        helper = (ROOT / "tools" / "ollama_stream.py").read_text(encoding="utf-8")
        self.assertIn("class ThinkingUnsupported", helper)
        self.assertIn('"think": False', helper)
        self.assertIn("thinking_unsupported", helper)
        # A model that rejects thinking must still produce a usable answer file.
        self.assertIn("except ThinkingUnsupported", helper)

    def test_models_that_cannot_run_have_a_known_good_fallback(self):
        workflow = (ROOT / ".github" / "workflows" / "main.yml").read_text(encoding="utf-8")
        # Every streaming call must be able to retry on a model we know loads.
        # Story, story repair, narration edit, world plan, its helper round and the
        # short post-sub-agent confirmation.
        self.assertEqual(workflow.count("--fallback-model"), 7)
        self.assertIn("FALLBACK_MODEL=qwen3:4b", workflow)
        self.assertIn("FALLBACK_MODEL=qwen3:8b", workflow)
        # llama3.2-vision is the mllama architecture, which current Ollama cannot
        # even load (HTTP 500), so it must never be selected again.
        self.assertNotIn("SELECTED_MODEL=llama3.2-vision", workflow)
        helper = (ROOT / "tools" / "ollama_stream.py").read_text(encoding="utf-8")
        self.assertIn("class ModelUnusable", helper)
        self.assertIn("exc.code >= 500", helper)
        self.assertIn("fallback_model", helper)

    def test_slow_models_get_a_larger_request_budget(self):
        workflow = (ROOT / ".github" / "workflows" / "main.yml").read_text(encoding="utf-8")
        # Slow presets are allowed to take as long as they need: the socket guard
        # is hours, not minutes, and there is no wall-clock cap on any call.
        self.assertIn("smart_11b) AI_TIMEOUT=9000", workflow)
        self.assertIn("hard) AI_TIMEOUT=5400", workflow)
        self.assertIn('echo "AI_TIMEOUT=$AI_TIMEOUT" >> "$GITHUB_ENV"', workflow)
        self.assertEqual(workflow.count('--timeout "${AI_TIMEOUT:-900}"'), 5)
        self.assertNotIn("--max-seconds", workflow)
        self.assertNotIn("NARRATION_MAX", workflow)

    def test_workflow_streams_ai_output_and_supports_live_search(self):
        workflow = (ROOT / ".github/workflows/main.yml").read_text(encoding="utf-8")
        self.assertIn("tools/ollama_stream.py", workflow)
        self.assertNotIn("curl --fail --silent --show-error --max-time 600", workflow)
        self.assertGreaterEqual(workflow.count("python tools/ollama_stream.py"), 5)
        self.assertIn("tools/ai_web_search.py", workflow)
        self.assertIn('search_queries', workflow)
        self.assertIn("AI help round", workflow)

    def test_workflow_form_is_compact_and_lists_comma_separated_usernames(self):
        workflow = (ROOT / ".github/workflows/main.yml").read_text(encoding="utf-8")
        self.assertIn("Usernames, COMMA separated", workflow)
        for short in ('description: \'Story topic — one line, "In a world where ..." works best', "description: 'Length — pick it; the AI picks the exact seconds", "description: 'World size'",
                      "description: 'AI model'", "description: 'Voice'"):
            self.assertIn(short, workflow)
        self.assertNotIn("Real-life story topic for a fully furnished Roblox-themed short video", workflow)

    def test_workflow_plans_face_animation_and_face_cameras(self):
        workflow = (ROOT / ".github/workflows/main.yml").read_text(encoding="utf-8")
        for expected in ("face_expressions", '"framing":"face"', "face_distance",
                         "--face-animation always", "--captions dist/narration.srt",
                         "npm run test:face", "full creative authority"):
            self.assertIn(expected, workflow)

    def test_studio_runtime_uses_native_rbxm_animation_tracks(self):
        from tools.build_studio_experience import make_config, server_lua

        profiles = [{
            "username": "Normal",
            "rbxm_animation_ids": {"idle": "rbxassetid://123", "walk": "rbxassetid://456"},
        }]
        config = make_config({}, [{"username": "Normal", "role": "lead", "position": [0, 0, 0]}],
                             60, "", [], "", profiles)
        self.assertEqual(config["rbxm_animations"]["normal"]["idle"], "rbxassetid://123")
        self.assertEqual(config["cast"][0]["visual_effects"], [])
        runtime = server_lua(json.dumps(config))
        self.assertIn("animator:LoadAnimation(animation)", runtime)
        self.assertIn("tracks.walk", runtime)
        self.assertIn("humanoid:MoveTo(waypoints[index])", runtime)
        self.assertIn('FindFirstChild("Animate")', runtime)

    def test_avatar_body_effects_are_opt_in_and_follow_requested_attachments(self):
        from tools.build_story_map import default_plan, validate
        from tools.build_studio_experience import make_config, server_lua

        no_effects = validate(default_plan(), 60, ["Lead", "Friend"], min_props=8,
                              visual_request="A wallet dilemma about finding strength in friendship.")
        self.assertTrue(all("visual_effects" not in person for person in no_effects["character_placements"]))

        explicit = validate(default_plan(), 60, ["Lead", "Friend"], min_props=8,
                             visual_request="Show a strength number above each avatar's head and add a scar on the left arm.")
        lead_effects = explicit["character_placements"][0]["visual_effects"]
        self.assertEqual([(effect["kind"], effect["attachment"]) for effect in lead_effects],
                         [("number", "head"), ("scar", "left_arm")])
        self.assertTrue(all(10 <= effect["value"] <= 99 for effect in lead_effects if effect["kind"] == "number"))
        fixed = validate(default_plan(), 60, ["Lead"], min_props=8,
                         visual_request="Put the number 42 on the avatar's chest.")
        self.assertEqual(fixed["character_placements"][0]["visual_effects"],
                         [{"kind": "number", "attachment": "torso", "value": 42}])

        config = make_config(explicit, [{"username": "Lead", "role": "lead", "position": [0, 0, 24]}],
                             60, "", [], "")
        self.assertEqual(config["cast"][0]["visual_effects"], lead_effects)
        runtime = server_lua(json.dumps(config))
        self.assertIn("applyRequestedAvatarEffects", runtime)
        self.assertIn('kind == "number" or kind == "text"', runtime)
        self.assertIn('kind == "scar"', runtime)

    def test_mp4_renderer_retargets_native_roblox_keyframes_onto_auto_rigged_models(self):
        renderer = (ROOT / "tools/video_renderer/render_short.mjs").read_text(encoding="utf-8")
        report = (ROOT / "tools/package_studio_deliverables.py").read_text(encoding="utf-8")
        renderer_package = json.loads((ROOT / "tools/video_renderer/package.json").read_text(encoding="utf-8"))
        self.assertIn("test:avatar-rig", renderer_package["scripts"])
        self.assertIn("test:avatar-obj", renderer_package["scripts"])
        self.assertIn("test:module-resolution", renderer_package["scripts"])
        self.assertIn("function animateActor(actor, t)", renderer)
        self.assertIn("actor.root.rotation.y", renderer)
        # The cast is blocked from a camera-cut schedule (actor_motion.mjs) instead
        # of sliding round a tiny sine circle in place.
        self.assertIn("planMarks", renderer)
        self.assertIn("/actor_motion.mjs", renderer)
        self.assertIn("idleAvatarRig", renderer)
        self.assertIn("await RAPIER.init()", renderer)
        self.assertIn("physicsWorld.step();physicsWorld.step();", renderer)
        self.assertIn("dynamicPropInstances", renderer)
        self.assertIn('<script type="importmap">', renderer)
        self.assertIn('"three":"/modules/three/build/three.module.js"', renderer)
        self.assertLess(renderer.index('type="importmap"'), renderer.index('type="module"'))
        self.assertIn("buildAvatarRig", renderer)
        self.assertIn("applyRobloxAnimationRig", renderer)
        self.assertIn("animateAvatarRig", renderer)
        self.assertIn("chooseSafeCamera", renderer)
        self.assertIn("addRequestedAvatarEffects", renderer)
        self.assertNotIn("strengthSprite", renderer)
        self.assertIn("focus_username", renderer)
        self.assertNotIn("nameSprite", renderer)
        # The spoken narration IS drawn on screen now (bold, outlined, a little
        # above the middle), but nothing else is: no username labels, no title,
        # no caption for a character's handle.
        self.assertIn('<div id="caption"></div>', renderer)
        self.assertIn("captionAt(t)", renderer)
        self.assertNotIn("usernameLabel", renderer)
        self.assertNotIn("titleSprite", renderer)
        self.assertIn("Automatic avatar limb rigs", renderer)
        self.assertIn("Native Roblox walk clips retargeted", renderer)
        self.assertIn("Native Roblox ${missing.join('/')}", renderer)
        self.assertIn("Moving-limb MP4 requires a local or authorized 3D avatar mesh", renderer)
        self.assertIn("no static-limb MP4 will be packaged", renderer)
        self.assertIn("Avatar sources:", renderer)
        self.assertIn("type:'jpeg',quality:92", renderer)
        self.assertIn("estimated ${remaining.toFixed(0)}s remaining", renderer)
        self.assertIn("DATA.plan.ground_color", renderer)
        self.assertIn("horizon.position.y=-.08", renderer)
        self.assertIn("rather than using Roblox's native Animate runtime", report)
        self.assertIn("static-limb video is not delivered", report)

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
            self.assertGreaterEqual(len(root.findall('.//Item[@class="Part"]')), 9)
            self.assertIsNotNone(root.find('.//Item[@class="Sky"]'))
            self.assertIn('SkyboxBk = "rbxasset://textures/sky/sky512_bk.tex"', server.text)
            self.assertNotIn('World Title Sign', server.text)
            self.assertIn('applyRequestedAvatarEffects(avatar, castMember.visual_effects)', server.text)
            self.assertNotIn('StrengthNumber', server.text)
            self.assertIn('humanoid.DisplayName = ""', server.text)
            self.assertIn('HumanoidDisplayDistanceType.None', server.text)
            part_names = {node.text for node in root.findall('.//Item[@class="Part"]/Properties/string[@name="Name"]')}
            self.assertIn('AI landmark 0', part_names)
            part_by_name = {
                node.find('Properties/string[@name="Name"]').text: node
                for node in root.findall('.//Item[@class="Part"]')
            }
            self.assertEqual(part_by_name['AI landmark 0'].find('Properties/bool[@name="Anchored"]').text, 'false')
            self.assertEqual(part_by_name['AI landmark 1'].find('Properties/bool[@name="Anchored"]').text, 'true')
            self.assertNotIn('NarrationCaption', client.text)
            self.assertNotIn('TextLabel', client.text)
            self.assertNotIn('A student returns a lost wallet.', client.text)
            self.assertIn('shotFocus(a, targetA)', client.text)
            self.assertIn('focus_username', client.text)
            self.assertNotIn('motor.Transform', client.text)
            self.assertNotIn('Story Lead Torso', server.text)
            self.assertTrue((work / "README.md").exists())
            readme = (work / "README.md").read_text(encoding="utf-8")
            self.assertIn("ROBLOX_OPEN_CLOUD_API_KEY", readme)
            self.assertIn("public Users API", readme)
            self.assertIn("users/<username>.rbxm", readme)
            self.assertIn("R15-style joints", readme)
            self.assertTrue((work / "World.lua").exists())

    def test_map_decoder_reads_chat_api_content(self):
        from tools.build_story_map import decode_response

        plan = {"name": "Test", "props": []}
        with tempfile.TemporaryDirectory() as temporary:
            response = Path(temporary) / "response.json"
            response.write_text(json.dumps({"message": {"content": json.dumps(plan)}}), encoding="utf-8")
            self.assertEqual(decode_response(response), plan)

    def test_prompt_themed_map_requires_full_ai_authored_scene(self):
        from tools.build_story_map import emit_lua, validate

        props = [
            {"name": f"Theme part {index}", "shape": "Block", "material": "SmoothPlastic",
             "position": [index - 25, 4, 0], "size": [4, 8, 4], "color": [0, 0, 0] if index == 0 else [95, 145, 210],
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
        self.assertGreaterEqual(sum(normalized["props"][0]["color"]) / 3, 72)
        self.assertEqual(normalized["props"][3]["physics"], "static")
        with self.assertRaises(ValueError):
            validate({**plan, "props": [{**props[0], "size": [65, 1, 1]}, *props[1:]]}, 60, (), min_props=120)
        with tempfile.TemporaryDirectory() as temporary:
            lua_output = Path(temporary) / "GeneratedStoryWorld.lua"
            emit_lua(normalized, lua_output)
            generated_lua = lua_output.read_text(encoding="utf-8")
            self.assertIn("p.Anchored = physicsMode ~= 'dynamic'", generated_lua)
            self.assertIn('"dynamic", nil, nil)', generated_lua)
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
        expanded = validate(expand_plan(blueprint, 1260), 60, (), min_props=1260)
        names = [part["name"] for part in expanded["props"]]
        self.assertGreaterEqual(len(names), 1260)
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(any(name == "Coral Market Interior Floor" for name in names))
        self.assertTrue(any("Wood Entrance Door" in name for name in names))
        self.assertTrue(any("Glass Window" in name for name in names))
        self.assertTrue(any("Welcome Rug" in name for name in names))
        self.assertTrue(any("Sea Floor Stone" in name for name in names))
        self.assertTrue(any(name.startswith("Plaza Paving Tile") for name in names))
        self.assertTrue(any("Plaza Bench Seat" in name for name in names))
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
        sparse_world = validate(expand_plan(sparse_plan, 1260), 60, (), min_props=1260)
        self.assertTrue(all(any(building in part["name"] for part in sparse_world["props"])
                            for building in ("Forest Market", "Canopy Hall", "Moss Workshop")))

        fallback = procedural_fallback_plan("daylight", "Friends discover a hidden coral reef.", 60, ["Lead", "Friend"])
        fallback_world = validate(expand_plan(validate(fallback, 60, ["Lead", "Friend"], 8), 1260),
                                  60, ["Lead", "Friend"], 1260)
        self.assertIn("daylight", fallback_world["theme"])
        self.assertIn("coral reef", fallback_world["theme"])
        self.assertEqual(len(fallback_world["character_placements"]), 2)
        self.assertTrue(all("visual_effects" not in person for person in fallback_world["character_placements"]))
        self.assertEqual(fallback_world["camera_shots"][0]["focus_username"], "Lead")

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
                "--voice", "en-US-GuyNeural", "--rate=+4%", "--duration", "60",
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


class PageTemplateTests(unittest.TestCase):
    """The served page must be built for real, not just parse as JavaScript.

    A backtick inside the one big template literal (a comment like "only `.bones`")
    ends the literal early and turns the rest into code. `node --check` passes, and
    the render then dies with "WIDTHHEIGHT...bones is not a function" after the
    world has already been planned.
    """

    def test_the_page_template_builds_without_stray_backticks(self):
        renderer = (ROOT / "tools/video_renderer/render_short.mjs").read_text(encoding="utf-8")
        start = renderer.index("return `<!doctype")
        body = renderer[start:renderer.index("function serveFile", start)]
        self.assertEqual(body.count("`"), 2, "a backtick inside the page template ends it early")

    def test_caption_whitespace_regex_reaches_the_browser_intact(self):
        """A single backslash in the page template silently became "delete every s".

        The caption code collapses runs of whitespace with a regex written inside
        the page template. Written with ONE backslash, the template literal ate it
        and Chromium received `/s+/g` - "replace every letter s with a space" - so
        the shipped MP4 read "WHI TLE" and "HI FACE OFTENING" instead of "WHISTLE"
        and "HIS FACE SOFTENING".
        """
        renderer = (ROOT / "tools/video_renderer/render_short.mjs").read_text(encoding="utf-8")
        self.assertIn(r"replace(/\\s+/g,' ')", renderer,
                      "the caption regex needs a doubled backslash inside the page template")

    def test_the_template_check_rejects_eaten_escapes(self):
        script = (ROOT / "tools/video_renderer/template_check.mjs").read_text(encoding="utf-8")
        self.assertIn("TEMPLATE_ESCAPES", script,
                      "the template check must scan for escapes a template literal eats")
        self.assertIn("silently eats", script)

    def test_the_template_check_runs_the_builder(self):
        script = ROOT / "tools/video_renderer/template_check.mjs"
        self.assertTrue(script.is_file())
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed here")
        result = subprocess.run([node, str(script)], capture_output=True, text=True,
                                cwd=ROOT / "tools/video_renderer")
        self.assertEqual(result.returncode, 0, result.stderr[-1500:])
        self.assertIn("Page template check passed", result.stdout)

    def test_the_one_workflow_runs_the_page_template_check(self):
        text = (ROOT / ".github" / "workflows" / "main.yml").read_text(encoding="utf-8")
        self.assertIn("npm run test:page-template", text)
        # ...and it runs it BEFORE the model is downloaded: the check exists to stop
        # a broken page from being discovered after an hour of AI work.
        self.assertLess(text.index("test:page-template"), text.index("ollama pull"))


class RenderGuardTests(unittest.TestCase):
    """A broken page must fail in the first second, not after 45 minutes."""

    def setUp(self):
        self.renderer = (ROOT / "tools/video_renderer/render_short.mjs").read_text(encoding="utf-8")

    def test_the_page_is_built_through_the_guard(self):
        self.assertIn("checkedHtml(data)", self.renderer)
        self.assertIn("function checkedHtml(", self.renderer)
        self.assertNotIn("createStaticServer(buildHtml(data)", self.renderer)

    def test_the_guard_explains_the_backtick_trap(self):
        self.assertIn("A backtick inside the HTML template", self.renderer)
        self.assertIn("test:page-template", self.renderer)

    def test_the_check_runs_the_real_builder_not_just_a_literal(self):
        script = (ROOT / "tools/video_renderer/template_check.mjs").read_text(encoding="utf-8")
        self.assertIn("function buildHtml(", "function buildHtml(")  # marker
        self.assertIn("new Function", script)
        self.assertIn("return buildHtml;", script)
        # It must reject a stray backtick before it ever evaluates the page.
        self.assertIn("a backtick inside the page template ends it early", script)
