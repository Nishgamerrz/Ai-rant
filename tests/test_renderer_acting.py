#!/usr/bin/env python3
"""The shipped MP4 had an exploding character, standing still.

Two faults, both in the renderer, both invisible until the video was watched:

1. the avatar was soft-skinned, so any pose that moved two joints apart stretched
   the mesh into spikes and tore the body apart ("exploding character");
2. each character slid round a sine circle barely a stud wide with one walk cycle
   looping forever, facing 180 degrees away from the way it was travelling,
   because the avatar's front is +Z and the yaw used atan2(vx, -vz) ("no moving
   around, just animation").

The fixes live in `avatar_rig.mjs` (rigid, part-aware rig), `actor_motion.mjs`
(blocking between camera cuts) and the page script inside `render_short.mjs`.
These tests check the page itself: it must parse, it must use the new machinery,
and it must not reintroduce the old bugs. The maths itself is tested in Node by
`avatar_rigid_parts_smoke_test.mjs` and `actor_motion_smoke_test.mjs`.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RENDERER = ROOT / "tools" / "video_renderer"


def page_script() -> str:
    """The module script the browser actually runs, as text."""
    source = (RENDERER / "render_short.mjs").read_text(encoding="utf-8")
    start = source.index('<script type="module">') + len('<script type="module">')
    end = source.index("</script>", start)
    return source[start:end]


class PageScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = page_script()

    def test_the_page_script_parses(self):
        """A syntax error here only shows up three hours into a render."""
        if shutil.which("node") is None:
            self.skipTest("node is not available")
        body = re.sub(r"\$\{[^}]*\}", "0", self.script)
        with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False) as handle:
            handle.write(body)
            path = handle.name
        try:
            result = subprocess.run(["node", "--check", path], capture_output=True, text=True)
        finally:
            Path(path).unlink(missing_ok=True)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])

    def test_the_page_uses_the_blocking_module(self):
        for needle in ("/actor_motion.mjs", "planMarks", "poseAt(", "roomBoundsFrom"):
            self.assertIn(needle, self.script)

    def test_the_page_uses_the_rigid_rig(self):
        source = (RENDERER / "render_short.mjs").read_text(encoding="utf-8")
        self.assertIn("measureRigStretch", self.script)
        self.assertIn("rigStretchSummary", self.script)
        # A part that deforms is the exploding-character bug: stop before encoding.
        self.assertIn("avatar mesh deforms by", source)
        self.assertIn("no MP4 is written", source)

    def test_the_old_in_place_circle_is_gone(self):
        # The sine sweep around the base position was the "standing still" bug.
        self.assertNotIn("Math.sin(cycle*.42)", self.script)
        self.assertNotIn("Math.cos(cycle*.34+actor.phase)", self.script)
        self.assertNotIn("actor.stride*", self.script)

    def test_the_body_cannot_lift_off_the_floor(self):
        # The old finale jumped the lead three studs into the air and left the feet
        # under the ground, which read as a broken model.
        self.assertNotIn("jumpHeight", self.script)
        self.assertIn("actor.root.position.set(pose.x, actor.baseY, pose.z)", self.script)

    def test_the_facing_yaw_uses_the_avatars_real_front(self):
        # atan2(vx, -vz) faced the body the opposite way to its heading.
        self.assertNotIn("Math.atan2(vx", self.script)
        self.assertIn("yawToward", self.script)

    def test_standing_still_does_not_run_a_walk_cycle(self):
        self.assertIn("idleAvatarRig(actor.rig, t, actor.phase, 1 - pose.moving)", self.script)
        self.assertIn("pose.moving", self.script)

    def test_the_camera_stays_inside_the_room(self):
        self.assertIn("roomBounds", self.script)
        self.assertIn("chooseSafeCamera(target.toArray(),desired.toArray(),cameraBlockers,preferred[0],preferred[1],roomBounds)", self.script)
        self.assertIn("chooseFaceCamera(head.toArray(),desired.toArray(),cameraBlockers,faceDistance,roomBounds)", self.script)

    def test_the_cast_cannot_walk_through_the_walls(self):
        self.assertIn("roomBoundsFrom(DATA.plan.interior)", self.script)

    def test_the_camera_helpers_only_get_names_the_page_declares(self):
        """Run #111 died at the preflight with `cameraBlockers is not defined`.

        The camera refactor for indoor scenes rewrote the two calls and dropped
        the `const cameraBlockers=...` line that fed them. Nothing caught it
        locally: the page is a string inside a Node file, so `node --check` only
        proves it parses, and the name was only read inside the browser. A bare
        identifier handed to one of the camera helpers must therefore be declared
        by the page itself.
        """
        declared = set(re.findall(r"\b(?:const|let|var|class|function)\s+([A-Za-z_$][\w$]*)", self.script))
        self.assertIn("cameraBlockers", declared, "the page must build the camera blocker list")
        bare = set()
        for helper in ("chooseSafeCamera(", "chooseFaceCamera("):
            for match in re.finditer(re.escape(helper), self.script):
                depth, index, current = 1, match.end(), ""
                while index < len(self.script) and depth:
                    char = self.script[index]
                    if char in "([{":
                        depth += 1
                    elif char in ")]}":
                        depth -= 1
                        if depth == 0:
                            bare.add(current.strip())
                            break
                    if depth == 1 and char == ",":
                        bare.add(current.strip())
                        current = ""
                    else:
                        current += char
                    index += 1
        bare = {name for name in bare if re.fullmatch(r"[A-Za-z_$][\w$]*", name)}
        self.assertIn("cameraBlockers", bare)
        missing = sorted(name for name in bare if name not in declared)
        self.assertEqual(missing, [], f"the page reads names it never declares: {missing}")


class RigidRigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (RENDERER / "avatar_rig.mjs").read_text(encoding="utf-8")

    def test_every_part_follows_exactly_one_bone(self):
        # The guarantee: a rigid part cannot stretch, tear or explode.
        self.assertIn("indices[vertex * 4] = index;", self.source)
        self.assertIn("weights[vertex * 4] = 1;", self.source)

    def test_the_part_rig_is_the_default_path(self):
        self.assertIn("if (classified.confident)", self.source)
        self.assertIn("mode: 'rigid-parts'", self.source)

    def test_joints_are_derived_from_the_parts_not_guessed(self):
        for needle in ("joints[`${side}UpperArm`]", "joints[`${side}LowerLeg`]",
                       "joints[`${side}Foot`]", "headPart.box.min.y"):
            self.assertIn(needle, self.source)

    def test_the_walk_cycle_has_an_amplitude(self):
        self.assertIn("gaitAmount = 1", self.source)
        self.assertIn("export function idleAvatarRig", self.source)

    def test_native_clips_can_be_faded_out(self):
        self.assertIn("blend = 1", self.source)
        self.assertIn("clamp(blend,0,1)", self.source)


class RendererTestWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.package = json.loads((RENDERER / "package.json").read_text(encoding="utf-8"))
        cls.workflow = (ROOT / ".github" / "workflows" / "main.yml").read_text(encoding="utf-8")

    def test_the_new_renderer_tests_exist(self):
        self.assertTrue((RENDERER / "avatar_rigid_parts_smoke_test.mjs").is_file())
        self.assertTrue((RENDERER / "actor_motion_smoke_test.mjs").is_file())
        self.assertEqual(self.package["scripts"]["test:avatar-rigid"],
                         "node avatar_rigid_parts_smoke_test.mjs")
        self.assertEqual(self.package["scripts"]["test:actor-motion"],
                         "node actor_motion_smoke_test.mjs")

    def test_the_workflow_runs_them_before_the_render(self):
        for script in ("npm run test:avatar-rigid", "npm run test:actor-motion"):
            self.assertIn(script, self.workflow)


class RigidAvatarNodeTests(unittest.TestCase):
    """Run the two Node checks that prove the behaviour, when node is available."""

    def _run(self, name):
        if shutil.which("node") is None:
            self.skipTest("node is not available")
        if not (RENDERER / "node_modules" / "three").is_dir():
            self.skipTest("renderer dependencies are not installed")
        result = subprocess.run(["node", name], cwd=RENDERER, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout[-2000:] + result.stderr[-2000:])
        return result.stdout

    def test_the_real_avatar_cannot_deform(self):
        output = self._run("avatar_rigid_parts_smoke_test.mjs")
        self.assertIn("0% deformation", output)

    def test_the_cast_walks_between_cuts(self):
        output = self._run("actor_motion_smoke_test.mjs")
        self.assertIn("nobody left the room", output)
        studs = float(re.search(r"([0-9.]+) studs walked", output).group(1))
        self.assertGreater(studs, 8, "a character must cross the scene, not stand on one spot")


if __name__ == "__main__":
    unittest.main()
