/**
 * Keep safe map cleanup aware of the scene it is cleaning.
 *
 * The outdoor cast-lane guard used to discard every room wall and nearly every
 * piece of furniture in an interior plan: a bedroom's whole floor plan occupies
 * the same coordinates as the open-world cast lane. Indoor props are already
 * fitted and overlap-resolved by build_story_map.py, so valid room geometry must
 * survive this renderer-side audit.
 */
const GRID = 0.25;
const MAX_PART_SPAN = 70;
const CAST_MIN_Z = 4;
const CAST_MAX_Z = 54;
const CAST_HALF_WIDTH = 20;

const finiteTriple = (value) => Array.isArray(value) && value.length === 3
  && value.every((item) => Number.isFinite(Number(item)));
const snap = (value) => Math.round(Number(value) / GRID) * GRID;

export function isProtectedInteriorProp(part, interior) {
  if (!interior || typeof interior !== 'object') return false;
  // The deterministic room shell includes the backboard just outside the window.
  // Its shell flag is explicit and it is built from bounded, validated parts.
  if (part?.shell === true) return true;
  if (!finiteTriple(part?.position) || !finiteTriple(part?.size)) return false;
  const width = Number(interior.width);
  const depth = Number(interior.depth);
  const height = Number(interior.height);
  const centreZ = Number(interior.centre_z ?? 24);
  if (![width, depth, height, centreZ].every(Number.isFinite) || width <= 0 || depth <= 0 || height <= 0) {
    return false;
  }
  const [x, y, z] = part.position.map(Number);
  const [sx, sy, sz] = part.size.map((value) => Math.abs(Number(value)));
  const padding = 1.0;
  return x - sx / 2 >= -width / 2 - padding
    && x + sx / 2 <= width / 2 + padding
    && y - sy / 2 >= -padding
    && y + sy / 2 <= height + padding
    && z - sz / 2 >= centreZ - depth / 2 - padding
    && z + sz / 2 <= centreZ + depth / 2 + padding;
}

export function isCameraHazard(part, interior = null) {
  if (!finiteTriple(part?.position) || !finiteTriple(part?.size)) return true;
  const [x, y, z] = part.position.map(Number);
  const [sx, sy, sz] = part.size.map((value) => Math.abs(Number(value)));
  if (Math.max(sx, sy, sz) > MAX_PART_SPAN) return true;
  if (isProtectedInteriorProp(part, interior)) return false;
  const overlapsActorHeight = y - sy / 2 < 7 && y + sy / 2 > 2;
  return overlapsActorHeight && Math.abs(x) < CAST_HALF_WIDTH
    && z > CAST_MIN_Z - 2 && z < CAST_MAX_Z + 2;
}

/** Normalize the renderer's props while preserving floor height and room geometry. */
export function auditRenderProps(rawProps, interior = null) {
  let droppedProps = 0;
  const props = [];
  for (const raw of Array.isArray(rawProps) ? rawProps : []) {
    if (!finiteTriple(raw?.position) || !finiteTriple(raw?.size)) {
      droppedProps += 1;
      continue;
    }
    const rawSize = raw.size.map((value) => Math.abs(Number(value)));
    if (Math.max(...rawSize) > MAX_PART_SPAN) {
      droppedProps += 1;
      continue;
    }
    const size = rawSize.map((value) => Math.max(0.5, value));
    // A floor's centre is Y=0, not Y=0.5: lifting every ground-level part created
    // a raised platform, clipped feet and exposed the world behind its jagged edge.
    const position = raw.position.map(snap);
    const part = { ...raw, position, size };
    if (isCameraHazard(part, interior)) {
      droppedProps += 1;
      continue;
    }
    props.push(part);
  }
  const shell = props.filter((part) => part.shell === true);
  const roomFloor = shell.find((part) => String(part.name || '').toLowerCase() === 'room floor');
  return {
    props,
    audit: {
      alignedProps: props.length,
      droppedHazards: droppedProps,
      roomShellParts: interior ? shell.length : 0,
      roomWallParts: interior ? shell.filter((part) => /wall|door|window/i.test(String(part.name || ''))).length : 0,
      roomFurnitureParts: interior ? props.filter((part) => part.shell !== true).length : 0,
      roomFloorY: roomFloor ? roomFloor.position[1] : null,
    },
  };
}
