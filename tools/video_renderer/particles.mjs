/**
 * Particle motion for the AI's effects, computed from the clock rather than
 * accumulated frame by frame.
 *
 * The renderer draws frames one at a time by asking for an exact second, so a
 * particle field must be a pure function of t: two runs of the same plan have to
 * produce the same pixels. Every particle's starting direction, offset and life
 * comes from a small deterministic generator seeded per field.
 *
 * This module is plain maths - no Three.js, no canvas - so it can be tested in
 * Node without a browser.
 */

/** A tiny deterministic generator: the same effect looks the same on every run. */
export function seeded(seed) {
  let state = (Math.imul(seed >>> 0, 2654435761) >>> 0) || 1;
  return () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 4294967296;
  };
}

const TINTS_UNSUPPORTED = new Set(['smoke', 'mist', 'fog']);

/**
 * Pre-compute one field: how many particles, which way each one leaves, when it
 * was born and how long it lives.
 */
export function createParticleField(effect, seed = 1) {
  const rate = Math.max(0.05, Math.min(1, Number(effect?.rate) || 0.6));
  const count = Math.max(6, Math.min(120, Math.round(rate * 90)));
  const spread = Math.max(0, Math.min(1, Number(effect?.spread) || 0));
  const life = Math.max(0.1, Number(effect?.life) || 2);
  const random = seeded(seed + 7);
  const direction = [];
  const offset = [];
  const lifeSpan = [];
  for (let index = 0; index < count; index += 1) {
    const theta = random() * Math.PI * 2;
    // A cone opening upward: spread 0 is a straight jet, spread 1 a full sphere.
    const phi = Math.acos(Math.max(-1, Math.min(1, 1 - 2 * random() * spread)));
    direction.push([
      Math.cos(theta) * Math.sin(phi),
      Math.cos(phi),
      Math.sin(theta) * Math.sin(phi),
    ]);
    offset.push(random() * life);
    lifeSpan.push(life * (0.6 + random() * 0.8));
  }
  return { count, direction, offset, lifeSpan };
}

/**
 * Where every particle of a field is at second t.
 *
 * @returns {Float32Array} flat x,y,z triples, ready for a BufferGeometry.
 */
export function sampleParticles(field, origin, effect, t, target = null, options = {}) {
  const positions = target || new Float32Array(field.count * 3);
  const speed = Math.max(-20, Number(effect?.speed) || 0);
  const gravity = Math.max(-20, Number(effect?.gravity) || 0);
  const twinkle = Boolean(effect?.twinkle);
  const floor = Number.isFinite(options.floor) ? options.floor : -0.05;
  const [ox, oy, oz] = origin;
  for (let index = 0; index < field.count; index += 1) {
    const span = field.lifeSpan[index];
    const born = field.offset[index];
    const age = ((t + born) % span + span) % span;
    const [dx, dy, dz] = field.direction[index];
    const sway = Math.sin((t + born) * 3 + index) * 0.08;
    let y = oy + dy * speed * age + 0.5 * gravity * age * age + sway;
    if (twinkle) y += Math.sin((t * 6 + index) * 1.3) * 0.12;
    // Nothing sinks below the ground plane and keeps glittering there.
    if (y < floor) y = floor;
    positions[index * 3] = ox + dx * speed * age;
    positions[index * 3 + 1] = y;
    positions[index * 3 + 2] = oz + dz * speed * age;
  }
  return positions;
}

/** Soft smoke and dust are drawn over the scene, not added to it. */
export function isAdditive(family) {
  return !['smoke', 'mist', 'fog', 'dust', 'confetti', 'petals', 'leaves', 'snow', 'rain',
    'bubbles'].includes(String(family || ''));
}

export { TINTS_UNSUPPORTED };
