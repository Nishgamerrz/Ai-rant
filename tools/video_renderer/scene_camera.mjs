function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function inside(position, box, padding) {
  const p = box.position;
  const s = box.size;
  return Math.abs(position[0] - p[0]) <= s[0] / 2 + padding
    && Math.abs(position[1] - p[1]) <= s[1] / 2 + padding
    && Math.abs(position[2] - p[2]) <= s[2] / 2 + padding;
}

function segmentHitsBox(start, end, box, padding = 0.35) {
  let entry = 0;
  let exit = 1;
  for (let axis = 0; axis < 3; axis += 1) {
    const low = box.position[axis] - box.size[axis] / 2 - padding;
    const high = box.position[axis] + box.size[axis] / 2 + padding;
    const delta = end[axis] - start[axis];
    if (Math.abs(delta) < 1e-8) {
      if (start[axis] < low || start[axis] > high) return false;
      continue;
    }
    const a = (low - start[axis]) / delta;
    const b = (high - start[axis]) / delta;
    entry = Math.max(entry, Math.min(a, b));
    exit = Math.min(exit, Math.max(a, b));
    if (entry > exit) return false;
  }
  return exit > 0.035 && entry < 0.965;
}

const MIN_CAMERA_HEIGHT = 3.4;
const SOLID_PADDING = 2.6;

function clearView(target, position, blockers) {
  // Keep a generous safety margin: a camera merely grazing a wall used to fill
  // the frame with an unexplained dark slab instead of the character.
  if (position[1] < MIN_CAMERA_HEIGHT) return false;
  if (blockers.some((box) => inside(position, box, SOLID_PADDING))) return false;
  return !blockers.some((box) => segmentHitsBox(target, position, box, 0.9));
}

/** Keep the camera outside map geometry and preserve an unobstructed view of its target. */
export function chooseSafeCamera(target, desired, blockers, minDistance = 14, maxDistance = 42) {
  const raw = desired.map((value, axis) => value - target[axis]);
  const rawDistance = Math.hypot(...raw) || 1;
  const distance = clamp(rawDistance, minDistance, maxDistance);
  const yaw = Math.atan2(raw[2], raw[0]);
  const pitch = Math.asin(clamp(raw[1] / rawDistance, -0.65, 0.78));
  const makeCandidate = (angle, elevation, radius) => [
    target[0] + Math.cos(elevation) * Math.cos(angle) * radius,
    target[1] + Math.sin(elevation) * radius,
    target[2] + Math.cos(elevation) * Math.sin(angle) * radius,
  ];

  const initial = makeCandidate(yaw, pitch, distance);
  if (clearView(target, initial, blockers)) return initial;

  let best = null;
  let bestCost = Infinity;
  const angles = [0, 35, -35, 70, -70, 105, -105, 140, -140, 180];
  const elevations = [pitch, 0.28, 0.48, 0.66];
  const radii = [distance, clamp(distance * 0.82, minDistance, maxDistance),
    clamp(distance * 1.12, minDistance, maxDistance), minDistance];
  for (const radius of radii) {
    for (const elevation of elevations) {
      for (const degrees of angles) {
        const candidate = makeCandidate(yaw + degrees * Math.PI / 180, elevation, radius);
        if (!clearView(target, candidate, blockers)) continue;
        const cost = Math.hypot(candidate[0] - desired[0], candidate[1] - desired[1], candidate[2] - desired[2]);
        if (cost < bestCost) {
          best = candidate;
          bestCost = cost;
        }
      }
    }
    if (best) break;
  }
  if (best) return best;

  // The map can contain a closed/tall cluster; rise above it rather than place
  // the camera inside a wall or leave the avatar completely occluded.
  const roofline = blockers.reduce((max, box) => Math.max(max, box.position[1] + box.size[1] / 2), 8);
  return [target[0] + minDistance * 0.72, Math.max(target[1] + 14, roofline + 8), target[2] + minDistance * 0.72];
}

/**
 * Close-up "face cam" for story shorts: frame the head from a short, safe
 * distance. Roblox story shorts cut to the character's face for the emotional
 * beat, so the camera must get within a couple of studs without clipping into
 * the head, a wall, or the character's own shoulders.
 */
export function chooseFaceCamera(target, desired, blockers, distance = 2.5) {
  const raw = desired.map((value, axis) => value - target[axis]);
  const rawDistance = Math.hypot(...raw) || 1;
  const yaw = Math.atan2(raw[2], raw[0]);
  const pitch = Math.asin(clamp(raw[1] / rawDistance, -0.18, 0.42));
  const candidate = (angle, elevation, radius) => [
    target[0] + Math.cos(elevation) * Math.cos(angle) * radius,
    target[1] + Math.sin(elevation) * radius,
    target[2] + Math.cos(elevation) * Math.sin(angle) * radius,
  ];
  const allowed = (position) => {
    if (position[1] < target[1] - 1.2) return false;
    if (blockers.some((box) => inside(position, box, 0.75))) return false;
    return !blockers.some((box) => segmentHitsBox(target, position, box, 0.35));
  };
  const radii = [distance, distance * 1.35, distance * 0.82, distance * 1.9];
  for (const radius of radii) {
    for (const elevation of [pitch, 0.02, -0.05, 0.16, 0.3]) {
      for (const degrees of [0, 12, -12, 25, -25, 40, -40, 58, -58, 78, -78, 100, -100, 130, -130, 160, 180]) {
        const point = candidate(yaw + degrees * Math.PI / 180, elevation, radius);
        if (allowed(point)) return point;
      }
    }
  }
  // Never leave the face unreadable: fall back to a clean medium shot.
  return chooseSafeCamera(target, desired, blockers, 7, 16);
}

export { segmentHitsBox };
