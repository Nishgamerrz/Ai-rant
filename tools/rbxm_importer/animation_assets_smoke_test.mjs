import assert from 'node:assert/strict';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const Module = require('node:module');
const lz4js = require('lz4js');
const originalLoad = Module._load;
Module._load = function load(request, parent, isMain) {
  if (request === 'lz4') return {
    decodeBlock(source, destination) {
      return lz4js.decompressBlock(
        new Uint8Array(source.buffer, source.byteOffset, source.byteLength),
        new Uint8Array(destination.buffer, destination.byteOffset, destination.byteLength),
        0, source.byteLength, 0,
      );
    },
    encodeBound() { throw new Error('not used in animation smoke test'); },
    encodeBlock() { throw new Error('not used in animation smoke test'); },
  };
  return originalLoad.call(this, request, parent, isMain);
};
const { RobloxFile } = require('rbxm-parser');
const sourcePath = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../users/normal.rbxm');
const source = RobloxFile.ReadFromBuffer(fs.readFileSync(sourcePath));
const instances = [];
function visit(instance) {
  instances.push(instance);
  for (const child of instance.Children ?? []) visit(child);
}
for (const root of source.Roots ?? []) visit(root);
const walkAnimation = instances.find((instance) => instance.ClassName === 'Animation'
  && /(?:[?&]id=|rbxassetid:\/\/)(\d{1,20})/i.test(instance.AnimationId || '')
  && String(instance.Parent?.Name || '').toLowerCase() === 'walk');
assert.ok(walkAnimation, 'normal.rbxm must have a native walk AnimationId');
const id = String(walkAnimation.AnimationId).match(/(?:[?&]id=|rbxassetid:\/\/)(\d{1,20})/i)[1];
const response = await fetch(`https://assetdelivery.roblox.com/v1/asset/?id=${id}`, {
  headers: { Accept: '*/*', 'User-Agent': 'Ai-rant-Roblox-animation-renderer/1.0' },
  signal: AbortSignal.timeout(45000),
});
assert.ok(response.ok, `Roblox did not allow keyless access to walk animation ${id}: HTTP ${response.status}`);
const bytes = Buffer.from(await response.arrayBuffer());
assert.ok(bytes.length > 0 && bytes.length < 64 * 1024 * 1024, 'walk animation response has an invalid size');
const sequence = RobloxFile.ReadFromBuffer(bytes);
assert.ok(sequence?.Roots?.length, `walk animation ${id} is not a readable Roblox keyframe file`);
const animationInstances = [];
for (const root of sequence.Roots) visitAnimation(root, animationInstances);
function visitAnimation(instance, output) {
  output.push(instance);
  for (const child of instance.Children ?? []) visitAnimation(child, output);
}
const keyframes = animationInstances.filter((instance) => instance.ClassName === 'Keyframe');
assert.ok(keyframes.length > 1, `walk animation ${id} contains no usable keyframe sequence`);
const poses = animationInstances.filter((instance) => instance.ClassName === 'Pose');
const poseCount = poses.length;
const transformCount = poses.filter((pose) => Array.isArray(pose.CFrame?.Orientation)
  && pose.CFrame.Orientation.length === 9).length;
assert.ok(poseCount > 0, `walk animation ${id} contains no Pose channels`);
assert.ok(transformCount > 0, `walk animation ${id} contains no readable Pose CFrames`);
console.log(`Keyless Roblox animation fetch passed: walk asset ${id}, ${keyframes.length} keyframes, ${poseCount} Pose nodes, ${transformCount} transforms.`);
