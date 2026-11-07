"""The world the AI may build: triangles, lamps and 520 particle effects.

A map made only of Blocks, Balls and Cylinders looks like a prototype, and a
world with no light of its own looks flat however detailed it is. The AI may now
ask for a triangle (Wedge), a dome, a cone, a ring, a truss; attach a light with a
brightness, a range and a colour; and attach a particle effect with a density, a
size, a speed, a lifetime, gravity and a colour.

These tests pin down the three places the vocabulary has to agree: the
validator that cleans the plan, the schema the model is held to, and the two
builders that emit it (Lua for Studio, the browser page for the MP4).
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import build_story_map as bsm  # noqa: E402
import effects_catalog as catalog  # noqa: E402
import plan_schema  # noqa: E402

RENDERER = (ROOT / "tools/video_renderer/render_short.mjs").read_text(encoding="utf-8")
SHAPES_JS = (ROOT / "tools/video_renderer/map_shapes.mjs").read_text(encoding="utf-8")
PARTICLES_JS = (ROOT / "tools/video_renderer/particles.mjs").read_text(encoding="utf-8")
STUDIO = (ROOT / "tools/build_studio_experience.py").read_text(encoding="utf-8")
WORKFLOW = (ROOT / ".github/workflows/main.yml").read_text(encoding="utf-8")


def plan_with(prop: dict, **extra) -> dict:
    base = {
        "name": "Shape Test",
        "theme": "a test world",
        "props": [
            {"name": "Anchor One", "shape": "Block", "material": "Brick",
             "position": [0, 4, -40], "size": [8, 8, 8], "color": [180, 150, 120]},
            {"name": "Anchor Two", "shape": "Ball", "material": "Grass",
             "position": [20, 3, -40], "size": [6, 6, 6], "color": [120, 200, 120]},
            dict(prop),
        ],
        "camera_shots": [{"time": 0, "position": [0, 10, 30], "target": [0, 4, 0],
                          "focus_username": "world", "transition": "smooth"}],
        "face_expressions": [{"time": 0, "expression": "neutral", "intensity": 0.5,
                              "username": "everyone"}],
    }
    base.update(extra)
    return base


class ShapeTests(unittest.TestCase):
    """A triangle must be possible, and every shape must survive validation."""

    SHAPE_WORDS = {
        "triangle": "Wedge", "wedge": "Wedge", "ramp": "Wedge", "roof": "Wedge",
        "prism": "Prism", "corner wedge": "CornerWedge", "cone": "Cone",
        "pyramid": "Pyramid", "doughnut": "Torus", "donut": "Torus",
        "ring": "Ring", "dome": "Hemisphere", "truss": "Truss", "lattice": "Truss",
    }

    def test_every_shape_word_maps_to_a_real_shape(self):
        for word, expected in self.SHAPE_WORDS.items():
            self.assertEqual(bsm.normalize_shape(word), expected, word)
            self.assertIn(expected, bsm.SHAPES)

    def test_each_shape_passes_validation(self):
        for shape in sorted(bsm.SHAPES):
            out = bsm.validate(plan_with({"name": "Shape Probe", "shape": shape,
                                          "material": "Neon", "position": [5, 4, -60],
                                          "size": [4, 4, 4], "color": [200, 120, 240]}), 30, (), 2)
            self.assertEqual(out["props"][2]["shape"], shape)

    def test_an_unknown_shape_falls_back_instead_of_failing(self):
        out = bsm.validate(plan_with({"name": "Odd Shape", "shape": "dodecahedron",
                                      "material": "Slate", "position": [5, 4, -60],
                                      "size": [4, 4, 4], "color": [140, 140, 150]}), 30, (), 2)
        self.assertEqual(out["props"][2]["shape"], "Block")

    def test_the_schema_offers_all_of_them(self):
        shapes = plan_schema.build_schema()["properties"]["props"]["items"]["properties"]["shape"]["enum"]
        self.assertEqual(set(shapes), set(bsm.SHAPES))

    def test_the_renderer_draws_them_all(self):
        from_shape = set()
        for line in SHAPES_JS.splitlines():
            text = line.strip()
            if text.startswith("'"):
                from_shape.add(text.strip("',"))
        for shape in bsm.SHAPES:
            self.assertIn(shape, SHAPES_JS, f"map_shapes.mjs has no {shape}")
        self.assertIn("export const SHAPES", SHAPES_JS)
        # The page must consume the module rather than keep its own three shapes.
        self.assertIn("buildShapeGeometry", RENDERER)
        self.assertNotIn("Block:new THREE.BoxGeometry(1,1,1),Ball:", RENDERER)

    def test_studio_gets_a_real_part_type_for_each_shape(self):
        for shape in sorted(bsm.SHAPES):
            studio_shape = bsm.STUDIO_SHAPE_FALLBACK.get(shape, shape)
            self.assertIn(studio_shape, ("Ball", "Block", "Cylinder", "Wedge", "CornerWedge"))
            self.assertIn(f'"{studio_shape}"', STUDIO)

    def test_the_smoke_test_builds_every_shape_for_real(self):
        node = __import__("shutil").which("node")
        if not node or not (ROOT / "tools/video_renderer/node_modules/three").exists():
            self.skipTest("node or three is not installed")
        result = subprocess.run([node, "map_features_smoke_test.mjs"],
                                cwd=ROOT / "tools/video_renderer",
                                capture_output=True, text=True, timeout=180)
        self.assertEqual(result.returncode, 0, result.stderr[-1500:])
        self.assertIn("shapes built with real Three.js", result.stdout)


class LightTests(unittest.TestCase):
    def test_a_light_is_kept_with_its_dials(self):
        out = bsm.validate(plan_with({
            "name": "Warm Lantern", "shape": "Cylinder", "material": "Neon",
            "position": [2, 6, -45], "size": [1, 3, 1], "color": [255, 210, 140],
            "light": {"kind": "point", "color": [255, 200, 90], "brightness": 3,
                      "range": 40, "angle": 120},
        }), 30, (), 2)
        light = out["props"][2]["light"]
        self.assertEqual(light["kind"], "Point")
        self.assertEqual(light["color"], [255, 200, 90])
        self.assertEqual(light["brightness"], 3)
        self.assertEqual(light["range"], 40)

    def test_brightness_range_and_angle_are_bounded(self):
        light = bsm.normalize_light({"brightness": 99, "range": -5, "angle": 500})
        self.assertEqual(light["brightness"], 5.0)
        self.assertEqual(light["range"], 0.0)
        self.assertEqual(light["angle"], 180.0)
        self.assertGreaterEqual(light["brightness"], 0)
        self.assertLessEqual(light["range"], 60)

    def test_the_colour_can_be_a_hex_string(self):
        self.assertEqual(bsm.normalize_light({"hex": "#ff8000"})["color"], [255, 128, 0])

    def test_a_light_can_be_switched_off(self):
        self.assertIsNone(bsm.normalize_light({"brightness": 0, "enabled": False}))
        self.assertIsNone(bsm.normalize_light(False))
        self.assertIsNone(bsm.normalize_light(""))

    def test_a_bare_true_means_a_plain_lamp(self):
        self.assertEqual(bsm.normalize_light(True)["kind"], "Point")

    def test_spot_and_surface_kinds(self):
        self.assertEqual(bsm.normalize_light("spotlight")["kind"], "Spot")
        self.assertEqual(bsm.normalize_light({"kind": "surface"})["kind"], "Surface")

    def test_too_many_lights_are_dropped_not_rendered(self):
        props = [{"name": f"Lamp {i}", "shape": "Block", "material": "Neon",
                  "position": [i % 20 - 10, 2, -60 - i], "size": [1, 1, 1],
                  "color": [255, 255, 255], "light": {"brightness": 2}}
                 for i in range(60)]
        out = bsm.validate({"props": props,
                            "camera_shots": [{"time": 0, "position": [0, 9, 20],
                                              "target": [0, 3, 0],
                                              "focus_username": "world",
                                              "transition": "smooth"}],
                            "face_expressions": [{"time": 0, "expression": "neutral",
                                                  "intensity": 0.5, "username": "x"}]},
                           30, (), 1)
        kept = [p for p in out["props"] if "light" in p]
        self.assertEqual(len(kept), 40)

    def test_the_page_builds_lights_from_the_blueprint(self):
        self.assertIn("new THREE.PointLight", RENDERER)
        self.assertIn("new THREE.SpotLight", RENDERER)
        self.assertIn("lightSummary", RENDERER)

    def test_studio_export_writes_the_same_light(self):
        self.assertIn("PointLight", STUDIO)
        self.assertIn("SpotLight", STUDIO)
        self.assertIn("SurfaceLight", STUDIO)


class EffectTests(unittest.TestCase):
    def test_the_catalog_has_520_or_more_presets(self):
        names = catalog.preset_names()
        self.assertGreaterEqual(len(names), 520)
        self.assertEqual(len(names), len(set(names)))
        self.assertIn("gold sparkles", names)
        self.assertIn("cyan smoke", names)
        self.assertIn("rainbow lightning", names)

    def test_every_preset_resolves_to_a_complete_effect(self):
        for name in catalog.preset_names():
            effect = catalog.preset(name)
            self.assertEqual(set(effect), set(catalog.EFFECT_KEYS), name)
            self.assertTrue(all(isinstance(channel, int) for channel in effect["color"]), name)

    def test_families_and_colours_are_what_the_prompt_promises(self):
        self.assertEqual(len(catalog.FAMILIES), 20)
        self.assertEqual(len(catalog.PALETTES), 26)
        for family in ("sparkles", "confetti", "smoke", "rain", "snow", "lightning", "hearts"):
            self.assertIn(family, catalog.FAMILIES)

    def test_the_dials_are_bounded(self):
        effect = catalog.resolve({"family": "sparkles", "rate": 9, "size": 99,
                                  "speed": -3, "life": 0.01, "gravity": 100, "spread": 4})
        self.assertEqual(effect["rate"], 1.0)
        self.assertEqual(effect["size"], 6.0)
        self.assertEqual(effect["speed"], 0.0)
        self.assertEqual(effect["life"], 0.1)
        self.assertEqual(effect["gravity"], 6.0)
        self.assertEqual(effect["spread"], 1.0)

    def test_an_unknown_effect_still_plays_something(self):
        self.assertEqual(catalog.resolve("zorp")["family"], "sparkles")
        # A word that does name a real family is honoured, not thrown away.
        self.assertEqual(catalog.resolve("unicorn dust")["family"], "dust")
        self.assertEqual(catalog.resolve({"family": "nonsense"})["family"], "sparkles")
        self.assertIsNone(catalog.resolve(None))

    def test_validate_keeps_effects_and_drops_the_extras(self):
        props = [{"name": f"Prop {i}", "shape": "Block", "material": "Brick",
                  "position": [i % 10 - 5, 2, -50 - i], "size": [2, 2, 2],
                  "color": [200, 180, 150], "effect": "cyan smoke"}
                 for i in range(70)]
        out = bsm.validate({"props": props,
                            "camera_shots": [{"time": 0, "position": [0, 9, 20],
                                              "target": [0, 3, 0],
                                              "focus_username": "world",
                                              "transition": "smooth"}],
                            "face_expressions": [{"time": 0, "expression": "neutral",
                                                  "intensity": 0.5, "username": "x"}]},
                           30, (), 1)
        self.assertEqual(len([p for p in out["props"] if "effect" in p]), 60)
        self.assertEqual(out["props"][0]["effect"]["family"], "smoke")
        self.assertEqual(out["props"][0]["effect"]["color"], [64, 214, 232])

    def test_the_schema_offers_the_effect_fields(self):
        fields = plan_schema.build_schema()["properties"]["props"]["items"]["properties"]["effect"]
        self.assertEqual(set(fields["properties"]), {"name", "family", "color", "rate", "size",
                                                     "speed", "life", "gravity", "spread"})
        self.assertEqual(set(fields["properties"]["family"]["enum"]), set(catalog.FAMILIES))

    def test_the_page_builds_the_particles(self):
        self.assertIn("createParticleField", RENDERER)
        self.assertIn("sampleParticles", RENDERER)
        self.assertIn("effectSummary", RENDERER)
        self.assertIn("updateEffects(t)", RENDERER)
        self.assertIn("PointsMaterial", RENDERER)

    def test_particles_are_a_pure_function_of_time(self):
        self.assertIn("export function sampleParticles", PARTICLES_JS)
        self.assertIn("position.needsUpdate", RENDERER)

    def test_lua_export_writes_a_particle_emitter(self):
        out = bsm.validate(plan_with({
            "name": "Wish Fountain", "shape": "Cylinder", "material": "Neon",
            "position": [3, 3, -50], "size": [2, 6, 2], "color": [140, 220, 255],
            "effect": {"name": "gold sparkles", "rate": 0.9},
        }), 30, (), 2)
        lua_path = Path("/tmp/map_shape_effect_test.lua")
        bsm.emit_lua(out, lua_path)
        lua = lua_path.read_text(encoding="utf-8")
        self.assertIn("ParticleEmitter", lua)
        self.assertIn("emitter.Rate", lua)
        self.assertIn("LightEmission", lua)
        self.assertIn("partTypes", lua)


class PromptTests(unittest.TestCase):
    """The model must be told it may use all of this."""

    def test_the_prompt_names_the_new_shapes(self):
        for shape in ("Wedge", "Prism", "Cone", "Pyramid", "Torus", "Ring", "Hemisphere", "Truss"):
            self.assertIn(shape, WORKFLOW)

    def test_the_prompt_explains_lights_and_effects(self):
        self.assertIn("brightness", WORKFLOW)
        self.assertIn("range is how far the pool of light reaches", WORKFLOW)
        self.assertIn("520 ready presets", WORKFLOW)
        self.assertIn("gold sparkles", WORKFLOW)

    def test_the_sub_agent_is_invited_for_maps_and_cameras(self):
        self.assertIn("USE THE GEMINI SUB-AGENT FOR THE MAP AND THE CAMERAS", WORKFLOW)
        self.assertIn('"write"', WORKFLOW)

    def test_search_is_no_longer_forced_up_front(self):
        self.assertNotIn("Web search the AI can reuse in every planning stage", WORKFLOW)
        self.assertIn("nothing is scraped unless you ask", WORKFLOW)

    def test_gemini_knows_the_new_fields(self):
        import gemini_workspace
        guide = gemini_workspace.guide({"topic": "map", "instruction": "design a lamp"})
        self.assertIn("Wedge", guide)
        self.assertIn("brightness", guide)
        self.assertIn("520 presets", guide)


if __name__ == "__main__":
    unittest.main()


class RichnessReportTests(unittest.TestCase):
    """The run log must say whether the AI actually used shapes, lamps and effects.

    Run #82 produced 5000 plain Blocks with no light of its own, and nothing in
    the log said so - it only showed up in the finished video. The world review
    now counts them, so the next run answers the question by itself.
    """

    def test_the_world_review_counts_shapes_lamps_and_effects(self):
        self.assertIn("from collections import Counter", WORKFLOW)
        self.assertIn("World detail: shapes", WORKFLOW)
        self.assertIn("lamp(s)", WORKFLOW)
        self.assertIn("particle effect(s)", WORKFLOW)
        self.assertIn("world_richness.json", WORKFLOW)

    def test_a_plain_block_world_is_called_out_without_forcing_anything(self):
        self.assertIn("is made only of plain blocks with no lamps or effects", WORKFLOW)
        self.assertIn("nothing is forced", WORKFLOW)

    def test_the_step_summary_lists_them_too(self):
        self.assertIn("- Shapes: {', '.join(", WORKFLOW)
        self.assertIn("- Lamps: {lights}; particle effects:", WORKFLOW)

    def test_the_counts_match_what_the_validator_keeps(self):
        import json
        plan = bsm.validate(plan_with({
            "name": "Lamp Probe", "shape": "triangle", "material": "Neon",
            "position": [4, 5, -45], "size": [4, 6, 4], "color": [255, 200, 140],
            "light": True, "effect": "gold sparkles",
        }), 30, (), 2)
        shapes = {}
        for prop in plan["props"]:
            shapes[prop["shape"]] = shapes.get(prop["shape"], 0) + 1
        self.assertEqual(shapes.get("Wedge"), 1)
        self.assertEqual(sum(1 for p in plan["props"] if p.get("light")), 1)
        self.assertEqual(sum(1 for p in plan["props"] if p.get("effect")), 1)
        json.dumps({"shapes": shapes})  # the report is plain JSON
