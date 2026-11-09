#!/usr/bin/env python3
"""An indoor story must be rendered INSIDE a room.

Run #109 told a bedroom story ("two brothers keep each other awake in a cramped
bedroom") and produced a video of an open 640-stud world: a workshop wall, grass,
sky, and no room anywhere. Nothing in the workflow had ever asked for a room, and
the review pass that deletes "camera blockers" deleted the furniture that would
have made one.

These tests lock the fix down:

* the scene mode is decided from the story's own words (room words vs outdoor
  words), so a bedroom story cannot silently become a city;
* the builder turns that mode into a real room - floor, four walls, ceiling,
  door, window, room-sized furniture, the AI's props squeezed in where they fit;
* every camera ends up inside those walls, and a pure-mathematics ray cast proves
  each shot sees walls/ceiling rather than open sky;
* the review pass keeps the shell, keeps the floor under the cast's feet, never
  pads a room with plaza decor, and never pushes the camera through the plaster.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import build_story_map as build  # noqa: E402
import realign_story_map as realign  # noqa: E402
import scene_mode  # noqa: E402

BEDROOM_TOPIC = ("In a world where the last person to fall asleep each night gets "
                 "one wish, two brothers keep each other awake on purpose in a "
                 "cramped bedroom")

CAST = ["normal", "noob"]

PLAN = {
    "name": "The Last Wish Bedroom",
    "theme": "A cramped bedroom where the last one awake gets a wish",
    "ground_material": "Wood",
    "ground_color": [150, 190, 225],
    "ambient_color": [190, 200, 215],
    "props": [
        {"name": "Rusty Workshop Wall North", "model": "workshop", "shape": "Block",
         "material": "Wood", "position": [100, 6, 110], "size": [30, 12, 0.5],
         "color": [140, 120, 100], "physics": "static"},
        {"name": "Bed", "model": "furniture", "shape": "Block", "material": "Wood",
         "position": [-10, 1.5, 30], "size": [6, 3, 7], "color": [200, 160, 120],
         "physics": "static"},
        {"name": "Nightstand", "model": "furniture", "shape": "Block",
         "material": "Wood", "position": [-14, 1, 30], "size": [2, 2, 2],
         "color": [180, 140, 100], "physics": "static"},
        {"name": "Desk", "model": "furniture", "shape": "Block", "material": "Wood",
         "position": [12, 1.5, 32], "size": [4, 3, 2], "color": [190, 150, 110],
         "physics": "static"},
        {"name": "Chair", "model": "furniture", "shape": "Block", "material": "Wood",
         "position": [12, 1, 29], "size": [2, 2, 2], "color": [170, 130, 95],
         "physics": "static"},
        {"name": "Lamp", "model": "lamp", "shape": "Cylinder", "material": "Neon",
         "position": [14, 4, 40], "size": [1, 5, 1], "color": [255, 230, 180],
         "physics": "static"},
        {"name": "Bookshelf", "model": "shelf", "shape": "Block", "material": "Wood",
         "position": [8, 4, 40], "size": [4, 8, 1.5], "color": [160, 120, 90],
         "physics": "static"},
        {"name": "Plant", "model": "plant", "shape": "Cylinder", "material": "Wood",
         "position": [15, 2, 26], "size": [2, 4, 2], "color": [90, 160, 90],
         "physics": "static"},
    ],
    "character_placements": [
        {"username": "normal", "role": "lead", "position": [0, 0, 24]},
        {"username": "noob", "role": "supporting", "position": [-6, 0, 24]},
    ],
    "camera_shots": [
        {"time": 0, "position": [0, 75, 170], "target": [0, 3, 24],
         "focus_username": "normal", "transition": "smooth", "framing": "auto"},
        {"time": 30, "position": [3, 6, 30], "target": [0, 5, 24],
         "focus_username": "noob", "transition": "snap", "framing": "face",
         "face_distance": 2.6},
        {"time": 60, "position": [0, 10, 44], "target": [0, 4, 24],
         "focus_username": "normal", "transition": "smooth", "framing": "wide"},
    ],
    "face_expressions": [
        {"time": 1, "expression": "neutral", "intensity": 0.6, "username": "normal"},
        {"time": 20, "expression": "happy", "intensity": 1, "username": "noob"},
        {"time": 40, "expression": "worried", "intensity": 0.8, "username": "normal"},
    ],
    "search_queries": [],
}


def build_plan(mode_flag=(), topic=BEDROOM_TOPIC, plan=None, target=1260):
    """Run the builder the way the workflow does and return the finished plan."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        response = tmp_path / "response.json"
        response.write_text(json.dumps({"message": {"content": json.dumps(plan or PLAN)}}),
                            encoding="utf-8")
        cast_file = tmp_path / "characters.json"
        cast_file.write_text(json.dumps(CAST), encoding="utf-8")
        output = tmp_path / "map.json"
        subprocess.run(
            [sys.executable, str(ROOT / "tools" / "build_story_map.py"), str(response),
             str(output), "120", "--json-only", "--strict", "--min-props", "8",
             "--target-props", str(target), "--usernames", str(cast_file),
             "--story-topic", topic, *mode_flag],
            check=True, capture_output=True, text=True,
        )
        return json.loads(output.read_text(encoding="utf-8"))


def by_name(plan, needle):
    return [part for part in plan["props"] if needle.lower() in part["name"].lower()]


class SceneModeTests(unittest.TestCase):
    def test_bedroom_story_is_interior(self):
        mode = scene_mode.detect(BEDROOM_TOPIC, "")
        self.assertEqual(mode["mode"], "interior")
        self.assertEqual(mode["size"], "tiny")      # "cramped"
        self.assertGreater(mode["width"], 10)

    def test_narration_alone_can_decide(self):
        mode = scene_mode.detect("", "Two brothers whisper in the dark classroom.")
        self.assertEqual(mode["mode"], "interior")

    def test_open_world_story_stays_outdoor(self):
        mode = scene_mode.detect("In a world where gravity naps in the city square", "")
        self.assertEqual(mode["mode"], "outdoor")
        self.assertEqual(scene_mode.prompt_block(mode), "")

    def test_interior_prompt_block_tells_the_ai_to_build_a_room(self):
        block = scene_mode.prompt_block(scene_mode.detect(BEDROOM_TOPIC, ""))
        self.assertIn("INSIDE ONE ROOM", block)
        self.assertIn("bed", block)
        self.assertIn("Camera: every shot must be INSIDE the room", block)
        # It must beat the open-world rules that come later in the same prompt.
        self.assertIn("overrides every later instruction", block)
        self.assertIn("640-by-640-stud map", block)

    def test_env_written_for_the_workflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / "env"
            mode = scene_mode.detect(BEDROOM_TOPIC, "")
            scene_mode.write_env(mode, str(env))
            text = env.read_text(encoding="utf-8")
        self.assertIn("WORLD_MODE=interior", text)
        self.assertIn("ROOM_WIDTH=", text)


class InteriorBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = build_plan()
        cls.room = cls.plan["interior"]

    def test_room_is_walled_enclosed_and_has_a_door_and_window(self):
        names = " | ".join(part["name"] for part in self.plan["props"])
        for needed in ("Room Floor", "Room Ceiling", "Room Wall Left", "Room Wall Right",
                       "Room Wall Back", "Room Front Wall", "Room Door", "Room Window Glass"):
            self.assertIn(needed, names)

    def test_no_open_world_buildings_or_plaza_decor(self):
        names = " ".join(part["name"] for part in self.plan["props"]).lower()
        for unwelcome in ("workshop wall", "market", "plaza", "fountain", "paving",
                          "lamp post", "street tree"):
            self.assertNotIn(unwelcome, names)
        self.assertLess(len(self.plan["props"]), 400)   # a room, not a city

    def test_furniture_is_room_sized(self):
        for part in self.plan["props"]:
            if part.get("shell") or "Beam" in part["name"]:
                continue      # beams and shell walls deliberately span the room
            self.assertLessEqual(max(part["size"]), 12.0, part["name"])
        self.assertTrue(by_name(self.plan, "Mattress"))     # the story's bed exists
        self.assertTrue(by_name(self.plan, "Wardrobe"))

    def test_every_prop_is_inside_the_walls(self):
        width = self.room["width"]
        depth = self.room["depth"]
        centre = self.room["centre_z"]
        top = self.room["height"]
        for part in self.plan["props"]:
            x, y, z = part["position"]
            sx, sy, sz = part["size"]
            self.assertLessEqual(abs(x) + sx / 2, width / 2 + 1.0, part["name"])
            self.assertLessEqual(abs(z - centre) + sz / 2, depth / 2 + 2.0, part["name"])
            self.assertLessEqual(y + sy / 2, top + 1.0, part["name"])

    def test_cameras_are_inside_the_room(self):
        half_x = self.room["width"] / 2
        half_z = self.room["depth"] / 2
        for shot in self.plan["camera_shots"]:
            x, y, z = shot["position"]
            self.assertLessEqual(abs(x), half_x, shot)
            self.assertLessEqual(abs(z - self.room["centre_z"]), half_z + 0.01, shot)
            self.assertGreaterEqual(y, 3.0)
            self.assertLessEqual(y, self.room["height"] - 1.0)

    def test_the_view_shows_a_room_not_the_sky(self):
        report = self.plan["interior_view"]
        self.assertGreaterEqual(len(report), 6)
        for entry in report:
            self.assertLessEqual(entry["sky"], 0.02, entry)
            self.assertGreater(entry["cast"], 0.1, entry)      # the cast is on camera
            self.assertGreater(entry["room"] + entry["furniture"], 0.05, entry)

    def test_more_than_one_camera_angle(self):
        positions = {tuple(shot["position"]) for shot in self.plan["camera_shots"]}
        self.assertGreaterEqual(len(positions), 6)

    def test_face_closeups_exist_and_are_close(self):
        faces = [shot for shot in self.plan["camera_shots"] if shot["framing"] == "face"]
        self.assertGreaterEqual(len(faces), 2)
        for shot in faces:
            distance = sum((shot["target"][axis] - shot["position"][axis]) ** 2
                           for axis in range(3)) ** 0.5
            self.assertLess(distance, 4.0, shot)
            self.assertGreater(distance, 1.2, shot)

    def test_cast_is_close_enough_to_share_a_frame(self):
        xs = [person["position"][0] for person in self.plan["character_placements"]]
        self.assertLessEqual(max(xs) - min(xs), 5.0)

    def test_outdoor_story_is_unchanged(self):
        outdoor = build_plan(topic="In a world where gravity naps over the city square")
        self.assertNotIn("interior", outdoor)
        self.assertFalse(any(part.get("shell") for part in outdoor["props"]))
        self.assertTrue(any("Workshop" in part["name"] for part in outdoor["props"]))

    def test_forced_outdoor_ignores_room_words(self):
        outdoor = build_plan(mode_flag=("--scene-mode", "outdoor"))
        self.assertNotIn("interior", outdoor)

    def test_forced_interior_size(self):
        plan = build_plan(mode_flag=("--interior", "medium"))
        self.assertEqual(plan["interior"]["width"], 44.0)


class InteriorReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = build_plan()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "map.json"
            path.write_text(json.dumps(cls.plan), encoding="utf-8")
            subprocess.run([sys.executable, str(ROOT / "tools" / "realign_story_map.py"),
                            str(path), "--passes", "2", "--target-parts", "5000"],
                           check=True, capture_output=True, text=True)
            cls.reviewed = json.loads(path.read_text(encoding="utf-8"))

    def test_shell_survives_the_review(self):
        names = {part["name"] for part in self.reviewed["props"]}
        for needed in ("Room Floor", "Room Ceiling", "Room Wall Left", "Room Wall Right"):
            self.assertIn(needed, names)

    def test_room_is_not_padded_with_plaza_decor(self):
        self.assertLessEqual(len(self.reviewed["props"]), len(self.plan["props"]) + 5)
        names = " ".join(part["name"] for part in self.reviewed["props"]).lower()
        self.assertNotIn("fountain", names)

    def test_cameras_stay_inside_after_the_review(self):
        room = self.reviewed["interior"]
        for shot in self.reviewed["camera_shots"]:
            x, _, z = shot["position"]
            self.assertLessEqual(abs(x), room["width"] / 2)
            self.assertLessEqual(abs(z - room["centre_z"]), room["depth"] / 2 + 0.01)

    def test_view_is_still_enclosed_after_the_review(self):
        for shot in self.reviewed["camera_shots"]:
            coverage = build.view_coverage(self.reviewed, shot["position"], shot["target"])
            self.assertLessEqual(coverage["sky"], 0.05, (shot["position"], coverage))

    def test_review_uses_the_room_lane(self):
        room = self.reviewed["interior"]
        realign.use_room_lane(room)
        try:
            self.assertLess(realign.CAST_LANE["x"], 20.0)     # not the open-world lane
            self.assertLess(realign.CAST_LANE["z_max"] - realign.CAST_LANE["z_min"], 12.0)
        finally:
            realign.CAST_LANE.update(realign.OUTDOOR_CAST_LANE)


class RendererHandoffTests(unittest.TestCase):
    def test_shell_parts_are_ordinary_parts_for_the_renderer(self):
        plan = build_plan()
        for part in plan["props"]:
            self.assertEqual(len(part["position"]), 3)
            self.assertEqual(len(part["size"]), 3)
            self.assertEqual(part["physics"], "static")
            self.assertGreaterEqual(min(part["size"]), 0.5)

    def test_lua_export_contains_the_room(self):
        plan = build_plan()
        with tempfile.TemporaryDirectory() as tmp:
            lua = Path(tmp) / "map.lua"
            build.emit_lua(plan, lua)
            text = lua.read_text(encoding="utf-8")
        self.assertIn("Room Ceiling", text)
        self.assertIn("Room Window Glass", text)


if __name__ == "__main__":
    unittest.main()
