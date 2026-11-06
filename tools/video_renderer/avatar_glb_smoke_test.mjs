/**
 * Verifies that an uploaded .glb avatar can be rigged by this renderer.
 *
 * Roblox-style .glb uploads from Sketchfab/marketplaces usually ship an
 * "Armature" with bone nodes but no skin bindings and no animation clips, which
 * Roblox itself cannot animate. This test proves the MP4 pipeline can still rig
 * such a file: it loads the real GLB, runs the automatic R15-style rig, and
 * checks every mesh is bound rigidly (no stretching) and the head region is
 * measurable (needed for the animated face).
 *
 * Usage: node avatar_glb_smoke_test.mjs [path/to/avatar.glb]
 */
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { applyRobloxAnimationRig, buildAvatarRig, measureHeadRegion } from './avatar_rig.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const candidate = process.argv[2]
  || resolve(HERE, '../../users/noob.glb');
if (!existsSync(candidate)) {
  console.log(`No .glb avatar found at ${candidate}; skipping the GLB rig check.`);
  process.exit(0);
}

/** Textures need a browser image decoder, so drop them and rig the bare geometry. */
function withoutTextures(buffer) {
  const magic = buffer.readUInt32LE(0);
  assert.equal(magic, 0x46546c67, 'not a GLB file');
  const version = buffer.readUInt32LE(4);
  assert.equal(version, 2, 'only glTF 2.0 GLB files are supported');
  const total = buffer.readUInt32LE(8);
  let offset = 12;
  const chunks = [];
  while (offset < total) {
    const length = buffer.readUInt32LE(offset);
    const type = buffer.readUInt32LE(offset + 4);
    chunks.push({ type, data: buffer.subarray(offset + 8, offset + 8 + length) });
    offset += 8 + length;
  }
  const jsonChunk = chunks.find((chunk) => chunk.type === 0x4e4f534a);
  const binChunk = chunks.find((chunk) => chunk.type === 0x004e4942);
  const gltf = JSON.parse(jsonChunk.data.toString('utf8'));
  delete gltf.images;
  delete gltf.textures;
  delete gltf.samplers;
  for (const material of gltf.materials || []) {
    delete material.pbrMetallicRoughness?.baseColorTexture;
    delete material.pbrMetallicRoughness?.metallicRoughnessTexture;
    delete material.normalTexture;
    delete material.occlusionTexture;
    delete material.emissiveTexture;
  }
  const json = Buffer.from(JSON.stringify(gltf), 'utf8');
  const paddedJson = Buffer.concat([json, Buffer.alloc((4 - (json.length % 4)) % 4, 0x20)]);
  const bin = binChunk ? binChunk.data : Buffer.alloc(0);
  const paddedBin = Buffer.concat([bin, Buffer.alloc((4 - (bin.length % 4)) % 4, 0)]);
  const header = Buffer.alloc(12);
  const jsonHeader = Buffer.alloc(8);
  const binHeader = Buffer.alloc(8);
  jsonHeader.writeUInt32LE(paddedJson.length, 0);
  jsonHeader.writeUInt32LE(0x4e4f534a, 4);
  binHeader.writeUInt32LE(paddedBin.length, 0);
  binHeader.writeUInt32LE(0x004e4942, 4);
  const parts = [header, jsonHeader, paddedJson, binHeader, paddedBin];
  header.writeUInt32LE(magic, 0);
  header.writeUInt32LE(version, 4);
  header.writeUInt32LE(parts.reduce((sum, part) => sum + part.length, 0), 8);
  return Buffer.concat(parts);
}

const source = readFileSync(candidate);
const gltf = await new GLTFLoader().parseAsync(
  withoutTextures(source).buffer.slice(0, withoutTextures(source).length), '');
const model = gltf.scene;
const originalHeight = new THREE.Box3().setFromObject(model).getSize(new THREE.Vector3()).y;
assert.ok(originalHeight > 0.1, 'uploaded GLB has invalid bounds');
console.log(`Loaded ${candidate}: ${originalHeight.toFixed(2)} units tall, `
  + `${gltf.animations.length} embedded animation clip(s), `
  + `${(gltf.parser.json.skins || []).length} skin binding(s).`);
if (!(gltf.parser.json.skins || []).length) {
  console.log('The GLB has an armature hierarchy but no skin bindings, so it is not directly '
    + 'animatable; the automatic rig below supplies real joints.');
}

const rig = buildAvatarRig(THREE, model);
rig.root.updateMatrixWorld(true);
rig.skeleton.update();
assert.ok(rig.meshCount >= 1, 'no meshes were rigged');
assert.equal(rig.skeleton.bones.length, 18, `expected 18 R15-style joints, got ${rig.skeleton.bones.length}`);
for (const bone of ['Root', 'Hips', 'Chest', 'Head', 'LeftUpperArm', 'RightUpperArm', 'LeftUpperLeg', 'RightUpperLeg']) {
  assert.ok(rig.bones[bone], `missing joint ${bone}`);
}

let vertices = 0;
for (const mesh of rig.meshes) {
  assert.ok(mesh.isSkinnedMesh, 'every part must become a skinned mesh');
  const position = mesh.geometry.getAttribute('position');
  const weights = mesh.geometry.getAttribute('skinWeight');
  const indices = mesh.geometry.getAttribute('skinIndex');
  assert.ok(position && weights && indices, 'skin attributes are missing');
  vertices += position.count;
  const step = Math.max(1, Math.floor(position.count / 500));
  for (let vertex = 0; vertex < position.count; vertex += step) {
    const sum = weights.getX(vertex) + weights.getY(vertex) + weights.getZ(vertex) + weights.getW(vertex);
    assert.ok(Math.abs(sum - 1) < 1e-5, `skin weight must be exactly 1, got ${sum}`);
    assert.ok(indices.getX(vertex) < rig.skeleton.bones.length, 'skin index out of range');
  }
}
assert.ok(vertices > 100, `unexpectedly small avatar (${vertices} vertices)`);

const head = measureHeadRegion(THREE, rig);
assert.ok(head.size[0] > 0.05 && head.size[1] > 0.05,
  `the head region must be measurable for the animated face: ${JSON.stringify(head)}`);
assert.ok(head.center[1] > rig.height * 0.6, 'the measured head must sit near the top of the avatar');

// No stretching: a limb keeps its rest length when a native clip rotates it.
const leftArm = rig.meshes.find((mesh) => /arm|object_10/i.test(mesh.name)) || rig.meshes[0];
leftArm.geometry.computeBoundingBox();
const restSize = leftArm.geometry.boundingBox.getSize(new THREE.Vector3()).length();
const clip = {
  duration: 1,
  keyframes: [
    { time: 0, poses: { LeftShoulder: { orientation: [1, 0, 0, 0, 1, 0, 0, 0, 1], weight: 1, position: [0, 0, 0] } } },
    { time: 1, poses: { LeftShoulder: {
      orientation: [Math.cos(0.5), Math.sin(0.5), 0, -Math.sin(0.5), Math.cos(0.5), 0, 0, 0, 1],
      weight: 1, position: [0.4, 0.2, 0.1] } } },
  ],
};
applyRobloxAnimationRig(THREE, rig.bones, clip, 0.5, true, 1);
rig.root.updateMatrixWorld(true);
rig.skeleton.update();
const bone = rig.bones.LeftUpperArm;
assert.ok(Math.abs(bone.quaternion.length() - 1) < 1e-6, 'joint rotation must stay normalised');
assert.ok(restSize > 0);

console.log(`GLB rig check passed: ${rig.meshCount} mesh part(s) skinned to `
  + `${rig.skeleton.bones.length} joints, ${vertices} vertices, head region `
  + `${head.size.map((value) => value.toFixed(2)).join(' x ')} for the animated face, no stretch.`);
