import assert from 'node:assert/strict';
import * as THREE from 'three';
import { buildAvatarRig, measureHeadRegion } from './avatar_rig.mjs';
import {
  applyFaceHeadMotion, blinkAt, blinkSchedule, createFaceRig, drawFace, expressionAt,
  faceStateAt, mouthOpenAt, normalizeExpressionTimeline, parseSrt, speechPulses,
  syllableCount, syntheticPulses,
} from './face_rig.mjs';

// --- caption parsing and mouth timing -------------------------------------
const srt = [
  '1', '00:00:00,000 --> 00:00:02,000', 'Maya found a wallet on the pavement.', '',
  '2', '00:00:02,100 --> 00:00:04,500', 'She could keep it, or hand it back.', '',
  '3', '00:00:05,000 --> 00:00:06,200', 'Her heart raced.',
].join('\n');
const cues = parseSrt(srt);
assert.equal(cues.length, 3);
assert.equal(cues[0].start, 0);
assert.ok(Math.abs(cues[1].end - 4.5) < 1e-6);
const pulses = speechPulses(cues);
assert.ok(pulses.length > 12, 'every spoken syllable should produce a mouth pulse');
assert.ok(pulses.every((pulse) => pulse.start >= 0 && pulse.end > pulse.start));
assert.ok(pulses[0].start < pulses.at(-1).start);
assert.ok(mouthOpenAt(cues[0].start + 0.4, pulses) > 0.3, 'the mouth must open while words are spoken');
assert.equal(mouthOpenAt(4.8, pulses), 0, 'the mouth must close in the pause between cues');
const chatter = syntheticPulses(30, 5);
assert.ok(chatter.length > 40 && chatter.at(-1).start <= 30);
assert.ok(syllableCount('pavement') >= 2 && syllableCount('pavement') <= 3,
  'multi-syllable words must flap more than once');
assert.equal(syllableCount('a'), 1);
assert.equal(syllableCount('!!!'), 0);

// --- blinking --------------------------------------------------------------
const blinks = blinkSchedule(3, 30, 1);
assert.ok(blinks.length >= 8 && blinks.length <= 40, `unexpected blink count ${blinks.length}`);
assert.equal(blinkAt(0, blinks), 0);
const midBlink = blinks[2].start + blinks[2].length / 2;
assert.ok(blinkAt(midBlink, blinks) > 0.9, 'the eyes must be shut mid-blink');
assert.deepEqual(blinkSchedule(3, 30, 1), blinks, 'blinking must be deterministic between renders');

// --- AI expression timeline -------------------------------------------------
const username = 'MayaRblx';
const timeline = normalizeExpressionTimeline([
  { time: 12, expression: 'sad', intensity: 0.9, username },
  { time: 0, expression: 'neutral' },
  { time: 3.5, expression: 'happy', intensity: 0.8, username },
  { time: 3.9, expression: 'not-a-face' },
  { time: 200, expression: 'happy' },
  { time: 21, expression: 'surprised', intensity: 'loud', username: 'SomeoneElse' },
], 60, [username]);
assert.deepEqual(timeline.map((entry) => entry.time), [0, 3.5, 12, 21]);
assert.deepEqual(timeline.map((entry) => entry.expression), ['neutral', 'happy', 'sad', 'surprised']);
assert.equal(timeline[3].username, '', 'a beat aimed at an unknown actor becomes global');
assert.deepEqual(expressionAt(3.4, timeline, username).expression, 'neutral');
assert.deepEqual(expressionAt(3.5, timeline, username).expression, 'happy');
assert.deepEqual(expressionAt(11.99, timeline, username).expression, 'happy');
assert.deepEqual(expressionAt(12.0, timeline, username).expression, 'sad');

// --- per-frame face state ---------------------------------------------------
const options = {
  timeline, username, pulses, blinks,
  seed: 4,
};
const beforeSwitch = faceStateAt(3.49, options);
const afterSwitch = faceStateAt(3.5, options);
assert.equal(beforeSwitch.expression, 'neutral');
assert.equal(afterSwitch.expression, 'happy');
assert.notEqual(beforeSwitch.smile, afterSwitch.smile, 'a switch must change the mouth curve');
const sadState = faceStateAt(12.1, options);
assert.ok(sadState.smile < 0 && sadState.brow < 0, 'sad must lower the brows and the mouth');
const openState = faceStateAt(0.5, { ...options, timeline: [] });
assert.ok(openState.mouth > 0.2, 'speech must move the mouth');
assert.ok(Number.isFinite(openState.nod) && Math.abs(openState.nod) < 0.1);

// --- painting ---------------------------------------------------------------
function recordingContext() {
  const calls = [];
  const record = (name) => (...args) => { calls.push([name, ...args]); };
  return {
    calls,
    clearRect: record('clearRect'), beginPath: record('beginPath'), ellipse: record('ellipse'),
    fill: record('fill'), stroke: record('stroke'), moveTo: record('moveTo'), lineTo: record('lineTo'),
    quadraticCurveTo: record('quadraticCurveTo'), closePath: record('closePath'), save: record('save'),
    restore: record('restore'), clip: record('clip'), fillRect: record('fillRect'),
    set fillStyle(value) { calls.push(['fillStyle', String(value)]); },
    set strokeStyle(value) { calls.push(['strokeStyle', String(value)]); },
    set lineWidth(value) { calls.push(['lineWidth', value]); },
    set lineCap(value) { calls.push(['lineCap', value]); },
  };
}
const painter = recordingContext();
drawFace(painter, afterSwitch, undefined, 512);
assert.ok(painter.calls.length > 30, 'painting a face must draw eyes, brows and a mouth');
assert.ok(painter.calls.some(([name]) => name === 'quadraticCurveTo'), 'the mouth must be curved, not a box');
const closedEyes = recordingContext();
drawFace(closedEyes, { ...afterSwitch, blink: 1, mouth: 0 }, undefined, 512);
assert.ok(!closedEyes.calls.some(([name]) => name === 'strokeText' || name === 'fillText'),
  'faces must never render text');

// --- canvas-backed face mesh -------------------------------------------------
function fakeDocument() {
  const canvas = {
    width: 0, height: 0,
    getContext: () => recordingContext(),
  };
  return { createElement: () => canvas, canvas };
}
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
rig.root.updateMatrixWorld(true);
const head = measureHeadRegion(THREE, rig);
assert.ok(head.size[0] > 0.4 && head.size[1] > 0.4, `head region looks wrong: ${JSON.stringify(head)}`);
assert.ok(head.center[1] > 4.6, 'the measured head must sit at the top of the avatar');

const doc = fakeDocument();
const face = createFaceRig(THREE, { headBone: rig.bones.Head, width: 0.82, height: 0.5, document: doc, seed: 9 });
assert.equal(face.mesh.name, 'AnimatedFace');
assert.equal(face.mesh.material.transparent, true);
assert.equal(face.mesh.material.depthWrite, false);
assert.ok(face.update(afterSwitch), 'the first paint must upload the texture');
assert.ok(!face.update(afterSwitch), 'identical frames must not re-upload the texture');
assert.ok(face.update({ ...afterSwitch, mouth: 0.6 }), 'mouth movement must repaint');

// --- head motion -------------------------------------------------------------
const before = rig.bones.Head.quaternion.clone();
applyFaceHeadMotion(THREE, rig.bones, afterSwitch);
const after = rig.bones.Head.quaternion.clone();
const delta = before.angleTo(after);
assert.ok(delta > 0 && delta < 0.25, `head motion must be subtle, got ${delta} rad`);
assert.ok(Math.abs(after.length() - 1) < 1e-6);

console.log('Face rig smoke test passed; caption-driven mouth movement, deterministic blinking, '
  + 'AI expression switching at exact times, canvas face painting without text, and subtle head motion.');
