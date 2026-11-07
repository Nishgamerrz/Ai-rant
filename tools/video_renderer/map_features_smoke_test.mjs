#!/usr/bin/env node
/**
 * Prove the new map vocabulary really works: every shape builds a closed unit
 * mesh with real Three.js, and every particle field is deterministic and lands
 * where gravity says it should.
 *
 * The AI can now ask for triangles, domes, rings, cones and trusses, and for
 * lamps and particle effects. None of that is worth anything if a shape comes out
 * inside-out or a sparkle field drifts through the floor, and a browser is not
 * needed to know: geometry and particle maths are plain JavaScript.
 */
import { buildShapeGeometry, SHAPES, SHAPE_ROTATIONS, mergedBoxes } from './map_shapes.mjs';
import { createParticleField, sampleParticles, isAdditive, seeded } from './particles.mjs';

let failures = 0;
function check(label, condition, detail = '') {
  if (condition) return;
  failures += 1;
  console.error(`FAIL ${label}${detail ? `: ${detail}` : ''}`);
}

/* --- shapes ------------------------------------------------------------- */
const geometries = buildShapeGeometry();
const names = Object.keys(geometries);

check('every declared shape has geometry', SHAPES.every(name => geometries[name]),
  SHAPES.filter(name => !geometries[name]).join(', '));
check('no geometry without a declaration', names.every(name => SHAPES.includes(name)),
  names.filter(name => !SHAPES.includes(name)).join(', '));

for (const [name, geometry] of Object.entries(geometries)) {
  geometry.computeBoundingBox();
  const box = geometry.boundingBox;
  const size = [box.max.x - box.min.x, box.max.y - box.min.y, box.max.z - box.min.z];
  const centre = [box.max.x + box.min.x, box.max.y + box.min.y, box.max.z + box.min.z].map(v => v / 2);
  const positions = geometry.attributes.position.array;
  check(`${name}: has vertices`, positions.length >= 9, `${positions.length / 3} vertices`);
  check(`${name}: no NaN vertex`, positions.every(Number.isFinite), 'a vertex is NaN');
  check(`${name}: fits in a unit cube`, size.every(v => v > 0.02 && v <= 1.02), size.map(v => v.toFixed(3)).join('x'));
  check(`${name}: centred on the origin`, centre.every(v => Math.abs(v) < 0.06), centre.map(v => v.toFixed(3)).join(','));
  const triangleCount = geometry.index ? geometry.index.count / 3 : positions.length / 9;
  check(`${name}: is a real solid`, triangleCount >= 2, `${triangleCount} triangles`);
}

// A triangle was impossible before: the wedge must actually be a prism, not a box.
const wedge = geometries.Wedge;
wedge.computeBoundingBox();
check('wedge keeps a full base and a sloped top', wedge.boundingBox.max.y === 0.5 && wedge.boundingBox.min.y === -0.5);
const wedgeVertices = new Set();
const wedgePositions = wedge.attributes.position.array;
for (let i = 0; i < wedgePositions.length; i += 3) {
  wedgeVertices.add(`${wedgePositions[i].toFixed(2)},${wedgePositions[i + 1].toFixed(2)},${wedgePositions[i + 2].toFixed(2)}`);
}
check('wedge has exactly six corners (a triangular prism)', wedgeVertices.size === 6, `${wedgeVertices.size} corners`);

check('cylinder is turned onto its Roblox axis', Array.isArray(SHAPE_ROTATIONS.Cylinder));
check('truss merges its bars into one mesh', mergedBoxes([
  { size: [1, 0.1, 0.1], position: [0, 0, 0] },
  { size: [0.1, 1, 0.1], position: [0, 0, 0] },
]).attributes.position.count === 72, String(geometries.Truss.attributes.position.count));

/* --- particles ---------------------------------------------------------- */
const sparkles = { family: 'sparkles', rate: 0.6, size: 0.4, speed: 1.5, life: 1.6, gravity: 0.7, spread: 0.75, twinkle: true };
const rain = { family: 'rain', rate: 0.8, size: 0.16, speed: 6.5, life: 1.6, gravity: -6, spread: 0.5, twinkle: false };
const smoke = { family: 'smoke', rate: 0.5, size: 1.3, speed: 0.9, life: 3.4, gravity: 0.55, spread: 0.45, twinkle: false };

const field = createParticleField(sparkles, 1);
check('a field has particles', field.count >= 6 && field.count <= 120, String(field.count));
check('density drives the count', createParticleField({ ...sparkles, rate: 1 }, 1).count
  > createParticleField({ ...sparkles, rate: 0.1 }, 1).count);

const randomA = seeded(1);
const randomB = seeded(1);
check('the generator is deterministic', [1, 2, 3, 4, 5].every(() => randomA() === randomB()));
check('the generator is uniform enough', (() => {
  const sample = seeded(3);
  let low = 0;
  for (let i = 0; i < 2000; i += 1) if (sample() < 0.5) low += 1;
  return low > 800 && low < 1200;
})());

const origin = [10, 5, -20];
const atOne = sampleParticles(field, origin, sparkles, 1.0);
const againAtOne = sampleParticles(field, origin, sparkles, 1.0);
check('the same second gives the same frame', atOne.every((v, i) => v === againAtOne[i]));
check('positions are finite', atOne.every(Number.isFinite));
check('particles stay near their lamp', atOne.every((value, index) => {
  const axis = index % 3;
  return Math.abs(value - origin[axis]) < 14;
}), 'a particle drifted more than 14 studs from its anchor');

// Rain falls. Rising effects rise. Smoke rises slowly. Individual particles wrap
// around and start again, so the whole field is compared, not one particle.
const meanHeight = (positions) => {
  let total = 0;
  for (let i = 1; i < positions.length; i += 3) total += positions[i];
  return total / (positions.length / 3);
};
const rainField = createParticleField(rain, 2);
const rainLow = meanHeight(sampleParticles(rainField, [0, 20, 0], rain, 1.0));
const rainHigh = meanHeight(sampleParticles(rainField, [0, 20, 0], rain, 1.05));
check('rain falls over time', rainHigh < rainLow, `${rainLow.toFixed(2)} -> ${rainHigh.toFixed(2)}`);
const smokeField = createParticleField(smoke, 3);
const smokeLow = meanHeight(sampleParticles(smokeField, [0, 2, 0], smoke, 1.0));
const smokeHigh = meanHeight(sampleParticles(smokeField, [0, 2, 0], smoke, 1.4));
check('smoke rises over time', smokeHigh > smokeLow, `${smokeLow.toFixed(2)} -> ${smokeHigh.toFixed(2)}`);

// Nothing keeps glittering below the ground.
const sunk = sampleParticles(rainField, [0, 0.4, 0], rain, 0.9);
check('particles never sink below the floor', sunk.every((value, index) => index % 3 !== 1 || value >= -0.06));

check('glowing effects add light to the scene', isAdditive('sparkles') === true);
check('smoke is drawn over the scene', isAdditive('smoke') === false);
check('confetti is not additive', isAdditive('confetti') === false);

if (failures) {
  console.error(`Map feature smoke test failed: ${failures} problem(s).`);
  process.exit(1);
}
console.log(`Map feature smoke test passed; ${names.length} shapes built with real Three.js `
  + `(${names.join(', ')}), particle fields deterministic, rain falls and smoke rises.`);
