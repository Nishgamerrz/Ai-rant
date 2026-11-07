/**
 * Every shape a Roblox Part may be, as unit-size Three.js geometry.
 *
 * The renderer used to know three shapes - Block, Ball, Cylinder - so a roof, a
 * ramp, a sail, a kite or an arrow sign could only be faked out of thin blocks.
 * These all fit inside a 1x1x1 cube and are scaled by the Part's size, so they
 * still batch into one instanced draw call per (shape, material) pair.
 *
 * Kept in its own module so `map_features_smoke_test.mjs` can build every shape
 * with real Three.js in Node and check it is a closed, unit-size mesh - no
 * browser and no WebGL needed.
 */
import * as THREE from 'three';

/** Shapes the AI may name. The first five are real Roblox PartTypes. */
export const SHAPES = [
  'Block', 'Ball', 'Cylinder', 'Wedge', 'CornerWedge',
  'Cone', 'Pyramid', 'Prism', 'Torus', 'Ring', 'Hemisphere', 'Truss',
];

/**
 * Roblox's Cylinder lies along X, so it is turned a quarter turn here too. The
 * hand-built shapes keep their natural orientation (Wedge slopes toward +Z).
 */
export const SHAPE_ROTATIONS = {
  Cylinder: [0, 0, Math.PI / 2],
  Torus: [Math.PI / 2, 0, 0],
  Ring: [Math.PI / 2, 0, 0],
};

/** Merge simple boxes into one geometry (used for the Truss lattice). */
export function mergedBoxes(bars) {
  const positions = [];
  const normals = [];
  for (const bar of bars) {
    const box = new THREE.BoxGeometry(bar.size[0], bar.size[1], bar.size[2]).toNonIndexed();
    box.translate(bar.position[0], bar.position[1], bar.position[2]);
    positions.push(...box.attributes.position.array);
    normals.push(...box.attributes.normal.array);
    box.dispose();
  }
  const merged = new THREE.BufferGeometry();
  merged.setAttribute('position', new THREE.BufferAttribute(new Float32Array(positions), 3));
  merged.setAttribute('normal', new THREE.BufferAttribute(new Float32Array(normals), 3));
  return merged;
}

/** Build a closed mesh from vertex positions and polygon faces. */
function solid(vertices, faces) {
  const positions = [];
  const push = (index) => {
    const [x, y, z] = vertices[index];
    positions.push(x, y, z);
  };
  for (const face of faces) {
    if (face.length === 4) {
      push(face[0]); push(face[1]); push(face[2]);
      push(face[0]); push(face[2]); push(face[3]);
    } else {
      push(face[0]); push(face[1]); push(face[2]);
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.computeVertexNormals();
  return geometry;
}

const WEDGE_VERTICES = [
  [-0.5, -0.5, 0.5], [0.5, -0.5, 0.5], [0.5, -0.5, -0.5],
  [-0.5, -0.5, -0.5], [-0.5, 0.5, -0.5], [0.5, 0.5, -0.5],
];
const WEDGE_FACES = [[0, 1, 5, 4], [1, 2, 5], [0, 4, 3], [0, 3, 2, 1], [3, 4, 5, 2]];

const PRISM_VERTICES = [
  [-0.5, -0.5, 0.5], [0.5, -0.5, 0.5], [0, 0.5, 0.5],
  [-0.5, -0.5, -0.5], [0.5, -0.5, -0.5], [0, 0.5, -0.5],
];
const PRISM_FACES = [[0, 1, 2], [3, 5, 4], [0, 3, 4, 1], [1, 4, 5, 2], [0, 2, 5, 3]];

const CORNER_VERTICES = [
  [-0.5, -0.5, 0.5], [0.5, -0.5, 0.5], [0.5, -0.5, -0.5],
  [-0.5, -0.5, -0.5], [0.5, 0.5, -0.5],
];
const CORNER_FACES = [[0, 1, 2, 3], [0, 4, 1], [1, 4, 2], [2, 4, 3], [3, 4, 0]];

export function buildShapeGeometry() {
  return {
    Block: new THREE.BoxGeometry(1, 1, 1),
    Ball: new THREE.SphereGeometry(0.5, 16, 12),
    Cylinder: new THREE.CylinderGeometry(0.5, 0.5, 1, 14),
    Wedge: solid(WEDGE_VERTICES, WEDGE_FACES),
    Prism: solid(PRISM_VERTICES, PRISM_FACES),
    CornerWedge: solid(CORNER_VERTICES, CORNER_FACES),
    Cone: new THREE.ConeGeometry(0.5, 1, 18),
    Pyramid: new THREE.ConeGeometry(0.5, 1, 4),
    Torus: new THREE.TorusGeometry(0.34, 0.16, 10, 22),
    Ring: new THREE.TorusGeometry(0.42, 0.08, 8, 26),
    // A dome sits on its base plane, so it is dropped half a stud to stay centred.
    Hemisphere: new THREE.SphereGeometry(0.5, 18, 10, 0, Math.PI * 2, 0, Math.PI / 2).translate(0, -0.25, 0),
    Truss: mergedBoxes([
      // two chords, two posts, three rails and one diagonal brace
      { size: [0.12, 1, 0.12], position: [-0.44, 0, -0.44] },
      { size: [0.12, 1, 0.12], position: [-0.44, 0, 0.44] },
      { size: [0.12, 1, 0.12], position: [0.44, 0, -0.44] },
      { size: [0.12, 1, 0.12], position: [0.44, 0, 0.44] },
      { size: [1, 0.1, 0.1], position: [0, -0.44, -0.44] },
      { size: [1, 0.1, 0.1], position: [0, -0.44, 0.44] },
      { size: [1, 0.1, 0.1], position: [0, 0.44, -0.44] },
      { size: [1, 0.1, 0.1], position: [0, 0.44, 0.44] },
      { size: [0.1, 0.1, 1], position: [-0.44, 0, 0] },
      { size: [0.1, 0.1, 1], position: [0.44, 0, 0] },
      { size: [0.96, 0.09, 0.09], position: [0, 0, 0] },
    ]),
  };
}
