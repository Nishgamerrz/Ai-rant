"""The world plan must come back in the keys the validator actually reads.

Run #54 spent 22 minutes writing a blueprint that was thrown away:

  "type": "block"          (validator wanted "shape")
  "material": "brick"      (lowercase, not Roblox's "Brick")
  "ambient_light"          (validator wanted "ambient_color")
  "username": "LeadName"   (a placeholder, not the supplied cast)
  six props                (validator needs 8+)

A JSON schema now fixes the key names, the spelling and the cast up front.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from build_story_map import normalize_material, normalize_shape, validate  # noqa: E402
from plan_schema import build_schema  # noqa: E402

CAST = ["normal", "noob"]


class SchemaTests(unittest.TestCase):
    def test_schema_pins_keys_materials_and_cast(self):
        schema = build_schema(CAST)
        props = schema["properties"]["props"]["items"]["properties"]
        self.assertIn("shape", props)
        self.assertNotIn("type", props)
        self.assertIn("Brick", props["material"]["enum"])
        self.assertNotIn("brick", props["material"]["enum"])
        self.assertIn("ambient_color", schema["properties"])
        self.assertNotIn("ambient_light", schema["properties"])
        self.assertGreaterEqual(schema["properties"]["props"]["minItems"], 8)

    def test_schema_limits_usernames_to_the_real_cast(self):
        schema = build_schema(CAST)
        placements = schema["properties"]["character_placements"]["items"]["properties"]["username"]
        self.assertEqual(placements["enum"], CAST)
        shots = schema["properties"]["camera_shots"]["items"]["properties"]["focus_username"]
        self.assertEqual(shots["enum"], [*CAST, "world"])
        beats = schema["properties"]["face_expressions"]["items"]["properties"]["username"]
        self.assertEqual(beats["enum"], CAST)

    def test_cli_writes_a_schema_for_the_supplied_cast(self):
        with self.subTest("cli"):
            import tempfile

            with tempfile.TemporaryDirectory() as tmp:
                cast_path = Path(tmp) / "characters.json"
                out_path = Path(tmp) / "schema.json"
                cast_path.write_text(json.dumps(CAST), encoding="utf-8")
                result = subprocess.run(
                    [sys.executable, "tools/plan_schema.py",
                     "--usernames", str(cast_path), "--output", str(out_path)],
                    cwd=ROOT, capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 0, msg=result.stderr[-2000:])
                data = json.loads(out_path.read_text(encoding="utf-8"))
                self.assertEqual(data["properties"]["props"]["items"]
                                 ["properties"]["shape"]["enum"],
                                 ["Block", "Ball", "Cylinder"])


class AliasTests(unittest.TestCase):
    """Whatever spelling the model invents, the validator now understands it."""

    def test_shapes(self):
        self.assertEqual(normalize_shape("block"), "Block")
        self.assertEqual(normalize_shape("Sphere"), "Ball")
        self.assertEqual(normalize_shape("cylinder"), "Cylinder")
        self.assertEqual(normalize_shape(None), "Block")

    def test_materials(self):
        self.assertEqual(normalize_material("brick"), "Brick")
        self.assertEqual(normalize_material("smooth_plastic"), "SmoothPlastic")
        self.assertEqual(normalize_material("Wood Planks"), "Wood")
        self.assertEqual(normalize_material("metal"), "Metal")
        self.assertEqual(normalize_material(None), "SmoothPlastic")

    def test_a_run_54_style_blueprint_now_validates(self):
        plan = {
            "ground_material": "grass",
            "ground_color": [88, 166, 91],
            "ambient_light": [185, 205, 225],
            "props": [
                {"name": "Market Hall", "type": "block", "material": "brick",
                 "position": [-55, 8, 35], "size": [24, 16, 20], "color": [30, 210, 240]},
                {"name": "School Courtyard", "type": "block", "material": "metal",
                 "position": [0, 8, 0], "size": [32, 16, 20], "color": [170, 130, 240]},
                {"name": "Bus Stop", "type": "block", "material": "concrete",
                 "position": [25, 8, 0], "size": [12, 12, 16], "color": [200, 130, 240]},
                {"name": "Soccer Field", "type": "block", "material": "grass",
                 "position": [0, 0, -20], "size": [40, 4, 40], "color": [110, 200, 40]},
                {"name": "Library", "type": "block", "material": "wood",
                 "position": [-25, 8, -20], "size": [20, 16, 20], "color": [150, 120, 80]},
                {"name": "Streetlamp", "type": "block", "material": "metal",
                 "position": [6, 0, 20], "size": [3, 3, 4], "color": [130, 200, 240]},
                {"name": "Kiosk", "type": "block", "material": "smooth plastic",
                 "position": [40, 4, 40], "size": [8, 8, 8], "color": [200, 200, 90]},
                {"name": "Ball A", "type": "sphere", "material": "Neon",
                 "position": [-40, 2, 40], "size": [2, 2, 2], "color": [255, 80, 80]},
            ],
            "character_placements": [
                {"username": "normal", "role": "lead", "position": [0, 0, 24]},
                {"username": "noob", "role": "supporting", "position": [-6, 0, 24]},
            ],
        }
        cleaned = validate(plan, 120, CAST, min_props=8)
        self.assertEqual(len(cleaned["props"]), 8)
        self.assertEqual({p["shape"] for p in cleaned["props"]}, {"Block", "Ball"})
        self.assertIn("Brick", {p["material"] for p in cleaned["props"]})
        self.assertEqual(cleaned["ambient_color"], [185, 205, 225])
        self.assertEqual(cleaned["ground_material"], "Grass")
        self.assertEqual([p["username"] for p in cleaned["character_placements"]],
                         ["normal", "noob"])


class PromptTests(unittest.TestCase):
    def test_prompt_names_the_real_cast(self):
        workflow = (ROOT / ".github" / "workflows" / "main.yml").read_text(encoding="utf-8")
        self.assertIn("The ONLY usernames that exist are:", workflow)
        self.assertIn('FIRST_CAST=$(jq -r', workflow)
        self.assertIn('SECOND_CAST=$(jq -r', workflow)
        self.assertIn('{"username":"${FIRST_CAST}"', workflow)

    def test_prompt_demands_the_exact_keys(self):
        workflow = (ROOT / ".github" / "workflows" / "main.yml").read_text(encoding="utf-8")
        self.assertIn("USE THE EXACT KEYS: shape (never type/dimensions)", workflow)
