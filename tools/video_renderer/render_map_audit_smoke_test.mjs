import assert from 'node:assert/strict';
import { auditRenderProps, isCameraHazard } from './render_map_audit.mjs';

const room = { width: 26, depth: 26, height: 10, centre_z: 24 };
const props = [
  { name: 'Room Floor', shell: true, position: [0, 0.1, 24], size: [26, 0.2, 26] },
  { name: 'Room Ceiling', shell: true, position: [0, 10, 24], size: [26, 0.5, 26] },
  { name: 'Room Wall Left', shell: true, position: [-13, 5, 24], size: [0.5, 10, 25] },
  { name: 'Room Wall Right', shell: true, position: [13, 5, 24], size: [0.5, 10, 25] },
  { name: 'Room Wall Back 1', shell: true, position: [-9, 5, 37], size: [8.5, 10, 0.5] },
  { name: 'Room Wall Back 2', shell: true, position: [9, 5, 37], size: [8.5, 10, 0.5] },
  { name: 'Room Front Wall 1', shell: true, position: [-8, 5, 11], size: [10, 10, 0.5] },
  { name: 'Room Front Wall 2', shell: true, position: [8, 5, 11], size: [10, 10, 0.5] },
  // The lintel and glazed door are separate shell pieces in the production room;
  // count them too, matching the renderer's minimum of eight wall/door/window parts.
  { name: 'Room Front Door Header', shell: true, position: [0, 9.5, 11], size: [6, 1, 0.5] },
  { name: 'Room Front Door Window', shell: true, position: [0, 8, 11], size: [2, 2, 0.5] },
  // The sky board sits just past the window opening, intentionally beyond the room.
  { name: 'Room Sky Through Window', shell: true, position: [0, 6, 39], size: [13, 8, 0.5] },
  // Ordinary furniture occupies the same global cast lane as the characters.
  { name: 'Bunk Bed Mattress', position: [-8, 2, 30], size: [5, 1, 8] },
  { name: 'Wardrobe', position: [9, 4, 34], size: [3, 7, 2] },
  // A stray out-of-room slab still fails the cast-lane guard.
  { name: 'Bad Stage Wall', position: [0, 5, 6], size: [8, 10, 1] },
  // Bounded props stay bounded even if a bad plan marks one as shell geometry.
  { name: 'Oversized Shell', shell: true, position: [0, 5, 24], size: [80, 10, 80] },
];

const result = auditRenderProps(props, room);
const names = new Set(result.props.map((part) => part.name));
for (const name of [
  'Room Floor', 'Room Ceiling', 'Room Wall Left', 'Room Wall Right',
  'Room Wall Back 1', 'Room Wall Back 2', 'Room Front Wall 1', 'Room Front Wall 2',
  'Room Sky Through Window', 'Bunk Bed Mattress', 'Wardrobe',
]) assert.ok(names.has(name), `${name} must survive the indoor render audit`);
assert.ok(!names.has('Bad Stage Wall'), 'an out-of-room object must not cover the cast lane');
assert.ok(!names.has('Oversized Shell'), 'the shell flag must not bypass the maximum part size');
assert.equal(result.audit.roomFloorY, 0, 'the floor is snapped to ground height, never lifted to Y=0.5');
assert.ok(result.audit.roomWallParts >= 8, `wall/door/window coverage was lost: ${result.audit.roomWallParts}`);
assert.ok(result.audit.roomFurnitureParts >= 2);
const mattress = props.find((part) => part.name === 'Bunk Bed Mattress');
const badStage = props.find((part) => part.name === 'Bad Stage Wall');
assert.ok(!isCameraHazard(mattress, room), 'furniture in an interior is not an outdoor cast-lane hazard');
assert.ok(isCameraHazard(badStage, room), 'a stray part outside the room is still rejected');

const outdoor = auditRenderProps([
  { name: 'Outdoor obstruction', position: [0, 5, 24], size: [8, 10, 1] },
  { name: 'Outdoor scenery', position: [40, 5, 24], size: [8, 10, 1] },
]);
assert.equal(outdoor.props.length, 1, 'the outdoor cast-lane safety rule remains active');
assert.equal(outdoor.props[0].name, 'Outdoor scenery');

console.log('Render map audit smoke test passed: indoor walls, furnishings, window backboard and ground-level floor survive; outdoor cast hazards are still removed.');
