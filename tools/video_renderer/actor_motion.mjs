// Blocking and movement for the cast - the maths behind "the characters actually move".
//
// The shipped MP4 had characters standing on one spot while an animation played
// underneath them: the old code moved each avatar on a sine circle barely a stud
// wide, looped one walk cycle forever, and turned the body 180 degrees away from
// the way it was travelling (the avatar's front is +Z, but the yaw used
// atan2(vx, -vz)). A Roblox story short instead BLOCKS the scene: at every camera
// cut each character is somewhere new, walks there during the first moments of the
// shot, and then stands and acts while the camera holds.
//
// Everything here is deterministic and free of three.js, so it can be tested
// directly: the same run always blocks the same way.

/** The usable floor of an interior plan, or null for an open world. */
export function roomBoundsFrom(interior) {
  if (!interior || typeof interior !== 'object') return null;
  const width = Number(interior.width);
  const depth = Number(interior.depth);
  const height = Number(interior.height);
  const centre = Number(interior.centre_z ?? 24);
  if (!Number.isFinite(width) || !Number.isFinite(depth) || width <= 0 || depth <= 0) return null;
  const inset = 1.9;
  return {
    minX: -width / 2 + inset,
    maxX: width / 2 - inset,
    minZ: centre - depth / 2 + inset,
    maxZ: centre + depth / 2 - inset,
    minY: 3.2,
    maxY: (Number.isFinite(height) ? height : 12) - 1.4,
  };
}

export function clampStage(x, z, bounds) {
  if (!bounds) return [Math.max(-16, Math.min(16, x)), Math.max(8, Math.min(48, z))];
  return [Math.max(bounds.minX, Math.min(bounds.maxX, x)),
    Math.max(bounds.minZ, Math.min(bounds.maxZ, z))];
}

/** Yaw that makes an avatar with this front direction LOOK along (dx, dz). */
export function yawToward(front, dx, dz, fallback = 0) {
  if (Math.abs(dx) < 1e-4 && Math.abs(dz) < 1e-4) return fallback;
  const sign = Number(front?.[2] ?? 1) >= 0 ? 1 : -1;
  return Math.atan2(sign * dx, sign * dz);
}

/**
 * Where each actor stands while each camera shot is on screen.
 * `actors` needs baseX/baseZ (their mark from the plan), lead and phase.
 */
export function planMarks({ actors, shots, drift = 2.0, bounds = null }) {
  if (!Array.isArray(actors) || !actors.length || !Array.isArray(shots) || !shots.length) return [];
  const marks = actors.map((actor) => {
    const list = [];
    for (let index = 0; index < shots.length; index += 1) {
      if (index === 0) { list.push([Number(actor.baseX) || 0, Number(actor.baseZ) || 0]); continue; }
      const angle = index * 2.399963 + (actor.lead ? 0 : Math.PI) + (Number(actor.phase) || 0) * 0.35;
      const drifted = clampStage((Number(actor.baseX) || 0) + Math.cos(angle) * drift,
        (Number(actor.baseZ) || 0) + Math.sin(angle) * drift * 0.7, bounds);
      list.push(drifted);
    }
    return list;
  });
  // No two actors may share a mark: one would stand inside the other.
  for (let index = 0; index < shots.length; index += 1) {
    for (let a = 0; a < actors.length; a += 1) {
      for (let b = a + 1; b < actors.length; b += 1) {
        let [ax, az] = marks[a][index];
        let [bx, bz] = marks[b][index];
        const gap = Math.hypot(bx - ax, bz - az);
        if (gap >= 2.6) continue;
        const push = (2.6 - gap) / 2 + 0.1;
        const dx = gap > 1e-3 ? (bx - ax) / gap : 1;
        const dz = gap > 1e-3 ? (bz - az) / gap : 0;
        [ax, az] = clampStage(ax - dx * push, az - dz * push, bounds);
        [bx, bz] = clampStage(bx + dx * push, bz + dz * push, bounds);
        marks[a][index] = [ax, az];
        marks[b][index] = [bx, bz];
      }
    }
  }
  return actors.map((actor, index) => {
    const list = marks[index];
    // Distance walked to REACH each mark (walkedBefore[k] = ground covered by the
    // time the actor stands on mark k), so the walk cycle advances monotonically.
    let travelled = 0;
    const walkedBefore = [];
    for (let step = 0; step < list.length; step += 1) {
      if (step > 0) {
        travelled += Math.hypot(list[step][0] - list[step - 1][0], list[step][1] - list[step - 1][1]);
      }
      walkedBefore.push(travelled);
    }
    return { marks: list, walkedBefore, travelled };
  });
}

export function shotIndexAt(shots, t) {
  let index = 0;
  for (let shot = 0; shot < shots.length; shot += 1) {
    if (t >= shots[shot].time) index = shot;
    else break;
  }
  return index;
}

export function smoothStep(value) {
  const clamped = Math.max(0, Math.min(1, value));
  return clamped * clamped * (3 - 2 * clamped);
}

/**
 * One actor's pose at time t: position, whether it is walking, the distance it has
 * walked (which drives the walk cycle, so feet never skate), and the yaw it faces.
 */
export function poseAt({ marks, walkedBefore = [], shots, duration, t, front = [0, 0, 1],
  partnerMarks = null, lastYaw = null, walkSpeed = 3.2 }) {
  if (!marks?.length || !shots?.length) {
    const only = marks?.[0] || [0, 0];
    return { x: only[0], z: only[1], moving: 0, walked: 0, yaw: lastYaw ?? 0, shot: 0 };
  }
  const index = Math.min(shotIndexAt(shots, t), marks.length - 1);
  const shotStart = shots[index]?.time ?? 0;
  const shotEnd = index + 1 < shots.length ? shots[index + 1].time : (duration ?? shotStart + 5);
  const from = marks[Math.max(0, index - 1)];
  const to = marks[index];
  const distance = Math.hypot(to[0] - from[0], to[1] - from[1]);
  const travel = Math.min(Math.max(distance / walkSpeed, 0.55), Math.max(0.55, (shotEnd - shotStart) * 0.5));
  const raw = index === 0 || distance < 0.3 ? 0 : Math.max(0, Math.min(1, (t - shotStart) / travel));
  const eased = smoothStep(raw);
  const x = from[0] + (to[0] - from[0]) * eased;
  const z = from[1] + (to[1] - from[1]) * eased;
  // Amplitude fades in and out: a planted stand never runs a walk cycle.
  const moving = index === 0 || distance < 0.3 ? 0 : Math.min(1, Math.min(raw, 1 - raw) * 5);
  // Ground covered by the start of this shot, plus how far into the walk we are.
  const walked = (walkedBefore[Math.max(0, index - 1)] ?? 0) + distance * eased;

  let yaw;
  if (moving > 0.25) {
    yaw = yawToward(front, to[0] - from[0], to[1] - from[1], lastYaw ?? 0);
  } else if (partnerMarks?.length) {
    const partner = partnerMarks[Math.min(index, partnerMarks.length - 1)];
    yaw = yawToward(front, partner[0] - to[0], partner[1] - to[1], lastYaw ?? 0);
  } else {
    yaw = yawToward(front, 0, -1, lastYaw ?? 0);   // alone: face the room / camera side
  }
  const previous = lastYaw ?? yaw;
  const delta = ((yaw - previous + Math.PI) % (Math.PI * 2) + Math.PI * 2) % (Math.PI * 2) - Math.PI;
  // Turn, do not snap: an instant 180 reads as a broken model.
  const turnBlend = Math.max(0, Math.min(1, (t - shotStart) / 0.45));
  return { x, z, moving, walked, yaw: previous + delta * turnBlend, shot: index };
}
