import assert from 'node:assert/strict';
import { LIGHTING_PRESETS, resolveLightingAtTime, resolveTimeOfDay } from './lighting_presets.mjs';

assert.deepEqual(Object.keys(LIGHTING_PRESETS).sort(), ['dawn', 'day', 'night', 'sunset']);
assert.equal(resolveTimeOfDay('night', 'bright noon'), 'night', 'an explicit user selection wins');
assert.equal(resolveTimeOfDay('auto', 'A moonlit snowy village'), 'night');
assert.equal(resolveTimeOfDay('auto', 'A warm sunset over a village'), 'sunset');
assert.equal(resolveTimeOfDay('auto', 'A quiet sunrise in the hills'), 'dawn');
assert.equal(resolveTimeOfDay('auto', 'A green park'), 'day', 'auto has a readable daytime fallback');
assert.ok(LIGHTING_PRESETS.night.sunIntensity < LIGHTING_PRESETS.day.sunIntensity);
assert.ok(LIGHTING_PRESETS.sunset.sunColor !== LIGHTING_PRESETS.day.sunColor);
assert.ok(LIGHTING_PRESETS.night.fillIntensity > 0, 'night keeps enough cool fill to read faces and props');
assert.throws(() => resolveTimeOfDay('midnight-blue'), /Unknown time of day/);

const globalNight = { time_of_day: 'night', camera_shots: [{ time: 0 }, { time: 10 }] };
assert.deepEqual(resolveLightingAtTime(globalNight, 5), { from: 'night', to: 'night', blend: 0 });
const varied = {
  time_of_day: 'night',
  camera_shots: [
    { time: 0, time_of_day: 'night' },
    { time: 10, transition: 'smooth', time_of_day: 'sunset' },
    { time: 20, transition: 'snap', time_of_day: 'day' },
    { time: 30, transition: 'smooth' },
  ],
};
const transition = resolveLightingAtTime(varied, 5);
assert.equal(transition.from, 'night');
assert.equal(transition.to, 'sunset');
assert.ok(transition.blend > 0 && transition.blend < 1, 'smooth scene-hour changes blend gradually');
assert.deepEqual(resolveLightingAtTime(varied, 15), { from: 'sunset', to: 'day', blend: 0 },
  'a snap cut changes hour at the cut without blending');
assert.deepEqual(resolveLightingAtTime(varied, 25), { from: 'day', to: 'day', blend: 0 },
  'the last override holds through later shots that omit an hour');

console.log('Time-of-day smoke test passed: global and per-scene dawn, day, sunset, and night are usable.');
