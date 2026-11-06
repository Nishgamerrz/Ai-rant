/**
 * Animated Roblox-style faces for the rendered cast.
 *
 * The AI world plan owns the expression timeline (`face_expressions`): it says
 * exactly which feeling is on screen at which second, so cuts, narration beats
 * and face changes all land on the same moment. This module turns that plan
 * plus the narration captions into a per-frame face state (expression, mouth
 * movement, blinking, eyebrows, gaze, head nod) and paints it onto a canvas
 * texture attached to the avatar's head joint.
 */

export const EXPRESSIONS = ['neutral', 'happy', 'sad', 'surprised', 'worried', 'angry', 'excited', 'thinking'];

export const DEFAULT_PALETTE = {
  line: [44, 34, 34],
  mouth: [92, 40, 44],
  tongue: [214, 118, 128],
  teeth: [250, 250, 250],
  glint: [255, 255, 255],
  blush: [244, 150, 160],
};

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function hash(seed, index) {
  const value = Math.sin(seed * 127.1 + index * 311.7 + 74.7) * 43758.5453;
  return value - Math.floor(value);
}

/** Parse an SRT caption file so the mouth moves on the actual spoken words. */
export function parseSrt(text) {
  const cues = [];
  const blocks = String(text || '').replace(/\r/g, '').split(/\n{2,}/);
  const toSeconds = (stamp) => {
    const match = /(\d+):(\d{2}):(\d{2})[,.](\d{1,3})/.exec(stamp || '');
    if (!match) return null;
    return Number(match[1]) * 3600 + Number(match[2]) * 60 + Number(match[3]) + Number(match[4]) / 1000;
  };
  for (const block of blocks) {
    const lines = block.split('\n').filter((line) => line.trim());
    const timing = lines.find((line) => line.includes('-->'));
    if (!timing) continue;
    const [rawStart, rawEnd] = timing.split('-->');
    const start = toSeconds(rawStart);
    const end = toSeconds(rawEnd);
    if (start === null || end === null || end <= start) continue;
    const words = lines.slice(lines.indexOf(timing) + 1).join(' ').replace(/<[^>]*>/g, '').trim();
    if (!words) continue;
    cues.push({ start, end, text: words });
  }
  cues.sort((a, b) => a.start - b.start);
  return cues;
}

export function syllableCount(word) {
  const cleaned = String(word || '').toLowerCase().replace(/[^a-z']/g, '');
  if (!cleaned) return 0;
  const groups = cleaned.match(/[aeiouy]+/g) || [];
  let count = groups.length;
  if (cleaned.length > 3 && cleaned.endsWith('e') && !cleaned.endsWith('le') && count > 1) count -= 1;
  return Math.max(1, count);
}

/**
 * Turn captions into mouth-open pulses. Each cue is split by syllable weight so
 * fast sentences flap faster and pauses close the mouth completely.
 */
export function speechPulses(cues) {
  const pulses = [];
  for (const cue of cues) {
    const words = cue.text.split(/\s+/).filter(Boolean);
    const syllables = Math.max(1, words.reduce((total, word) => total + syllableCount(word), 0));
    const span = Math.max(0.08, cue.end - cue.start);
    const step = span / syllables;
    for (let index = 0; index < syllables; index += 1) {
      const start = cue.start + index * step;
      pulses.push({ start, end: start + step * 0.72, peak: 0.55 + 0.45 * hash(7, pulses.length) });
    }
  }
  pulses.sort((a, b) => a.start - b.start);
  return pulses;
}

/** Fallback chatter when no captions are available, so the face is never frozen. */
export function syntheticPulses(duration, seed = 3) {
  const pulses = [];
  let time = 0.6;
  let index = 0;
  while (time < duration) {
    const length = 0.11 + hash(seed, index) * 0.1;
    pulses.push({ start: time, end: time + length, peak: 0.45 + hash(seed + 1, index) * 0.4 });
    time += length + 0.06 + hash(seed + 2, index) * 0.16;
    index += 1;
  }
  return pulses;
}

/** Mouth openness 0..1 at a given time, with a natural attack and release. */
export function mouthOpenAt(time, pulses) {
  let open = 0;
  for (const pulse of pulses) {
    if (time < pulse.start - 0.09) break;
    if (time > pulse.end + 0.16) continue;
    const attack = clamp((time - (pulse.start - 0.05)) / 0.05, 0, 1);
    const release = clamp((pulse.end + 0.14 - time) / 0.18, 0, 1);
    open = Math.max(open, pulse.peak * Math.min(attack, release));
  }
  return clamp(open, 0, 1);
}

/** Deterministic blink schedule: mostly single blinks, now and then a double. */
export function blinkSchedule(seed, duration, density = 1) {
  const times = [];
  let time = 0.9 + hash(seed, 1) * 2.2;
  let index = 0;
  while (time < duration + 1) {
    times.push({ start: time, length: 0.11 + hash(seed, index * 3 + 2) * 0.06 });
    if (hash(seed, index * 5 + 4) > 0.82) {
      times.push({ start: time + 0.3, length: 0.1 });
    }
    time += (1.7 + hash(seed, index * 7 + 6) * 2.9) / Math.max(0.2, density);
    index += 1;
  }
  return times;
}

export function blinkAt(time, schedule) {
  let closed = 0;
  for (const blink of schedule) {
    const half = blink.length / 2;
    const distance = Math.abs(time - (blink.start + half));
    if (distance < half) closed = Math.max(closed, 1 - distance / half);
  }
  return clamp(closed, 0, 1);
}

/** Normalise the AI timeline into sorted, clamped entries. */
export function normalizeExpressionTimeline(entries, duration = 0, usernames = []) {
  const valid = new Set(usernames.map((name) => String(name).toLowerCase()));
  const output = [];
  for (const entry of Array.isArray(entries) ? entries : []) {
    if (!entry || typeof entry !== 'object') continue;
    const expression = String(entry.expression || '').toLowerCase();
    if (!EXPRESSIONS.includes(expression)) continue;
    const time = Number(entry.time);
    if (!Number.isFinite(time) || time < 0) continue;
    if (duration && time > duration + 0.5) continue;
    const intensity = clamp(Number(entry.intensity ?? 0.8), 0, 1);
    const username = String(entry.username ?? entry.character ?? '').trim();
    output.push({
      time: Math.round(time * 100) / 100,
      expression,
      intensity,
      username: username && valid.has(username.toLowerCase()) ? username : '',
    });
  }
  output.sort((a, b) => a.time - b.time);
  return output;
}

/** Which expression the AI scheduled for this actor at this time. */
export function expressionAt(time, timeline, username = '') {
  const key = String(username || '').toLowerCase();
  let chosen = { expression: 'neutral', intensity: 0.7 };
  for (const entry of timeline) {
    if (entry.time > time + 1e-6) break;
    if (entry.username && entry.username.toLowerCase() !== key) continue;
    chosen = { expression: entry.expression, intensity: entry.intensity };
  }
  return chosen;
}

const SHAPES = {
  happy: { brow: 0.55, smile: 1, eyeSquint: 0.25, mouthWide: 1.05, cheek: 1 },
  excited: { brow: 0.9, smile: 1, eyeSquint: 0.1, mouthWide: 1.2, cheek: 0.9 },
  sad: { brow: -0.75, smile: -0.85, eyeSquint: 0.15, mouthWide: 0.85, cheek: 0.15 },
  worried: { brow: -0.45, smile: -0.35, eyeSquint: 0.05, mouthWide: 0.8, cheek: 0.1 },
  angry: { brow: -0.95, smile: -0.6, eyeSquint: 0.5, mouthWide: 0.9, cheek: 0.4 },
  surprised: { brow: 1, smile: 0.1, eyeSquint: -0.35, mouthWide: 0.95, cheek: 0.05 },
  thinking: { brow: -0.2, smile: 0.05, eyeSquint: 0.2, mouthWide: 0.7, cheek: 0.05 },
  neutral: { brow: 0, smile: 0.12, eyeSquint: 0, mouthWide: 0.9, cheek: 0.05 },
};

/**
 * Per-frame face state. Everything the canvas painter and the head joint need.
 */
export function faceStateAt(time, options = {}) {
  const {
    timeline = [], pulses = [], blinks = [], expression: fallback = 'neutral',
    intensity: fallbackIntensity = 0.7, speaking = true, seed = 1,
  } = options;
  const scheduled = expressionAt(time, timeline, options.username || '');
  const expression = timeline.length ? scheduled.expression : fallback;
  const intensity = timeline.length ? scheduled.intensity : fallbackIntensity;
  const shape = SHAPES[expression] || SHAPES.neutral;
  const mouth = speaking ? mouthOpenAt(time, pulses) : 0;
  const blink = blinkAt(time, blinks);
  const gazeNoiseX = (hash(seed, Math.floor(time * 1.3)) - 0.5) * 0.22;
  const gazeNoiseY = (hash(seed + 5, Math.floor(time * 0.9)) - 0.5) * 0.14;
  return {
    time,
    expression,
    intensity,
    mouth,
    blink,
    brow: clamp(shape.brow * intensity + mouth * 0.08, -1, 1),
    smile: clamp(shape.smile * intensity, -1, 1),
    eyeSquint: clamp(shape.eyeSquint * intensity, -0.5, 1),
    mouthWide: shape.mouthWide,
    cheek: shape.cheek * intensity,
    gaze: [gazeNoiseX, gazeNoiseY],
    nod: Math.sin(time * 2.3 + seed) * 0.02 + mouth * 0.03,
    tilt: Math.sin(time * 0.7 + seed * 1.9) * 0.015,
  };
}

function rgba(color, alpha = 1) {
  return `rgba(${color[0]},${color[1]},${color[2]},${alpha})`;
}

/**
 * Paint the face. `ctx` is a 2D canvas context; kept free of DOM lookups so the
 * same painter can be tested with a recording stub.
 */
export function drawFace(ctx, state, palette = DEFAULT_PALETTE, size = 512) {
  const line = palette.line || DEFAULT_PALETTE.line;
  ctx.clearRect(0, 0, size, size);
  const eyeY = size * 0.44;
  const eyeOffset = size * 0.155;
  const openness = 1 - state.blink;
  const eyeHeight = size * (0.075 + state.eyeSquint * 0.03 + (state.expression === 'surprised' ? 0.02 : 0)) * Math.max(0.04, openness);
  const eyeWidth = size * 0.075;

  // Blush gives the cheerful beats a readable, friendly face.
  if (state.cheek > 0.05) {
    ctx.fillStyle = rgba(palette.blush || DEFAULT_PALETTE.blush, 0.32 * state.cheek);
    for (const side of [-1, 1]) {
      ctx.beginPath();
      ctx.ellipse(size / 2 + side * size * 0.27, size * 0.56, size * 0.075, size * 0.045, 0, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  for (const side of [-1, 1]) {
    const cx = size / 2 + side * eyeOffset + state.gaze[0] * size * 0.03;
    const cy = eyeY + state.gaze[1] * size * 0.02;
    if (openness < 0.16) {
      ctx.strokeStyle = rgba(line, 0.95);
      ctx.lineWidth = size * 0.014;
      ctx.lineCap = 'round';
      ctx.beginPath();
      ctx.moveTo(cx - eyeWidth, cy);
      ctx.lineTo(cx + eyeWidth, cy);
      ctx.stroke();
    } else {
      ctx.fillStyle = rgba(line, 0.95);
      ctx.beginPath();
      ctx.ellipse(cx, cy, eyeWidth, eyeHeight, 0, 0, Math.PI * 2);
      ctx.fill();
      if (eyeHeight > size * 0.035) {
        ctx.fillStyle = rgba(palette.glint || DEFAULT_PALETTE.glint, 0.92);
        ctx.beginPath();
        ctx.ellipse(cx - eyeWidth * 0.3, cy - eyeHeight * 0.35, eyeWidth * 0.26, eyeHeight * 0.24, 0, 0, Math.PI * 2);
        ctx.fill();
      }
    }
    // Eyebrows carry most of the expression change, so their angle matters.
    const browY = eyeY - size * 0.115 - state.brow * size * 0.04;
    const inner = cx - side * eyeWidth * 1.05;
    const outer = cx + side * eyeWidth * 1.15;
    ctx.strokeStyle = rgba(line, 0.9);
    ctx.lineWidth = size * 0.016;
    ctx.lineCap = 'round';
    ctx.beginPath();
    ctx.moveTo(outer, browY + state.brow * size * 0.006);
    ctx.lineTo(inner, browY - state.brow * size * 0.028);
    ctx.stroke();
  }

  // Mouth: open for speech, curved by the current expression.
  const mouthY = size * 0.68;
  const halfWidth = size * 0.105 * state.mouthWide;
  const openHeight = size * (0.012 + state.mouth * 0.095);
  const curve = state.smile * size * 0.05;
  ctx.beginPath();
  ctx.moveTo(size / 2 - halfWidth, mouthY);
  ctx.quadraticCurveTo(size / 2, mouthY + curve * 2 - openHeight * 0.9, size / 2 + halfWidth, mouthY);
  ctx.quadraticCurveTo(size / 2, mouthY + openHeight + Math.max(0, curve) * 0.4, size / 2 - halfWidth, mouthY);
  ctx.closePath();
  ctx.fillStyle = rgba(palette.mouth || DEFAULT_PALETTE.mouth, 0.95);
  ctx.fill();
  if (openHeight > size * 0.03) {
    ctx.save();
    ctx.clip();
    ctx.fillStyle = rgba(palette.tongue || DEFAULT_PALETTE.tongue, 0.85);
    ctx.beginPath();
    ctx.ellipse(size / 2, mouthY + openHeight * 0.95, halfWidth * 0.62, openHeight * 0.42, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = rgba(palette.teeth || DEFAULT_PALETTE.teeth, 0.95);
    ctx.fillRect(size / 2 - halfWidth, mouthY - openHeight, halfWidth * 2, openHeight * 0.28);
    ctx.restore();
  }
  ctx.strokeStyle = rgba(line, 0.6);
  ctx.lineWidth = size * 0.007;
  ctx.stroke();
  return state;
}

/** Small extra head/neck motion so a talking face never looks frozen. */
export function applyFaceHeadMotion(THREE, bones, state) {
  if (!bones?.Head) return false;
  const head = bones.Head;
  const tilt = new THREE.Quaternion().setFromEuler(
    new THREE.Euler(state.nod, state.tilt + state.gaze[0] * 0.08, -state.gaze[0] * 0.05));
  head.quaternion.multiply(tilt);
  if (bones.Neck) {
    const neck = new THREE.Quaternion().setFromEuler(
      new THREE.Euler(state.nod * 0.45, state.gaze[0] * 0.05, 0));
    bones.Neck.quaternion.multiply(neck);
  }
  return true;
}

/**
 * Build the face mesh for one avatar and return an updater.
 * The plane is parented to the head joint, so it turns and nods with the body.
 */
export function createFaceRig(THREE, options = {}) {
  const {
    headBone, width = 0.9, height = 0.62, palette = DEFAULT_PALETTE,
    seed = 1, canvasSize = 256, document: doc = globalThis.document,
  } = options;
  if (!headBone) throw new Error('face rig needs a Head bone');
  if (!doc) throw new Error('face rig needs a document to build its canvas texture');
  const canvas = doc.createElement('canvas');
  canvas.width = canvasSize;
  canvas.height = canvasSize;
  const ctx = canvas.getContext('2d');
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 4;
  const material = new THREE.MeshBasicMaterial({
    map: texture, transparent: true, depthWrite: false, alphaTest: 0.02,
    side: THREE.DoubleSide, toneMapped: false,
  });
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(width, height), material);
  mesh.name = 'AnimatedFace';
  mesh.renderOrder = 2;
  let lastKey = '';
  const update = (state) => {
    // Repaint ~12 times a second at most: enough for natural speech and
    // blinking, without uploading a texture for every rendered frame.
    const key = `${state.expression}|${Math.round(state.mouth * 12)}|${Math.round(state.blink * 12)}|`
      + `${Math.round(state.brow * 8)}|${Math.round(state.gaze[0] * 8)}|${Math.round(state.gaze[1] * 8)}`;
    if (key === lastKey) return false;
    lastKey = key;
    drawFace(ctx, state, palette, canvasSize);
    texture.needsUpdate = true;
    return true;
  };
  return { mesh, update, texture, canvas, seed };
}

/** Shared default timeline for stories that arrive without one. */
export function defaultFaceTimeline(duration, options = {}) {
  const beats = [
    [0.0, 'neutral', 0.6],
    [0.12, 'thinking', 0.7],
    [0.3, 'worried', 0.8],
    [0.52, 'surprised', 0.85],
    [0.68, 'thinking', 0.6],
    [0.84, 'happy', 0.9],
    [0.95, 'happy', 1.0],
  ];
  return beats.map(([fraction, expression, intensity]) => ({
    time: Math.round(duration * fraction * 100) / 100, expression, intensity, username: '',
  }));
}
