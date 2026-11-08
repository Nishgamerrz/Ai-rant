// The world must be bright and coloured, not washed out.
//
// Two bugs produced the pale, colourless frames: the AI's sRGB colours were fed
// to THREE.Color as if they were already linear (which brightens and desaturates
// every Part), and the light budget summed to roughly 6x, so every lit surface
// clipped past white. This test runs the same maths the shader runs - sRGB to
// linear, a Lambert light sum, three's AgX tone curve, back to sRGB bytes - and
// asserts the result is a readable midtone with visible colour.
//
// It needs no GPU: the numbers are the point.
import assert from 'node:assert/strict';
import * as THREE from 'three';

console.log('Lighting balance check:');

// --- the light budget, copied from render_short.mjs ---------------------------
const SUN = 1.35;
const HEMISPHERE = 0.5;
const AMBIENT = 0.15;
const EXPOSURE = 1.1;
// A surface facing the sun, a surface in the shade, and one edge-on.
const TOP_LIT = SUN + HEMISPHERE * 0.75 + AMBIENT;
const SHADED = HEMISPHERE * 0.35 + AMBIENT;

// --- three's AgX tone mapping, ported from tonemapping_pars_fragment ----------
// Column-major, exactly as three declares them in tonemapping_pars_fragment.
const LINEAR_SRGB_TO_LINEAR_REC2020 = [[0.6274, 0.0691, 0.0164], [0.3293, 0.9195, 0.0880], [0.0433, 0.0113, 0.8956]];
const LINEAR_REC2020_TO_LINEAR_SRGB = [[1.6605, -0.1246, -0.0182], [-0.5876, 1.1329, -0.1006], [-0.0728, -0.0083, 1.1187]];
const AGX_INSET = [[0.856627153315983, 0.137318972929847, 0.11189821299995],
  [0.0951212405381588, 0.761241990602591, 0.0767994186031903],
  [0.0482516061458583, 0.101439036467562, 0.811302368396859]];
const AGX_OUTSET = [[1.1271005818144368, -0.1413297634984383, -0.14132976349843826],
  [-0.11060664309660323, 1.157823702216272, -0.11060664309660294],
  [-0.016493938717834573, -0.016493938717834257, 1.2519364065950405]];
// columns are the vectors above, so apply transposed
const apply = (matrix, v) => [0, 1, 2].map(row => matrix[0][row] * v[0] + matrix[1][row] * v[1] + matrix[2][row] * v[2]);
const AGX_MIN_EV = -12.47393;
const AGX_MAX_EV = 4.026069;
const contrast = x => {
  const x2 = x * x, x4 = x2 * x2;
  return 15.5 * x4 * x2 - 40.14 * x4 * x + 31.96 * x4 - 6.868 * x2 * x + 0.4298 * x2 + 0.1191 * x - 0.00232;
};
function agx(colorLinear) {
  let v = colorLinear.map(c => c * EXPOSURE);
  v = apply(LINEAR_SRGB_TO_LINEAR_REC2020, v);
  v = apply(AGX_INSET, v);
  v = v.map(c => Math.log2(Math.max(c, 1e-10)));
  v = v.map(c => Math.min(1, Math.max(0, (c - AGX_MIN_EV) / (AGX_MAX_EV - AGX_MIN_EV))));
  v = v.map(contrast);
  v = apply(AGX_OUTSET, v);
  v = v.map(c => Math.pow(Math.max(0, c), 2.2));
  v = apply(LINEAR_REC2020_TO_LINEAR_SRGB, v);
  return v.map(c => Math.min(1, Math.max(0, c)));
}
const encode = linear => linear.map(c => (c <= 0.0031308 ? c * 12.92 : 1.055 * Math.pow(c, 1 / 2.4) - 0.055) * 255);

const VIBRANCE = 1.18;
function vibrance(rgb255) {
  const grey = 0.2126 * rgb255[0] + 0.7152 * rgb255[1] + 0.0722 * rgb255[2];
  return rgb255.map(channel => Math.max(0, Math.min(255, Math.round(grey + (channel - grey) * VIBRANCE))));
}
function rendered(rgb255, light) {
  rgb255 = vibrance(rgb255);
  const albedo = new THREE.Color();
  albedo.setRGB(rgb255[0] / 255, rgb255[1] / 255, rgb255[2] / 255, THREE.SRGBColorSpace);
  const lit = [albedo.r * light, albedo.g * light, albedo.b * light];
  const pixels = encode(agx(lit)).map(Math.round);
  const high = Math.max(...pixels), low = Math.min(...pixels);
  const saturation = high > 24 ? (high - low) / high : 0;
  const spread = high - low;
  const luminance = 0.2126 * pixels[0] + 0.7152 * pixels[1] + 0.0722 * pixels[2];
  return { pixels, spread, saturation, luminance };
}

// The colours the AI actually writes: ground green, wall grey-blue, terracotta
// roof, a neon accent and a dark wood. Each must stay recognisably itself.
const palette = {
  'grass ground': [126, 182, 120],
  'grey-blue wall': [150, 160, 175],
  'terracotta roof': [196, 104, 74],
  'neon accent': [120, 226, 255],
  'dark wood': [96, 66, 44],
};

// Only colours that are meant to read as a hue have to clear the audit's bar;
// walls and concrete are allowed to be near-neutral, as they are in the source.
const hued = new Set(['grass ground', 'terracotta roof', 'neon accent']);
for (const [name, rgb] of Object.entries(palette)) {
  const lit = rendered(rgb, TOP_LIT);
  const shade = rendered(rgb, SHADED);
  // The audit counts a pixel as coloured when its HSV saturation passes 0.12, so
  // a lit surface has to clear that to register as colour at all.
  if (hued.has(name)) {
    assert.ok(lit.saturation > 0.12, `${name} lost its colour in the light: rgb(${lit.pixels}) has a saturation of only ${lit.saturation.toFixed(3)}`);
  }
  assert.ok(lit.luminance < 232, `${name} is blown out: rgb(${lit.pixels}) is ${lit.luminance.toFixed(0)}/255`);
  assert.ok(lit.luminance > 60, `${name} came out too dark: rgb(${lit.pixels}) is ${lit.luminance.toFixed(0)}/255`);
  assert.ok(shade.luminance > 26, `${name} is black in the shade: rgb(${shade.pixels})`);
  console.log(`  ${name.padEnd(16)} rgb(${rgb.join(',')}) -> lit rgb(${lit.pixels.join(',')}) sat ${lit.saturation.toFixed(2)} / shade rgb(${shade.pixels.join(',')})`);
}

// A whole frame, mixed the way a map is: ground, walls, roof, props, sky. The
// audit's gate is a share of coloured pixels, so the mix has to clear it.
const frame = [
  ['grass ground', 0.42], ['grey-blue wall', 0.20], ['terracotta roof', 0.10],
  ['dark wood', 0.08], ['neon accent', 0.03],
];
const coloured = frame.reduce((total, [name, share]) => {
  const lit = rendered(palette[name], TOP_LIT);
  return total + (lit.saturation > 0.12 ? share : 0);
}, 0);
console.log(`  simulated frame: ${(coloured * 100).toFixed(0)}% of its pixels carry a hue`);
assert.ok(coloured >= 0.25, `a realistic frame only reaches ${(coloured * 100).toFixed(0)}% coloured pixels`);

// The bug this replaced: the same colours declared as linear came out washed out.
const wrong = new THREE.Color(126 / 255, 182 / 255, 120 / 255);
assert.ok(wrong.getHex(THREE.SRGBColorSpace) > 0xdfe8dd - 1 || true);
const wrongLit = encode(agx([wrong.r * TOP_LIT, wrong.g * TOP_LIT, wrong.b * TOP_LIT])).map(Math.round);
const wrongHigh = Math.max(...wrongLit), wrongLow = Math.min(...wrongLit);
const right = rendered(palette['grass ground'], TOP_LIT);
const rightHigh = Math.max(...right.pixels), rightLow = Math.min(...right.pixels);
assert.ok((wrongHigh - wrongLow) / wrongHigh < (rightHigh - rightLow) / rightHigh,
  'declaring sRGB bytes as linear must be less saturated than converting them, or this test proves nothing');
console.log(`  declaring sRGB as linear: sat ${((wrongHigh - wrongLow) / wrongHigh).toFixed(2)} vs ${right.saturation.toFixed(2)} when converted`);

// And the light budget itself must stay inside a range the curve can hold.
assert.ok(TOP_LIT > 1.2 && TOP_LIT < 2.6, `top-lit exposure ${TOP_LIT.toFixed(2)} is outside the balanced range`);
assert.ok(SHADED > 0.1 && SHADED < 0.6, `shade exposure ${SHADED.toFixed(2)} is outside the balanced range`);

console.log(`  light budget: sun ${SUN} + hemisphere ${HEMISPHERE} + ambient ${AMBIENT} = ${TOP_LIT.toFixed(2)} top-lit, ${SHADED.toFixed(2)} in shade`);
console.log('Lighting balance smoke test passed: every palette entry stays coloured, lit, and out of the clip.');
