import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import * as THREE from 'three';
import { OBJLoader } from 'three/addons/loaders/OBJLoader.js';
import { animateAvatarRig, applyRobloxAnimationRig, buildAvatarRig } from './avatar_rig.mjs';

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

const identity=[1,0,0,0,1,0,0,0,1];
const keyframedTurn=[1,0,0,0,0,-1,0,1,0];
const nativeFixture={duration:1,keyframes:[
  {time:0,poses:{LeftUpperArm:{orientation:identity,position:[0,0,0],weight:1}}},
  {time:1,poses:{LeftUpperArm:{orientation:keyframedTurn,position:[0,0,0],weight:1}}},
]};
const applied=applyRobloxAnimationRig(THREE,rig.bones,nativeFixture,.5,false);
assert.equal(applied,1,'the Roblox pose channel should retarget to the generated arm bone');
assert.ok(Math.abs(rig.bones.LeftUpperArm.rotation.x-Math.PI/4)<1e-4,'native keyframe rotations should interpolate on the matching joint');
console.log(`Uploaded OBJ auto-rig and native-keyframe smoke tests passed: ${rig.meshCount} groups, ${rig.skeleton.bones.length} joints; procedural vertex ${movingVertex.mesh}, Roblox-style pose interpolation.`);
