import assert from 'node:assert/strict';
import * as THREE from 'three';
import { animateAvatarRig, buildAvatarRig } from './avatar_rig.mjs';

const model = new THREE.Group();
const material = new THREE.MeshStandardMaterial({ color: 0x78a8d8 });
function part(name, center, size) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(...size), material);
  mesh.name = name;
  mesh.position.set(...center);
  model.add(mesh);
}
part('Torso', [0, 3.55, 0], [1.05, 1.75, 0.58]);
part('Head', [0, 5.55, 0], [0.72, 0.72, 0.72]);
part('LeftArm', [-0.9, 3.72, 0], [0.34, 1.48, 0.34]);
part('RightArm', [0.9, 3.72, 0], [0.34, 1.48, 0.34]);
part('LeftLeg', [-0.3, 1.32, 0], [0.44, 2.4, 0.48]);
part('RightLeg', [0.3, 1.32, 0], [0.44, 2.4, 0.48]);

const rig = buildAvatarRig(THREE, model);
assert.equal(rig.meshCount, 6);
assert.ok(rig.bones.LeftUpperArm && rig.bones.RightUpperArm);
assert.ok(rig.bones.LeftUpperLeg && rig.bones.RightUpperLeg);
rig.root.updateMatrixWorld(true);
rig.skeleton.update();

const leftArm = rig.root.children.find((child) => child.isSkinnedMesh && child.name === 'LeftArm');
assert.ok(leftArm, 'the real left-arm mesh should be retained as a skinned mesh');
const position = leftArm.geometry.getAttribute('position');
const skinWeight = leftArm.geometry.getAttribute('skinWeight');
for (let vertex = 0; vertex < position.count; vertex += 1) {
  const sum = skinWeight.getX(vertex) + skinWeight.getY(vertex) + skinWeight.getZ(vertex) + skinWeight.getW(vertex);
  assert.ok(Math.abs(sum - 1) < 1e-5, `skin weights must normalize to 1; got ${sum}`);
}

const before = leftArm.getVertexPosition(0, new THREE.Vector3()).clone();
animateAvatarRig(rig.bones, 0.7, 0.3, 0.25);
rig.root.updateMatrixWorld(true);
rig.skeleton.update();
const after = leftArm.getVertexPosition(0, new THREE.Vector3());
assert.ok(before.distanceTo(after) > 0.01, 'the auto-rigged real mesh vertex should move with the limb animation');
assert.notEqual(rig.bones.LeftUpperArm.rotation.x, 0);
assert.notEqual(rig.bones.RightUpperLeg.rotation.x, 0);
console.log(`Avatar rig smoke test passed; automatically skinned ${rig.meshCount} mesh groups to ${rig.skeleton.bones.length} procedural R15-style joints.`);
