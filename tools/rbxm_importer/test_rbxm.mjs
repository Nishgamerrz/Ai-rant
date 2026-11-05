import assert from 'node:assert/strict';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const directory = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const Module = require('node:module');
const lz4js = require('lz4js');
const originalLoad = Module._load;
Module._load = function load(request, parent, isMain) {
  if (request === 'lz4') {
    return {
      decodeBlock(source, destination) {
        return lz4js.decompressBlock(
          new Uint8Array(source.buffer, source.byteOffset, source.byteLength),
          new Uint8Array(destination.buffer, destination.byteOffset, destination.byteLength),
          0, source.byteLength, 0,
        );
      },
      encodeBound() { throw new Error('not used in parser smoke test'); },
      encodeBlock() { throw new Error('not used in parser smoke test'); },
    };
  }
  return originalLoad.call(this, request, parent, isMain);
};
const { RobloxFile } = require('rbxm-parser');
const modelPath = path.resolve(directory, '../../users/normal.rbxm');
const model = RobloxFile.ReadFromBuffer(fs.readFileSync(modelPath));
assert.ok(model, 'expected users/normal.rbxm to parse');
assert.equal(model.Roots.length, 1);
assert.equal(model.Roots[0].ClassName, 'Model');
assert.ok(model.Roots[0].Name);

const instances = [];
function visit(instance) {
  instances.push(instance);
  for (const child of instance.Children ?? []) visit(child);
}
for (const root of model.Roots) visit(root);
assert.ok(instances.some((instance) => instance.ClassName === 'Humanoid'), 'RBXM needs a Humanoid');
assert.ok(instances.some((instance) => instance.ClassName === 'LocalScript' && instance.Name === 'Animate'), 'RBXM should retain its Roblox Animate script');
const bodyParts = instances.filter((instance) => instance.ClassName === 'MeshPart');
assert.ok(bodyParts.length >= 6, `expected a rigged body, got ${bodyParts.length} MeshParts`);
assert.ok(bodyParts.some((instance) => instance.Name === 'Head'));
assert.ok(bodyParts.some((instance) => instance.Name === 'UpperTorso'));
assert.ok(bodyParts.some((instance) => instance.Name === 'LeftUpperArm'));
assert.ok(bodyParts.every((instance) => typeof instance.MeshId === 'string' && instance.MeshId.length > 0));
const animationCount = instances.filter((instance) => instance.ClassName === 'Animation' && instance.AnimationId).length;
assert.ok(animationCount > 0, 'expected native animation references in the RBXM');
console.log(`RBXM smoke test passed: ${bodyParts.length} MeshParts, Humanoid, Animate script, ${animationCount} animation refs.`);
