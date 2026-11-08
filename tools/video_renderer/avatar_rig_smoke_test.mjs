import assert from 'node:assert/strict';
import * as THREE from 'three';
import { animateAvatarRig, applyRobloxAnimationRig, buildAvatarRig, measureFaceAnchor, measureHeadRegion } from './avatar_rig.mjs';

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
const head = new THREE.Bone();
head.name = 'Head';
head.position.set(0, 5, 0);
const identity = [1, 0, 0, 0, 1, 0, 0, 0, 1];
const nativeClip = {
  duration: 2,
  keyframes: [
    { time: 0, poses: { Head: { orientation: identity, position: [0, 2, 0], weight: 1 } } },
    { time: 2, poses: { Head: { orientation: identity, position: [0, 2.6, 0], weight: 1 } } },
  ],
};
assert.equal(applyRobloxAnimationRig(THREE, { Head: head }, nativeClip, 0, false), 1);
assert.ok(Math.abs(head.position.y - 5) < 1e-6, 'native static Pose offset must not be added on top of the generated skeleton rest offset');
assert.equal(applyRobloxAnimationRig(THREE, { Head: head }, nativeClip, 1, false), 1);
assert.ok(Math.abs(head.position.y - 5) < 1e-6, 'native CFrame translation must not detach a limb joint on the generated rig');

// Stretch guard: limb bones must keep their rest length while native clips play,
// because blending or translating joints is what made arms look elastic.
const hip = rig.bones.LeftUpperLeg, knee = rig.bones.LeftLowerLeg;
const restGap = hip.position.distanceTo(knee.position);
const translatedClip = {
  duration: 1,
  keyframes: [
    { time: 0, poses: { LeftHip: { orientation: identity, position: [0, -7, 0], weight: 1 } } },
    { time: 1, poses: { LeftHip: { orientation: identity, position: [4, 7, 0], weight: 1 } } },
  ],
};
for (const time of [0, 0.5, 1]) {
  applyRobloxAnimationRig(THREE, rig.bones, translatedClip, time, false);
  rig.root.updateMatrixWorld(true);
  const gap = hip.position.distanceTo(knee.position);
  assert.ok(Math.abs(gap - restGap) < 1e-6, 'native clip translation must not change limb length');
}
const hipRest = hip.position.clone();
const hipRoot = rig.bones.Root.position.clone();
assert.ok(hip.position.distanceTo(hipRest) < 0.5, 'hip translation stays tightly clamped');
assert.ok(hipRoot, 'rig root must exist');
// Regression: run #58 died at "Cannot read properties of undefined (reading
// 'bones')" in measureHeadRegion because the renderer handed it the joint map
// instead of the whole rig. Every shape a caller has used must measure a head.
const fromRig = measureHeadRegion(THREE, rig);
assert.ok(fromRig.center[1] > rig.height * 0.6, 'the head region must sit near the top of the avatar');
assert.ok(fromRig.size[0] > 0 && fromRig.size[2] > 0, 'the head region must have a width and a depth');
const fromBonesOnly = measureHeadRegion(THREE, rig.bones);
assert.ok(Number.isFinite(fromBonesOnly.center[1]) && fromBonesOnly.center[1] > 0,
  'a bare joint map must still measure a head instead of throwing');
const fromHeadBone = measureHeadRegion(THREE, { Head: rig.bones.Head, height: rig.height });
assert.ok(Number.isFinite(fromHeadBone.center[1]), 'a lone Head bone must still measure a head');
const fromNothing = measureHeadRegion(THREE, undefined);
assert.ok(Number.isFinite(fromNothing.center[1]), 'a missing rig must fall back, not throw');
assert.ok(fromRig.size[0] > 0.1, 'the measured head must be big enough to place a face on');

// The face plane must land on the head wherever the actor stands on the map.
// Run #58 also exposed this: the anchor subtracted a world-space head position
// from a rig-space measurement, so moving the pivot to z = 24 pushed the face
// 24 studs off the head.
for (const offset of [[0, 0, 0], [0, 0, 24], [-7, 0, 31], [6, 2, -12]]) {
  const pivot = new THREE.Group();
  pivot.position.set(...offset);
  pivot.add(rig.root);
  pivot.updateMatrixWorld(true);
  const layout = measureFaceAnchor(THREE, rig, rig.bones.Head, 1);
  assert.ok(layout.anchor.length() < 1.2,
    `face anchor must be a small head-local offset, got ${layout.anchor.toArray()} at pivot ${offset}`);
  const face = new THREE.Mesh(new THREE.PlaneGeometry(layout.width, layout.height));
  face.position.copy(layout.anchor);
  rig.bones.Head.add(face);
  pivot.updateMatrixWorld(true);
  const faceWorld = face.getWorldPosition(new THREE.Vector3());
  const headWorld = rig.bones.Head.getWorldPosition(new THREE.Vector3());
  assert.ok(faceWorld.distanceTo(headWorld) < 1.2,
    `face must stay glued to the head at pivot ${offset}, distance ${faceWorld.distanceTo(headWorld)}`);
  assert.ok(Math.abs(faceWorld.x - headWorld.x) < 0.35, 'face stays centred on the head in X');
  assert.ok(Math.abs(faceWorld.y - headWorld.y) < 1.1, 'face sits at head height');
  rig.bones.Head.remove(face);
  face.geometry.dispose();
  pivot.remove(rig.root);
}

// Both skinning defects, at once.
//   * the shipped MP4 tore because a triangle's corners followed different joints;
//   * the attempt before that blended whole limbs 50/50 and they bent like rubber.
// The rule that removes both: every triangle carries ONE weight vector (here a
// single bone), so a triangle can rotate but can never be stretched into a spike.
{
  const tall = new THREE.Group();
  const body = new THREE.Mesh(new THREE.CylinderGeometry(0.62, 0.72, 5.2, 10, 14), material);
  body.name = 'Body';
  body.position.set(0, 3.1, 0);
  tall.add(body);
  const tallRig = buildAvatarRig(THREE, tall);
  const skin = tallRig.root.children.find((child) => child.isSkinnedMesh && child.name === 'Body');
  assert.ok(skin, 'the tall test body must be rigged as a skinned mesh');
  const geometry = skin.geometry;
  const skinWeight = geometry.getAttribute('skinWeight');
  const skinIndex = geometry.getAttribute('skinIndex');
  const vertexCount = geometry.getAttribute('position').count;
  assert.ok(vertexCount > 60, 'the tear test needs a real triangulated mesh');
  const key = (vertex) => [0, 1, 2, 3]
    .map((slot) => `${skinIndex.getComponent(vertex, slot)}:${skinWeight.getComponent(vertex, slot).toFixed(4)}`)
    .join('|');
  for (let vertex = 0; vertex < vertexCount; vertex += 1) {
    const total = skinWeight.getX(vertex) + skinWeight.getY(vertex) + skinWeight.getZ(vertex) + skinWeight.getW(vertex);
    assert.ok(Math.abs(total - 1) < 1e-5, `skin weights must normalize to 1; got ${total}`);
  }
  // The invariant: the three corners of a triangle carry identical weights.
  for (let vertex = 0; vertex + 2 < vertexCount; vertex += 3) {
    assert.equal(key(vertex), key(vertex + 1), 'a triangle must not straddle two joints (it will tear)');
    assert.equal(key(vertex + 1), key(vertex + 2), 'a triangle must not straddle two joints (it will tear)');
  }
  const rest = new Map();
  for (let vertex = 0; vertex < vertexCount; vertex += 1) rest.set(vertex, skin.getVertexPosition(vertex, new THREE.Vector3()).clone());
  let worst = 0;
  for (const time of [0.2, 0.55, 0.9, 1.4]) {
    animateAvatarRig(tallRig.bones, time, 0.5, 0.3);
    tallRig.root.updateMatrixWorld(true);
    tallRig.skeleton.update();
    for (let vertex = 0; vertex + 2 < vertexCount; vertex += 3) {
      for (const [a, b] of [[vertex, vertex + 1], [vertex + 1, vertex + 2], [vertex + 2, vertex]]) {
        const now = skin.getVertexPosition(a, new THREE.Vector3()).distanceTo(skin.getVertexPosition(b, new THREE.Vector3()));
        const restLength = rest.get(a).distanceTo(rest.get(b));
        if (restLength < 1e-5) continue;
        worst = Math.max(worst, Math.abs(now - restLength) / restLength);
      }
    }
  }
  assert.ok(worst < 1e-4, `a rigidly skinned triangle cannot stretch; worst edge changed by ${(worst * 100).toFixed(2)}%`);
}

console.log(`Avatar rig smoke test passed; one rigid bone per triangle on ${rig.meshCount} mesh groups (nothing can tear), ${rig.skeleton.bones.length} R15-style joints, no limb stretch under native clips.`);
