"""A building must be built like a building, not left as one block.

The AI map plan gives anchor props. Before this, a "Story House" anchor became a
plain box with a flat lid, so a rendered short looked like coloured slabs: no
glass, no furniture, no plants, no roof shape. Now an anchor declares what it is
(`"model": "house"`), and the build expands it into a whole furnished group.

These tests build real worlds and check the parts exist.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import build_story_map as bsm  # noqa: E402


def anchor(name, model, position, size, color=(200, 180, 160), shape="Block"):
    return {"name": name, "model": model, "shape": shape, "material": "Brick",
            "position": list(position), "size": list(size), "color": list(color),
            "physics": "static"}


PLAN = {
    "name": "Model Town", "theme": "a small green town with houses, a shop and a garden",
    "ground_material": "Grass", "ground_color": [88, 166, 91],
    "ambient_color": [185, 205, 225],
    "props": [
        anchor("Story House", "house", (0, 6, 74), (26, 12, 20)),
        anchor("Corner Shop", "shop", (-60, 6, 60), (22, 12, 18), (196, 202, 210)),
        anchor("Old Oak", "tree", (-30, 3, 30), (8, 6, 8), (120, 90, 60)),
        anchor("Bus Bench", "bench", (22, 1, 46), (5, 2, 2), (150, 100, 60)),
        anchor("Flower Pot", "plant", (26, 1, 30), (3, 2, 3), (190, 120, 90)),
        anchor("Street Lamp", "lamp", (-26, 1, 30), (1, 6, 1), (90, 100, 110), shape="Cylinder"),
        anchor("Market Stall", "stall", (40, 1, 55), (6, 3, 4), (140, 100, 60)),
        anchor("Garden Fence", "fence", (70, 1, 20), (10, 2, 0.5), (130, 96, 60)),
    ],
    "character_placements": [], "camera_shots": [], "face_expressions": [],
    "search_queries": [],
}


class ModelVocabularyTests(unittest.TestCase):
    def test_models_are_recognised_from_plain_wording(self):
        for text, expected in (("house", "house"), ("Tree", "tree"),
                               ("street tree", "tree"), ("Lamp Post", "lamp"),
                               ("market stall", "stall"), ("bench", "bench"),
                               ("flower", "plant"), ("library", "library")):
            self.assertEqual(bsm.normalize_model(text), expected, text)

    def test_unknown_models_fall_back_to_a_name_match_or_nothing(self):
        self.assertEqual(bsm.normalize_model("Palm Tree"), "tree")
        self.assertEqual(bsm.normalize_model("gibberish"), "")

    def test_validate_keeps_the_declared_model(self):
        plan = bsm.validate(PLAN, 120, ["normal"], 4, "")
        models = {p["name"]: p.get("model") for p in plan["props"]}
        self.assertEqual(models["Story House"], "house")
        self.assertEqual(models["Old Oak"], "tree")
        self.assertEqual(models["Bus Bench"], "bench")


class BuildingExpansionTests(unittest.TestCase):
    def setUp(self):
        anchors = bsm.validate(PLAN, 120, ["normal"], 4, "")
        self.plan = bsm.validate(bsm.expand_plan(anchors, 1200), 120, ["normal"], 1200, "")
        self.props = self.plan["props"]
        self.names = [p["name"] for p in self.props]

    def parts(self, needle):
        return [p for p in self.props if needle in p["name"]]

    def test_a_house_gets_walls_glass_and_a_roof_shape(self):
        for needle in ("Story House Rear Wall", "Story House Left Wall",
                       "Story House Glass Window", "Story House Wood Entrance Door",
                       "Story House Gable Roof 1", "Story House Roof Ridge Cap",
                       "Story House Chimney"):
            self.assertTrue(self.parts(needle), f"missing {needle}")

    def test_glass_inside_the_building(self):
        self.assertTrue(self.parts("Story House Glass Display Case"))
        self.assertTrue(self.parts("Story House Glass Interior Partition"))
        glass = [p for p in self.props if p["material"] == "Glass"]
        self.assertGreaterEqual(len(glass), 6)

    def test_plants_and_leaves_inside_and_outside(self):
        self.assertTrue(self.parts("Story House Interior Plant"))
        self.assertTrue(self.parts("Story House Facade Vine"))
        self.assertTrue(self.parts("Story House Facade Leaf"))
        self.assertTrue(self.parts("Story House Window Box Flowers"))
        self.assertTrue(self.parts("Story House Doorstep Leaves"))
        # A tree is a trunk plus clusters of leaves, not one ball.
        self.assertTrue(self.parts("Old Oak Trunk"))
        self.assertGreaterEqual(len(self.parts("Old Oak Canopy Leaf Cluster")), 4)

    def test_furniture_inside_the_building(self):
        for needle in ("Story House Front Counter", "Story House West Table",
                       "Story House West Wall Shelf", "Story House Welcome Rug",
                       "Story House Ceiling Light"):
            self.assertTrue(self.parts(needle), f"missing {needle}")

    def test_each_group_model_becomes_a_group(self):
        expected = {
            "Bus Bench": ("Seat", "Backrest", "Leg"),
            "Flower Pot": ("Planter", "Soil", "Leaves"),
            "Street Lamp": ("Post", "Lantern", "Base"),
            "Market Stall": ("Counter", "Awning", "Produce"),
            "Garden Fence": ("Post", "Rail"),
        }
        for name, details in expected.items():
            for detail in details:
                self.assertTrue(self.parts(f"{name} {detail}"),
                                f"{name} has no {detail}")

    def test_the_anchor_is_replaced_by_its_group(self):
        # The bare anchor must not also render as one block.
        self.assertEqual(len([p for p in self.props if p["name"] == "Old Oak"]), 0)
        self.assertEqual(len([p for p in self.props if p["name"] == "Bus Bench"]), 0)

    def test_the_cast_lane_stays_clear(self):
        # Only waist-height obstacles matter: plaza floor tiles belong in the lane.
        for prop in self.props:
            x, y, z = prop["position"]
            top = y + prop["size"][1] / 2
            if abs(x) >= 20 or not 4 <= z <= 54 or top <= 1.2:
                continue
            self.fail(f"{prop['name']} blocks the cast lane at {x},{z} (top {top})")

    def test_negative_coordinates_are_not_clamped_to_the_origin(self):
        """A prop at x=-60 must stay at -60; snapping used to floor every negative
        coordinate at +0.5, which piled the whole map onto the spawn point."""
        places = {p["name"]: p["position"] for p in self.props}
        self.assertLess(places["Corner Shop Interior Floor"][0], -40)
        self.assertLess(places["Old Oak Trunk"][0], -20)
        self.assertGreater(places["Garden Fence Post 1"][0], 55)

    def test_names_stay_unique_and_sizes_valid(self):
        lowered = [p["name"].casefold() for p in self.props]
        self.assertEqual(len(lowered), len(set(lowered)))
        for prop in self.props:
            self.assertTrue(0.5 <= min(prop["size"]) <= max(prop["size"]) <= 64, prop["name"])
            self.assertGreaterEqual(min(prop["color"]), 0)


class SchemaTests(unittest.TestCase):
    def test_the_ai_may_declare_a_model(self):
        from plan_schema import build_schema

        schema = build_schema(["normal"])
        model = schema["properties"]["props"]["items"]["properties"]["model"]
        for expected in ("house", "tree", "bench", "stall", "plant", "lamp", "shop"):
            self.assertIn(expected, model["enum"])

    def test_the_prompt_teaches_models_and_glass(self):
        workflow = (ROOT / ".github" / "workflows" / "main.yml").read_text(encoding="utf-8")
        self.assertIn("BUILD MODELS, NOT BARE BLOCKS", workflow)
        self.assertIn('"model":"house"', workflow)
        self.assertIn("GLASS windows", workflow)
        self.assertIn("Never return one giant featureless box", workflow)

    def test_the_gemini_file_rules_describe_the_models(self):
        from gemini_workspace import guide

        text = guide({"kind": "edit", "instruction": "fix the map props"})
        self.assertIn("model", text)
        self.assertIn("gable roof", text)
        self.assertIn("glass", text.lower())


if __name__ == "__main__":
    unittest.main()
