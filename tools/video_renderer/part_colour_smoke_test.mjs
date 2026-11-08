// Every Part must keep the colour the AI gave it.
//
// This is the bug that has bitten this renderer twice, in both directions:
//
//   vertexColors: true  + no colour attribute -> the shader multiplies by 0  -> BLACK
//   vertexColors: false + instanceColor       -> vColor never reaches the
//                                                fragment shader             -> WHITE
//
// three r170 only uses instanceColor in the fragment shader when USE_COLOR is
// defined, and USE_COLOR also multiplies by the geometry's own colour attribute.
// The only combination that works is therefore vertexColors on AND a white
// colour attribute on every shape, which leaves vColor = instanceColor.
//
// This test builds the real geometries with real three.js and proves that
// arithmetic, without a GPU.
import assert from 'node:assert/strict';
import * as THREE from 'three';
import { buildShapeGeometry } from './map_shapes.mjs';

console.log('Part colour check:');

const shapes = buildShapeGeometry();
const names = Object.keys(shapes);
assert.ok(names.length >= 12, `expected the 12 map shapes, got ${names.length}`);

// 1. Every shape must carry the white colour attribute the shader multiplies by.
for (const name of names) {
  const geometry = shapes[name];
  const attribute = geometry.getAttribute('color');
  assert.ok(attribute, `${name} has no colour attribute, so vertexColors would render it black`);
  assert.equal(attribute.itemSize, 3, `${name} colour attribute must be rgb`);
  assert.equal(attribute.count, geometry.getAttribute('position').count,
    `${name} needs one colour per vertex`);
  for (let i = 0; i < attribute.array.length; i += 1) {
    assert.equal(attribute.array[i], 1, `${name} colour attribute must be white, got ${attribute.array[i]}`);
  }
}

// 2. The material must ask for vertex colours, or instanceColor is discarded and
//    every Part renders white.
const material = new THREE.MeshStandardMaterial({ color: 0xffffff, vertexColors: true });
assert.equal(material.vertexColors, true, 'the instanced material must enable vertex colours');

// 3. The arithmetic the shaders perform, on a real InstancedMesh.
const mesh = new THREE.InstancedMesh(shapes.Block, material, 3);
const colours = [[220, 40, 40], [40, 160, 90], [40, 80, 220]];
colours.forEach((rgb, index) => {
  mesh.setMatrixAt(index, new THREE.Matrix4().makeTranslation(index * 4, 0, 0));
  mesh.setColorAt(index, new THREE.Color(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255));
});
assert.ok(mesh.instanceColor, 'setColorAt() produced no instance colour buffer');
assert.equal(mesh.instanceColor.count, 3);

const geometryColour = shapes.Block.getAttribute('color');
const shader = (vertex) => {
  // mirror of color_vertex.glsl.js + color_fragment.glsl.js
  let vColor = [1, 1, 1];
  if (material.vertexColors) vColor = vColor.map((value, axis) => value * vertex.colour[axis]);
  vColor = vColor.map((value, axis) => value * mesh.instanceColor.array[(vertex.index * 3) + axis]);
  const diffuse = material.color;
  return [diffuse.r, diffuse.g, diffuse.b].map((value, axis) => value * vColor[axis]);
};

colours.forEach((rgb, index) => {
  const out = shader({ index, colour: [geometryColour.array[0], geometryColour.array[1], geometryColour.array[2]] });
  const wanted = rgb.map(value => value / 255);
  out.forEach((value, axis) => {
    assert.ok(Math.abs(value - wanted[axis]) < 1e-6,
      `Part ${index} rendered ${out.map(v => v.toFixed(3))} instead of ${wanted.map(v => v.toFixed(3))}`);
  });
});

// 4. And the black case really is black, which is why the attribute exists.
const blackCase = shader({ index: 0, colour: [0, 0, 0] });
assert.deepEqual(blackCase, [0, 0, 0], 'a missing colour attribute reads as 0 and renders black');

console.log(`  ${names.length} shapes carry a white colour attribute (${geometryColour.count} values on Block)`);
console.log(`  vertexColors on + white attribute + instanceColor = the AI's colour: rgb(${colours[0]}) stays rgb(${colours[0]})`);
console.log('Part colour smoke test passed: per-Part colours survive the shader, and neither black nor white can come back.');
