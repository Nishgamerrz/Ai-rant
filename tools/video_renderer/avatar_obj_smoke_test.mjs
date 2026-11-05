import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import * as THREE from 'three';
import { OBJLoader } from 'three/addons/loaders/OBJLoader.js';
import { animateAvatarRig, buildAvatarRig } from './avatar_rig.mjs';

const source = new URL('../../users/normal.obj', import.meta.url);
const model = new OBJLoader().parse(readFileSync(source, 'utf8'));
const bounds = new THREE.Box3().setFromObject(model);
assert.ok(bounds.getSize(new THREE.Vector3()).y > 5, 'uploaded Roblox OBJ should contain a full-height avatar mesh');

const rig = buildAvatarRig(THREE, model);
assert.ok(rig.meshCount >= 10, `expected multiple imported avatar body/accessory groups, got ${rig.meshCount}`);
assert.ok(rig.bones.LeftUpperArm && rig.bones.RightUpperArm);
assert.ok(rig.bones.LeftUpperLeg && rig.bones.RightUpperLeg);
rig.root.updateMatrixWorld(true);
rig.skeleton.update();

let movingVertex = null;
for (const mesh of rig.root.children.filter((child) => child.isSkinnedMesh)) {
  const count = mesh.geometry.getAttribute('position').count;
  for (let vertex = 0; vertex < count; vertex += Math.max(1, Math.floor(count / 64))) {
    const before = mesh.getVertexPosition(vertex, new THREE.Vector3()).clone();
    animateAvatarRig(rig.bones, 0.7, 0.3, 0.25);
    rig.root.updateMatrixWorld(true);
    rig.skeleton.update();
    const after = mesh.getVertexPosition(vertex, new THREE.Vector3());
    if (before.distanceTo(after) > 0.005) {
      movingVertex = { mesh: mesh.name, distance: before.distanceTo(after) };
      break;
    }
    animateAvatarRig(rig.bones, 0, 0, 0);
  }
  if (movingVertex) break;
}
assert.ok(movingVertex, 'at least one real avatar mesh vertex should move under the generated limb rig');
console.log(`Uploaded OBJ auto-rig smoke test passed: ${rig.meshCount} imported groups, ${rig.skeleton.bones.length} procedural joints; moving mesh ${movingVertex.mesh}.`);
