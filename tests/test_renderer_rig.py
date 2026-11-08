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


class MeshTearTests(unittest.TestCase):
    """The avatar must never explode, which is what the first real MP4 shipped.

    Frames at 28 s and 88 s showed the torso bursting into flat yellow and blue
    spikes. The cause was per-vertex bone picking: one triangle's three vertices
    followed three different joints, so the triangle was torn in three directions.
    These checks fail on that bug and pass on rigid, one-bone-per-piece skinning.
    """

    @staticmethod
    def _node(script):
        return subprocess.run(["node", "--input-type=module", "-e", script], cwd=RENDERER,
                              capture_output=True, text=True, timeout=300)

    def test_skinning_keeps_every_triangle_rigid(self):
        script = """
import * as THREE from 'three';
import { animateAvatarRig, buildAvatarRig } from './avatar_rig.mjs';
const material = new THREE.MeshStandardMaterial();
const group = new THREE.Group();
const body = new THREE.Mesh(new THREE.CylinderGeometry(0.62, 0.72, 5.2, 10, 14), material);
body.name = 'Body'; body.position.set(0, 3.1, 0); group.add(body);
const rig = buildAvatarRig(THREE, group);
const skin = rig.root.children.find((c) => c.isSkinnedMesh && c.name === 'Body');
const index = skin.geometry.getIndex();
const bones = skin.geometry.getAttribute('skinIndex');
const tris = [];
for (let i = 0; i < index.count; i += 3) tris.push([index.getX(i), index.getX(i + 1), index.getX(i + 2)]);
const straddling = tris.filter((t) => new Set(t.map((v) => bones.getX(v))).size > 1).length;
const rest = new Map();
for (const t of tris) for (const v of t) rest.set(v, skin.getVertexPosition(v, new THREE.Vector3()).clone());
let worst = 0;
for (const time of [0.2, 0.55, 0.9, 1.4]) {
  animateAvatarRig(rig.bones, time, 0.5, 0.3);
  rig.root.updateMatrixWorld(true);
  rig.skeleton.update();
  for (const t of tris) for (const [a, b] of [[t[0], t[1]], [t[1], t[2]], [t[2], t[0]]]) {
    const now = skin.getVertexPosition(a, new THREE.Vector3()).distanceTo(skin.getVertexPosition(b, new THREE.Vector3()));
    worst = Math.max(worst, Math.abs(now - rest.get(a).distanceTo(rest.get(b))));
  }
}
console.log(JSON.stringify({ triangles: tris.length, straddling, worst }));
"""
        result = self._node(script)
        self.assertEqual(result.returncode, 0, msg=result.stderr[-1500:])
        data = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertGreater(data["triangles"], 100)
        self.assertEqual(data["straddling"], 0,
                         "a triangle spanning two joints is torn apart when they rotate")
        self.assertLess(data["worst"], 1e-4, "animated mesh edges must keep their length")


class CameraFramingTests(unittest.TestCase):
    """No weird cameras: the shipped MP4 must not look up at its own subject."""

    def test_camera_never_sits_below_its_target(self):
        script = """
import { chooseSafeCamera } from './scene_camera.mjs';
const target = [0, 3.05, 24];
const low = chooseSafeCamera(target, [0, 0.1, 40], [], 14, 36);
const porch = [{ position: [0, 9, 30], size: [26, 2, 22] }, { position: [10, 4, 30], size: [2, 10, 2] }];
const under = chooseSafeCamera(target, [0, 4, 36], porch, 14, 36);
console.log(JSON.stringify({ low, under }));
"""
        result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=RENDERER,
                                capture_output=True, text=True, timeout=300)
        self.assertEqual(result.returncode, 0, msg=result.stderr[-1500:])
        data = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertGreater(data["low"][1] - 3.05, 0.9, "the camera must look down, not up")
        under = data["under"]
        inside_roof = abs(under[0]) <= 13 + 0.6 and abs(under[2] - 30) <= 11 + 0.6 and under[1] < 8
        self.assertFalse(inside_roof, "the camera must not be placed underneath a roof slab")


if __name__ == "__main__":
    unittest.main()
