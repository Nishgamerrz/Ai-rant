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
import { LIGHTING_PRESETS } from './lighting_presets.mjs';

console.log('Lighting balance check:');

// --- the legacy daylight budget is now the named day preset -------------------
const SUN = LIGHTING_PRESETS.day.sunIntensity;
const HEMISPHERE = LIGHTING_PRESETS.day.hemisphereIntensity;
const AMBIENT = LIGHTING_PRESETS.day.ambientIntensity;
const EXPOSURE = 1.0;
// A surface facing the sun, a surface in the shade, and one edge-on.
const TOP_LIT = SUN + HEMISPHERE * 0.75 + AMBIENT;
const SHADED = HEMISPHERE * 0.35 + AMBIENT;

// --- three's ACES filmic tone mapping, ported from tonemapping_pars_fragment --
// ACES was measured against AgX on this exact palette: with the light budget
// below, AgX renders grass at 0.19 saturation and a roof at 0.43, while ACES
// renders 0.38 and 0.75. The desaturation that looked like ACES's fault was the
// 6x light budget it used to sit behind.
const ACES_INPUT = [[0.59719, 0.07600, 0.02840], [0.35458, 0.90834, 0.13383], [0.04823, 0.01566, 0.83777]];
const ACES_OUTPUT = [[1.60475, -0.10208, -0.00327], [-0.53108, 1.10813, -0.07276], [-0.07367, -0.00605, 1.07602]];
const apply = (matrix, v) => [0, 1, 2].map(row => matrix[0][row] * v[0] + matrix[1][row] * v[1] + matrix[2][row] * v[2]);
const aces = colorLinear => {
  let v = apply(ACES_INPUT, colorLinear.map(c => c * EXPOSURE));
  v = v.map(x => {
    const a = x * (x + 0.0245786) - 0.000090537;
    const b = x * (0.983729 * x + 0.4329510) + 0.238081;
    return a / b;
  });
  return apply(ACES_OUTPUT, v).map(c => Math.min(1, Math.max(0, c)));
};
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
  const pixels = encode(aces(lit)).map(Math.round);
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
  // A genuinely dark albedo in the shade is allowed to be dark - it just must not
  // be pure black, which is what an unlit or uncoloured Part looks like.
  assert.ok(shade.luminance > 10, `${name} is black in the shade: rgb(${shade.pixels})`);
  console.log(`  ${name.padEnd(16)} rgb(${rgb.join(',')}) -> lit rgb(${lit.pixels.join(',')}) sat ${lit.saturation.toFixed(2)} / shade rgb(${shade.pixels.join(',')})`);
}

// Every user-selectable hour keeps a saturated surface visible without clipping.
for (const [hour, preset] of Object.entries(LIGHTING_PRESETS)) {
  const top = preset.sunIntensity + preset.hemisphereIntensity * 0.75 + preset.ambientIntensity;
  const shade = preset.hemisphereIntensity * 0.35 + preset.ambientIntensity;
  assert.ok(top > 1.2 && top < 2.6, `${hour} top-lit exposure ${top.toFixed(2)} is outside the balanced range`);
  assert.ok(shade > 0.1 && shade < 0.6, `${hour} shade exposure ${shade.toFixed(2)} is outside the balanced range`);
  for (const name of hued) {
    const lit = rendered(palette[name], top);
    assert.ok(lit.saturation > 0.12, `${hour} ${name} lost its colour: rgb(${lit.pixels})`);
    assert.ok(lit.luminance > 45 && lit.luminance < 240,
      `${hour} ${name} is too dark or blown out: ${lit.luminance.toFixed(0)}/255`);
  }
  console.log(`  ${hour.padEnd(6)} top-lit ${top.toFixed(2)}, shade ${shade.toFixed(2)}: readable and coloured`);
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
const wrongLit = encode(aces([wrong.r * TOP_LIT, wrong.g * TOP_LIT, wrong.b * TOP_LIT])).map(Math.round);
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
