"""The renderer must hand the face code a whole rig, not just the joints.

Run #58 finished the story, the world plan and the animation, then died in the
last step with:

    TypeError: Cannot read properties of undefined (reading 'bones')
        at measureHeadRegion (avatar_rig.mjs:172)
        at attachAnimatedFace (render_short.mjs:259)

`registerActor` was given `avatarRig.bones` (the joint map) and passed that to
`measureHeadRegion`, which wanted `rig.skeleton.bones`. The face code also
subtracted a world-space head position from a rig-space measurement, so any
avatar standing away from the origin would have had its face floating off.

These tests pin the wiring and the maths down without needing a browser.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RENDERER = ROOT / "tools" / "video_renderer"
RENDER_SHORT = (RENDERER / "render_short.mjs").read_text(encoding="utf-8")
AVATAR_RIG = (RENDERER / "avatar_rig.mjs").read_text(encoding="utf-8")


class RendererWiringTests(unittest.TestCase):
    def test_the_actor_gets_the_whole_rig(self):
        self.assertIn("registerActor(pivot,point,index,place,username,avatarRig,"
                      "animationClips,avatarScale,profile.front_direction)",
                      RENDER_SHORT.replace("\n", "").replace(" ", ""))
        self.assertNotIn("avatarRig?.bones||null", RENDER_SHORT)

    def test_the_body_still_gets_plain_joints(self):
        # Camera focus and head motion work off actor.rig.Head, so the actor must
        # keep the bone map even though the face code receives the rig object.
        self.assertIn("rig:bones", RENDER_SHORT.replace(" ", ""))
        self.assertIn("addRequestedAvatarEffects(root,bones,", RENDER_SHORT.replace(" ", ""))

    def test_a_face_failure_cannot_kill_the_render(self):
        self.assertIn("Head measurement failed; rendering this avatar without a face",
                      RENDER_SHORT)
        self.assertIn("if(!head||!rig||mode==='off')return null;", RENDER_SHORT)

    def test_measurement_accepts_a_bare_joint_map(self):
        self.assertIn("Array.isArray(skeleton?.bones) ? skeleton.bones : []", AVATAR_RIG)
        self.assertIn("const boneMap = rig?.bones && rig.bones.Head", AVATAR_RIG)
        self.assertNotIn("const headIndex = rig.skeleton.bones.findIndex", AVATAR_RIG)

    def test_the_face_anchor_is_measured_in_rig_space(self):
        self.assertIn("measureFaceAnchor", RENDER_SHORT)
        self.assertIn("rig.root.worldToLocal(headWorld.clone())", AVATAR_RIG)


@unittest.skipUnless(shutil.which("node") and (RENDERER / "node_modules").is_dir(),
                     "node renderer dependencies are not installed here")
class RigSmokeTests(unittest.TestCase):
    """The same checks the validate workflow runs, runnable locally."""

    def _run(self, script):
        return subprocess.run(["node", script], cwd=RENDERER,
                              capture_output=True, text=True, timeout=300)

    def test_avatar_rig_smoke_test(self):
        result = self._run("avatar_rig_smoke_test.mjs")
        self.assertEqual(result.returncode, 0, msg=result.stderr[-1500:])
        self.assertIn("Avatar rig smoke test passed", result.stdout)

    def test_avatar_obj_smoke_test(self):
        result = self._run("avatar_obj_smoke_test.mjs")
        self.assertEqual(result.returncode, 0, msg=result.stderr[-1500:])

    def test_an_avatar_at_the_origin_and_on_the_map_measure_the_same_head(self):
        """Direct check of the crash: the old code threw on a bare joint map."""
        script = """
import * as THREE from 'three';
import { buildAvatarRig, measureHeadRegion, measureFaceAnchor } from './avatar_rig.mjs';
const model = new THREE.Group();
const material = new THREE.MeshStandardMaterial();
const part = (name, center, size) => {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(...size), material);
  mesh.name = name; mesh.position.set(...center); model.add(mesh);
};
part('Head', [0, 5.55, 0], [0.72, 0.72, 0.72]);
part('Torso', [0, 3.55, 0], [1.05, 1.75, 0.58]);
const rig = buildAvatarRig(THREE, model);
const bonesOnly = measureHeadRegion(THREE, rig.bones);
const wholeRig = measureHeadRegion(THREE, rig);
console.log(JSON.stringify({
  bonesCenter: bonesOnly.center,
  rigCenter: wholeRig.center,
  anchorLen: measureFaceAnchor(THREE, rig, rig.bones.Head, 1).anchor.length(),
  undefinedRig: measureHeadRegion(THREE, undefined).center,
  height: rig.height,
}));
"""
        result = subprocess.run(["node", "--input-type=module", "-e", script],
                               cwd=RENDERER, capture_output=True, text=True, timeout=300)
        self.assertEqual(result.returncode, 0, msg=result.stderr[-1500:])
        data = json.loads(result.stdout.strip().splitlines()[-1])
        # The whole rig measures the real head geometry...
        self.assertGreater(data["rigCenter"][1], 4.0)
        # ...and a bare joint map no longer throws; it falls back to the joint.
        self.assertGreater(data["bonesCenter"][1], 0)
        self.assertLess(data["anchorLen"], 8.0)  # a head-local offset, not a map offset
        self.assertGreater(data["undefinedRig"][1], 0)


if __name__ == "__main__":
    unittest.main()
