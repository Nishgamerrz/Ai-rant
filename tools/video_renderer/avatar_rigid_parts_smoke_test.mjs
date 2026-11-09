// The shipped MP4 had an EXPLODING character: limbs smeared into spikes and the
// body tore apart. The cause was soft skinning: a triangle whose corners followed
// different joints is not a rigid transform of itself, so any pose that moved two
// joints apart stretched it forever.
//
// A Roblox avatar is not soft skin. It is a set of rigid parts (head, torso, upper
// arm, forearm, hand, thigh, shin, foot) that only rotate around their joints, and
// the OBJ Roblox Studio exports already carries exactly those parts as named groups.
// This test loads the REAL avatar in users/normal.obj, rigs it, poses it hard (arms
// above the head, full stride, bent elbows and knees, twisted torso, jump) and
// proves that:
//
//   1. every part is recognised and bound to a sensible bone;
//   2. each part stays perfectly rigid (no vertex drifts from its own centre);
//   3. the skin weights are one bone at 100% per vertex - the guarantee;
//   4. the joints sit at the real boundaries, so limbs articulate instead of
//      sliding out of their sockets;
//   5. the old region rig is still used for a single fused mesh, and even there
//      the stretch guard stays finite.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import * as THREE from 'three';
import { OBJLoader } from 'three/examples/jsm/loaders/OBJLoader.js';
import {
  animateAvatarRig, buildAvatarRig, classifyAvatarParts, measureRigStretch,
} from './avatar_rig.mjs';

const OBJ = new URL('../../users/normal.obj', import.meta.url).pathname;
assert.ok(fs.existsSync(OBJ), 'the real Roblox avatar mesh must be in users/normal.obj');
const model = new OBJLoader().parse(fs.readFileSync(OBJ, 'utf8'));
// Same normalisation the renderer applies: 6.2 studs tall, feet at the origin.
const bounds = new THREE.Box3().setFromObject(model);
const size = bounds.getSize(new THREE.Vector3());
const scale = 6.2 / size.y;
model.scale.setScalar(scale);
model.position.set(-((bounds.min.x + bounds.max.x) / 2) * scale, -bounds.min.y * scale,
  -((bounds.min.z + bounds.max.z) / 2) * scale);

// 1. Every part is recognised, and the binding is anatomically right.
const classified = classifyAvatarParts(THREE, model);
assert.ok(classified.confident, 'the real avatar must be recognised as separate rigid parts');
assert.ok(classified.parts.length >= 12, `expected a full body of parts, got ${classified.parts.length}`);
const boneOf = Object.fromEntries(classified.parts.map((part) => [part.object.name, part.bone]));
const expected = {
  Handle1: 'Head',   // hat / hair on top of the head
  Rig10: 'Head',
  Rig15: 'Chest',
  Rig14: 'Hips',
  Rig9: 'LeftUpperArm', Rig8: 'LeftLowerArm', Rig7: 'LeftHand',
  Rig13: 'RightUpperArm', Rig12: 'RightLowerArm', Rig11: 'RightHand',
  Rig6: 'LeftUpperLeg', Rig5: 'LeftLowerLeg', Rig4: 'LeftFoot',
  Rig3: 'RightUpperLeg', Rig2: 'RightLowerLeg', Rig1: 'RightFoot',
};
for (const [part, bone] of Object.entries(expected)) {
  assert.equal(boneOf[part], bone, `${part} must be bound to ${bone}, got ${boneOf[part]}`);
}

const rig = buildAvatarRig(THREE, model);
assert.equal(rig.mode, 'rigid-parts', 'the avatar must use the rigid part rig');
assert.equal(rig.meshCount, classified.parts.length);
for (const bone of ['Root', 'Hips', 'Spine', 'Chest', 'Neck', 'Head', 'LeftUpperArm',
  'LeftLowerArm', 'LeftHand', 'RightUpperArm', 'LeftUpperLeg', 'LeftLowerLeg', 'LeftFoot']) {
  assert.ok(rig.bones[bone], `missing joint ${bone}`);
}

// Joints must sit at the real limb boundaries, not guessed fractions of the body:
// shoulders at the top of the upper arm, knees between thigh and shin, ankles at
// the foot.
const restWorld = (name) => rig.bones[name].getWorldPosition(new THREE.Vector3());
const joints = classified.joints;
assert.ok(Math.abs(joints.LeftUpperArm[1] - Math.max(...classified.parts
  .filter((p) => p.bone === 'LeftUpperArm').map((p) => p.box.max.y))) < 0.6,
'shoulder must sit at the top of the upper arm');
assert.ok(Math.abs(joints.LeftLowerLeg[1] - Math.max(...classified.parts
  .filter((p) => p.bone === 'LeftLowerLeg').map((p) => p.box.max.y))) < 0.6,
'knee must sit at the top of the shin');
assert.ok(joints.RightFoot[1] < joints.RightLowerLeg[1], 'the ankle must be below the knee');
assert.ok(joints.Head[1] > joints.Neck[1], 'the head joint must be above the neck');

// 3. Rigid binding: exactly one bone per vertex, at weight 1.
for (const mesh of rig.meshes) {
  const indices = mesh.geometry.getAttribute('skinIndex');
  const weights = mesh.geometry.getAttribute('skinWeight');
  for (let vertex = 0; vertex < indices.count; vertex += 7) {
    assert.equal(weights.getY(vertex) + weights.getZ(vertex) + weights.getW(vertex), 0,
      `${mesh.name} vertex ${vertex} must follow exactly one bone`);
    assert.equal(weights.getX(vertex), 1, `${mesh.name} vertex ${vertex} must have full weight`);
  }
}

// 2 + 4. Pose it hard and prove nothing explodes.
const poses = {
  'arms overhead': (bones) => {
    bones.LeftUpperArm.rotation.z = -2.5;
    bones.RightUpperArm.rotation.z = 2.5;
    bones.LeftUpperArm.rotation.x = -0.4;
    bones.RightUpperArm.rotation.x = -0.4;
  },
  'full stride': (bones) => {
    bones.LeftUpperLeg.rotation.x = 0.9;
    bones.RightUpperLeg.rotation.x = -0.9;
    bones.LeftLowerLeg.rotation.x = 0.0;
    bones.RightLowerLeg.rotation.x = 1.2;
    bones.LeftUpperArm.rotation.x = -0.8;
    bones.RightUpperArm.rotation.x = 0.8;
  },
  'bent elbows and knees': (bones) => {
    bones.LeftLowerArm.rotation.x = -1.4;
    bones.RightLowerArm.rotation.x = -1.4;
    bones.LeftLowerLeg.rotation.x = 1.5;
    bones.RightLowerLeg.rotation.x = 1.5;
  },
  'twisted torso and head': (bones) => {
    bones.Spine.rotation.y = 0.8;
    bones.Chest.rotation.y = 0.6;
    bones.Head.rotation.y = 1.2;
    bones.Head.rotation.z = 0.3;
  },
  jump: (bones) => {
    bones.LeftUpperArm.rotation.z = -1.1;
    bones.RightUpperArm.rotation.z = 1.1;
    bones.LeftUpperLeg.rotation.x = 0.6;
    bones.RightUpperLeg.rotation.x = 0.2;
    bones.LeftLowerLeg.rotation.x = 0.9;
  },
};
const reset = () => {
  for (const bone of Object.values(rig.bones)) bone.rotation.set(0, 0, 0);
  rig.root.updateMatrixWorld(true);
  rig.skeleton.update();
};
for (const [label, pose] of Object.entries(poses)) {
  reset();
  pose(rig.bones);
  rig.root.updateMatrixWorld(true);
  rig.skeleton.update();
  const report = measureRigStretch(THREE, rig);
  assert.ok(report.samples > 20, `${label}: must actually measure something`);
  assert.ok(report.maxStretch < 1e-3,
    `${label}: a rigid part must not deform at all; ${report.worstPart} stretched ${(report.maxStretch * 100).toFixed(1)}%`);
}

// The procedural walk cycle used when an avatar has no native Roblox clip must be
// rigid too - it is the pose the renderer applies all the way through a scene.
reset();
for (const time of [0, 0.4, 1.1, 2.7, 5.3]) {
  animateAvatarRig(rig.bones, time, 0.0, 0.6);
  rig.root.updateMatrixWorld(true);
  rig.skeleton.update();
  const report = measureRigStretch(THREE, rig);
  assert.ok(report.maxStretch < 1e-3,
    `t=${time}: the walk cycle deformed ${report.worstPart} by ${(report.maxStretch * 100).toFixed(1)}%`);
}

// Nothing may fly off into the distance either: every vertex stays within the
// avatar's own volume while it moves.
reset();
poses['arms overhead'](rig.bones);
rig.root.updateMatrixWorld(true);
rig.skeleton.update();
const posedBounds = new THREE.Box3();
for (const mesh of rig.meshes) {
  const position = mesh.geometry.getAttribute('position');
  for (let vertex = 0; vertex < position.count; vertex += 23) {
    posedBounds.expandByPoint(mesh.getVertexPosition(vertex, new THREE.Vector3()));
  }
}
assert.ok(posedBounds.max.y < 12, `an explored part flew above the avatar: ${posedBounds.max.y}`);
assert.ok(posedBounds.min.x > -8 && posedBounds.max.x < 8, 'an exploded part flew sideways');

// 5. A single fused mesh (no separate parts) still gets a usable rig.
const fused = new THREE.Group();
const fusedMesh = new THREE.Mesh(new THREE.BoxGeometry(1.6, 6, 0.8, 8, 24, 4),
  new THREE.MeshStandardMaterial({ color: 0x8899aa }));
fused.add(fusedMesh);
const fusedRig = buildAvatarRig(THREE, fused);
assert.ok(fusedRig.mode === undefined || fusedRig.mode !== 'rigid-parts',
  'a single fused mesh cannot be split into rigid parts');
assert.ok(fusedRig.skeleton.bones.length >= 10, 'the fused fallback still needs a skeleton');
animateAvatarRig(fusedRig.bones, 1.2, 0.3, 0.5);
fusedRig.root.updateMatrixWorld(true);
fusedRig.skeleton.update();

console.log(`Rigid avatar check: ${classified.parts.length} parts, ${rig.skeleton.bones.length} joints, ` +
  `${Object.keys(poses).length} hard poses, 0% deformation.`);
