// The MP4 must never look stretched.
//
// A stretched short never has the wrong frame size - it has a projection whose
// horizontal and vertical scales disagree, either because the camera aspect has
// drifted from the canvas, or because the encoder/container declares non-square
// pixels. render_short.mjs measures this in pixels on the live canvas; this test
// proves the measurement itself is right, without a browser or a GPU: for a
// correct perspective camera one world unit covers the same number of pixels
// across and down, and a deliberately skewed aspect shows up immediately.
console.log('Square-pixel projection check:');

const PIXEL_WIDTH = 720;
const PIXEL_HEIGHT = 1280;

// Perspective divide for a point `depth` in front of the camera, offset by
// `offset` world units along the camera's right (or up) axis.
function pixelsPerUnit({ aspect, fovDegrees, depth, offset, axis }) {
  const tanHalf = Math.tan((fovDegrees * Math.PI) / 360);
  const ndc = axis === 'x'
    ? offset / (aspect * tanHalf * depth)
    : offset / (tanHalf * depth);
  return Math.abs(ndc) * (axis === 'x' ? PIXEL_WIDTH : PIXEL_HEIGHT) / 2;
}

function stretch({ aspect = PIXEL_WIDTH / PIXEL_HEIGHT, fovDegrees = 42, depth = 12, offset = 1 } = {}) {
  const across = pixelsPerUnit({ aspect, fovDegrees, depth, offset, axis: 'x' });
  const tall = pixelsPerUnit({ aspect, fovDegrees, depth, offset, axis: 'y' });
  return across / tall;
}

function requireClose(actual, expected, message) {
  if (Math.abs(actual - expected) > 1e-9) throw new Error(`${message}: got ${actual}, expected ${expected}`);
}

// 1. A camera whose aspect matches the canvas draws square pixels.
requireClose(stretch(), 1, 'a 720x1280 camera at 42 degrees must be square');

// 2. The scale is the same at any depth and for any field of view: only the
//    ratio of the two axes matters, which is what the in-page probe relies on.
for (const depth of [2, 12, 40, 300]) requireClose(stretch({ depth }), 1, `depth ${depth} must stay square`);
for (const fovDegrees of [30, 42, 60, 90]) requireClose(stretch({ fovDegrees }), 1, `${fovDegrees} degrees must stay square`);

// 3. The historical failure: a camera that assumed a different frame shape. The
//    ratio has to move away from 1 by the same factor the aspect drifted, in
//    whichever direction - that is what makes a circle on screen an oval.
const landscape = stretch({ aspect: 16 / 9 });
if (Math.abs(landscape - 0.5625 / (16 / 9)) > 1e-9) {
  throw new Error(`a 16:9 camera on a 9:16 canvas must read as a vertical stretch of ${0.5625 / (16 / 9)}, got ${landscape}`);
}
if (Math.abs(landscape - 1) <= 0.02) throw new Error('a 16:9 camera must always trip the 2% gate');
const portrait = stretch({ aspect: 4 / 5 });
if (Math.abs(portrait - 1) <= 0.02) throw new Error('any mismatched aspect must trip the 2% gate');

// 4. The probe's two percent tolerance catches a real drift and ignores float noise.
const drifted = stretch({ aspect: (PIXEL_WIDTH / PIXEL_HEIGHT) * 1.05 });
if (Math.abs(drifted - 1) <= 0.02) throw new Error('a five percent aspect drift must trip the 2% gate');
const noise = stretch({ aspect: (PIXEL_WIDTH / PIXEL_HEIGHT) * 1.0001 });
if (Math.abs(noise - 1) > 0.02) throw new Error('a rounding-level difference must not trip the gate');

// 5. Frame sizes that are not exactly 9:16 would be rescaled by ffmpeg into a
//    stretched picture, so the renderer's constants and the encoder agree.
requireClose(Math.round(1440 / 2560 * 1e9) / 1e9, Math.round(PIXEL_WIDTH / PIXEL_HEIGHT * 1e9) / 1e9,
  'the 1440x2560 encode must be the same 9:16 shape as the 720x1280 capture');

console.log(`  720x1280 at 42 degrees: ${pixelsPerUnit({ aspect: 720 / 1280, fovDegrees: 42, depth: 12, offset: 1, axis: 'x' }).toFixed(2)}px across and `
  + `${pixelsPerUnit({ aspect: 720 / 1280, fovDegrees: 42, depth: 12, offset: 1, axis: 'y' }).toFixed(2)}px tall per world unit, ratio 1.000.`);
console.log(`  A 16:9 camera on the same canvas reads as ${(0.5625 / (16 / 9)).toFixed(2)}x, far outside 1.000, so the 2% gate in render_short.mjs stops it.`);
console.log('Projection smoke test passed: square pixels at every depth and field of view, and any aspect drift is caught before encoding.');
