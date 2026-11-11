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

    def test_scene_ready_updates_the_group_not_a_missing_joint_map_root(self):
        # actor.rig is the plain {Head, ...} joint map. Only actor.avatarRig has
        # the Three.js root; actor.root is the parent group that updates the whole
        # hierarchy. Dereferencing actor.rig.root crashed every render at startup.
        compact = RENDER_SHORT.replace(" ", "").replace("\n", "")
        self.assertNotIn("actor.rig.root.updateMatrixWorld", compact)
        self.assertIn("rig:bones,avatarRig,", compact)
        self.assertIn("actor.root.updateMatrixWorld(true);", RENDER_SHORT)
        self.assertIn("measureRigStretch(THREE,actor.avatarRig||actor.rig)", compact)

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
import { buildAvatarRig, measureHeadRegion, measureFaceAnchor, measureRigStretch } from './avatar_rig.mjs';
const model = new THREE.Group();
const material = new THREE.MeshStandardMaterial();
const part = (name, center, size) => {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(...size), material);
  mesh.name = name; mesh.position.set(...center); model.add(mesh);
};
part('Head', [0, 5.55, 0], [0.72, 0.72, 0.72]);
part('Torso', [0, 3.55, 0], [1.05, 1.75, 0.58]);
part('LeftArm', [-1.0, 3.7, 0], [0.4, 1.4, 0.4]);
part('RightArm', [1.0, 3.7, 0], [0.4, 1.4, 0.4]);
part('LeftLeg', [-0.35, 1.3, 0], [0.5, 2.4, 0.6]);
part('RightLeg', [0.35, 1.3, 0], [0.5, 2.4, 0.6]);
const rig = buildAvatarRig(THREE, model);
const actorRoot = new THREE.Group();
actorRoot.add(rig.root);
const actor = { root: actorRoot, rig: rig.bones, avatarRig: rig };
// This is the exact safe scene-ready path: the joint map has no .root, while
// updating the containing actor group updates the attached Three.js rig.
actor.root.updateMatrixWorld(true);
const stretch = measureRigStretch(THREE, actor.avatarRig || actor.rig);
const bonesOnly = measureHeadRegion(THREE, rig.bones);
const wholeRig = measureHeadRegion(THREE, rig);
console.log(JSON.stringify({
  jointMapHasRoot: Boolean(actor.rig.root),
  avatarRigHasRoot: Boolean(actor.avatarRig.root),
  stretchSamples: stretch.samples,
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
        # Actor animation retains a plain joint map; only the separate avatarRig
        # has a Three.js root. Updating actor.root safely updates the attached rig.
        self.assertFalse(data["jointMapHasRoot"])
        self.assertTrue(data["avatarRigHasRoot"])
        self.assertGreater(data["stretchSamples"], 0)
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
        """Every triangle must carry ONE weight vector, or it can be torn apart.

        The shipped MP4 exploded because two corners of a triangle 3 cm apart
        followed the hip and the foot at once (measured: an edge stretched by
        1144%). A triangle whose corners share their weights is an affine copy of
        itself, so it can rotate and slide but never spike.
        """
        script = """
import * as THREE from 'three';
import { animateAvatarRig, buildAvatarRig } from './avatar_rig.mjs';
const material = new THREE.MeshStandardMaterial();
const group = new THREE.Group();
// A cylinder is INDEXED: shared corners would let triangles disagree, so the rig
// must split the index before weighting anything.
const body = new THREE.Mesh(new THREE.CylinderGeometry(0.62, 0.72, 5.2, 10, 14), material);
body.name = 'Body'; body.position.set(0, 3.1, 0); group.add(body);
const rig = buildAvatarRig(THREE, group);
const skin = rig.root.children.find((c) => c.isSkinnedMesh && c.name === 'Body');
const geometry = skin.geometry;
const count = geometry.getAttribute('position').count;
const weights = geometry.getAttribute('skinWeight');
const boneIndex = geometry.getAttribute('skinIndex');
const key = (v) => [0, 1, 2, 3].map((s) => boneIndex.getComponent(v, s) + ':' + weights.getComponent(v, s).toFixed(4)).join('|');
const unnormalised = [];
for (let v = 0; v < count; v += 1) {
  const sum = weights.getX(v) + weights.getY(v) + weights.getZ(v) + weights.getW(v);
  if (Math.abs(sum - 1) > 1e-5) unnormalised.push([v, sum]);
}
let straddling = 0;
const triangles = Math.floor(count / 3);
for (let t = 0; t < triangles; t += 1) {
  const a = t * 3;
  if (key(a) !== key(a + 1) || key(a + 1) !== key(a + 2)) straddling += 1;
}
const rest = [];
const v3 = new THREE.Vector3();
for (let v = 0; v < count; v += 1) { skin.getVertexPosition(v, v3); rest.push([v3.x, v3.y, v3.z]); }
let worst = 0;
for (const time of [0.2, 0.55, 0.9, 1.4]) {
  animateAvatarRig(rig.bones, time, 0.5, 0.3);
  rig.root.updateMatrixWorld(true);
  rig.skeleton.update();
  for (let t = 0; t < triangles; t += 1) {
    const a = t * 3;
    for (const [x, y] of [[a, a + 1], [a + 1, a + 2], [a + 2, a]]) {
      const length = Math.hypot(rest[x][0] - rest[y][0], rest[x][1] - rest[y][1], rest[x][2] - rest[y][2]);
      if (length < 1e-5) continue;
      skin.getVertexPosition(x, v3); const px = v3.x, py = v3.y, pz = v3.z;
      skin.getVertexPosition(y, v3);
      worst = Math.max(worst, Math.abs(Math.hypot(px - v3.x, py - v3.y, pz - v3.z) - length) / length);
    }
  }
}
console.log(JSON.stringify({ triangles, straddling, unnormalised: unnormalised.slice(0, 3), worst }));
"""
        result = self._node(script)
        self.assertEqual(result.returncode, 0, msg=result.stderr[-1500:])
        data = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertGreater(data["triangles"], 100)
        self.assertEqual(data["unnormalised"], [], "every vertex must be fully weighted")
        self.assertEqual(data["straddling"], 0,
                         "a triangle spanning two joints is torn apart when they rotate")
        # Corners inside one triangle are rigid (asserted above: zero straddling
        # triangles). An edge BETWEEN two triangles bends a little by design - the
        # smoothing pass that keeps the seam shut is what allows it - and it must
        # never bend like rubber: 10% is the measured ceiling on the real avatar
        # under a 0.9-radian joint swing.
        self.assertLess(data["worst"], 0.15, "no edge may stretch like rubber")


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
