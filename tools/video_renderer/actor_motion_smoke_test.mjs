// "No moving around, just animation" - the shipped MP4 had characters standing on
// one spot while a walk cycle ran underneath them, facing away from the way they
// were sliding. This test drives the real blocking maths of the renderer and
// checks, over a whole 120-second bedroom short:
//
//   1. every character actually travels several studs across the video;
//   2. they are somewhere new at each camera cut (a blocked scene, not a statue);
//   3. they WALK to a mark and then STAND: the walk amplitude is 0 while planted;
//   4. the walk cycle advances with distance walked, so feet never skate;
//   5. they face the way they walk, using the avatar's real front (+Z), and turn
//      towards the other character when they stop;
//   6. nobody leaves the room (no wall-clipping, no wandering into the garden);
//   7. the whole thing is deterministic, so re-rendering gives the same film.
import assert from 'node:assert/strict';
import { planMarks, poseAt, roomBoundsFrom, shotIndexAt, yawToward } from './actor_motion.mjs';

const ROOM = { width: 26, depth: 26, height: 10, centre_z: 24 };
const shots = Array.from({ length: 10 }, (_, index) => ({
  time: index === 9 ? 120 : index * 12,
  framing: index === 2 || index === 4 ? 'face' : 'auto',
}));
const DURATION = 120;
const cast = [
  { username: 'normal', baseX: 0, baseZ: 24, lead: true, phase: 0 },
  { username: 'noob', baseX: -2, baseZ: 25.5, lead: false, phase: 1.73 },
];

const bounds = roomBoundsFrom(ROOM);
assert.ok(bounds, 'a room must produce bounds');
assert.ok(bounds.minX < 0 && bounds.maxX > 0 && bounds.maxZ - bounds.minZ > 15);

// 1 + 2. Marks differ at cuts and the cast travels.
const planned = planMarks({ actors: cast, shots, drift: 2.0, bounds });
assert.equal(planned.length, 2);
for (const entry of planned) {
  assert.equal(entry.marks.length, shots.length);
  assert.ok(entry.travelled > 4, `each character must actually move; travelled ${entry.travelled}`);
  const distinct = new Set(entry.marks.map((mark) => `${mark[0].toFixed(1)},${mark[1].toFixed(1)}`));
  assert.ok(distinct.size >= shots.length - 1, 'every cut should block the scene somewhere new');
}

// 6. Everything stays inside the room, and the two never overlap.
for (let index = 0; index < shots.length; index += 1) {
  const [first, second] = planned.map((entry) => entry.marks[index]);
  const gap = Math.hypot(second[0] - first[0], second[1] - first[1]);
  assert.ok(gap >= 2.5, `shot ${index}: characters stand ${gap.toFixed(2)} studs apart`);
  for (const mark of [first, second]) {
    assert.ok(mark[0] >= bounds.minX - 1e-6 && mark[0] <= bounds.maxX + 1e-6,
      `shot ${index}: x ${mark[0]} left the room`);
    assert.ok(mark[1] >= bounds.minZ - 1e-6 && mark[1] <= bounds.maxZ + 1e-6,
      `shot ${index}: z ${mark[1]} left the room`);
  }
}

// 3 + 4 + 5. Walk a whole shot frame by frame.
const walker = { marks: planned[0].marks, walkedBefore: planned[0].walkedBefore };
let lastYaw = null;
const samples = [];
for (let t = 0; t <= DURATION; t += 0.1) {
  const pose = poseAt({
    ...walker, shots, duration: DURATION, t, front: [0, 0, 1],
    partnerMarks: planned[1].marks, lastYaw,
  });
  lastYaw = pose.yaw;
  samples.push({ t, ...pose });
}

// Feet planted while standing: most of the film is spent standing (the amplitude is
// 0), and there is a real walking phase at the start of a shot.
const walking = samples.filter((sample) => sample.moving > 0.9);
const standing = samples.filter((sample) => sample.moving === 0);
assert.ok(walking.length > 15, `expected real walking phases, got ${walking.length} frames`);
assert.ok(standing.length > samples.length * 0.5, 'most of the film is a planted stand, not a treadmill');

// Walked distance never goes backwards, and the cycle advances with it.
let previousWalked = -1;
for (const sample of samples) {
  assert.ok(sample.walked >= previousWalked - 1e-6, 'the walk cycle must not run backwards');
  previousWalked = sample.walked;
}
const walkedAtEnd = samples[samples.length - 1].walked;
assert.ok(walkedAtEnd > 8, `the character should cross the room, walked ${walkedAtEnd.toFixed(1)}`);

// While walking, the body faces the direction of travel (front is +Z). The first
// 0.45 s of a shot is deliberately a TURN towards the new heading rather than a
// snap, so the heading is checked once that turn has finished.
const walkFrames = samples.filter((sample, index) => sample.moving > 0.9 && index > 0
  && sample.t - (shots[sample.shot]?.time ?? 0) > 0.6);
for (const sample of walkFrames.slice(0, 40)) {
  const previous = samples[samples.indexOf(sample) - 1];
  const dx = sample.x - previous.x;
  const dz = sample.z - previous.z;
  if (Math.hypot(dx, dz) < 1e-4) continue;
  const expected = Math.atan2(dx, dz);
  const delta = Math.abs(((sample.yaw - expected + Math.PI) % (Math.PI * 2) + Math.PI * 2) % (Math.PI * 2) - Math.PI);
  assert.ok(delta < 0.35, `walking yaw ${sample.yaw.toFixed(2)} should face ${expected.toFixed(2)}`);
}

// When standing, the character turns towards the other character.
const standFrames = samples.filter((sample) => sample.moving === 0 && sample.t > 30);
assert.ok(standFrames.length > 10);
for (const sample of standFrames.slice(0, 20)) {
  const partner = planned[1].marks[shotIndexAt(shots, sample.t)];
  const expected = Math.atan2(partner[0] - sample.x, partner[1] - sample.z);
  const delta = Math.abs(((sample.yaw - expected + Math.PI) % (Math.PI * 2) + Math.PI * 2) % (Math.PI * 2) - Math.PI);
  assert.ok(delta < 0.5, `standing yaw ${sample.yaw.toFixed(2)} should face the partner ${expected.toFixed(2)}`);
}

// The avatar's front really is honoured: a -Z avatar gets the opposite yaw.
assert.ok(Math.abs(yawToward([0, 0, 1], 0, 1) - 0) < 1e-6, 'a +Z avatar faces +Z at yaw 0');
assert.ok(Math.abs(Math.abs(yawToward([0, 0, -1], 0, 1)) - Math.PI) < 1e-6, 'a -Z avatar faces +Z at yaw PI');

// 7. Deterministic: the same inputs block the scene identically.
const again = planMarks({ actors: cast, shots, drift: 2.0, bounds });
assert.deepEqual(again, planned);

// An open world (no interior) still blocks, on the old, wider stage.
const outdoors = planMarks({ actors: cast, shots, drift: 3.0, bounds: null });
assert.equal(outdoors.length, 2);
assert.ok(outdoors[0].travelled > 4);
for (const entry of outdoors) {
  for (const [x, z] of entry.marks) {
    assert.ok(Math.abs(x) <= 16 && z >= 8 && z <= 48, 'outdoor marks keep the old cast lane');
  }
}

console.log(`Acting check: ${planned[0].marks.length} marks, ${walkedAtEnd.toFixed(1)} studs walked, ` +
  `${walking.length} walking frames, ${standing.length} planted frames, nobody left the room.`);
