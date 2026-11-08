import assert from 'node:assert/strict';
import { chooseSafeCamera, segmentHitsBox } from './scene_camera.mjs';

const target = [0, 4, 0];
const desired = [0, 7, 24];
const wall = { position: [0, 5, 12], size: [12, 12, 4] };
const safe = chooseSafeCamera(target, desired, [wall], 14, 36);
assert.ok(!segmentHitsBox(target, safe, wall), 'camera view must not pass through the oversized wall');
assert.ok(Math.hypot(safe[0] - target[0], safe[1] - target[1], safe[2] - target[2]) >= 14);

const open = chooseSafeCamera(target, desired, [], 14, 36);
assert.ok(Math.abs(open[0] - desired[0]) < 1e-6);
assert.ok(Math.abs(open[1] - desired[1]) < 1e-6);
assert.ok(Math.abs(open[2] - desired[2]) < 1e-6);

const closedRoom = [
  { position: [0, 5, 9], size: [14, 12, 1] },
  { position: [-7, 5, 2], size: [1, 12, 14] },
  { position: [7, 5, 2], size: [1, 12, 14] },
  { position: [0, 11, 2], size: [14, 1, 14] },
];
const outside = chooseSafeCamera(target, [0, 6, 15], closedRoom, 14, 36);
assert.ok(!closedRoom.some((box) => Math.abs(outside[0] - box.position[0]) <= box.size[0] / 2 + 0.8
  && Math.abs(outside[1] - box.position[1]) <= box.size[1] / 2 + 0.8
  && Math.abs(outside[2] - box.position[2]) <= box.size[2] / 2 + 0.8), 'camera must not remain inside building geometry');
// The shipped MP4 contained a shot from below the character's feet looking up at
// a roofline, with the subject tiny in the corner. Every wide shot must now look
// DOWN on its target, and no shot may be taken from underneath a roof.
const groundLevel = chooseSafeCamera([0, 3.05, 24], [0, 0.2, 40], [], 14, 36);
assert.ok(groundLevel[1] > 3.05 + 1.0, `a shot planned at ankle height must be lifted above the target, got y=${groundLevel[1]}`);
const wantedShot = [0, 3.05, 24];
assert.ok(groundLevel[1] - wantedShot[1] > 0.9, 'the camera must look down at the subject, not up at it');

const porch = [
  { position: [0, 9, 30], size: [26, 2, 22] }, // a big roof slab
  { position: [10, 4, 30], size: [2, 10, 2] },  // one of its pillars
];
for (const height of [4, 6, 7.6]) {
  const shot = chooseSafeCamera(wantedShot, [0, height, 36], porch, 14, 36);
  const under = Math.abs(shot[0] - 0) <= 26 / 2 + 0.6 && Math.abs(shot[2] - 30) <= 22 / 2 + 0.6 && shot[1] < 8;
  assert.ok(!under, `camera must never sit under the roof slab, got ${shot.map((v) => v.toFixed(2)).join(',')}`);
}

console.log('Scene camera safety smoke test passed; camera avoids walls, never rises above its subject, '
  + 'always looks down on it, and never shoots from under a roof.');
