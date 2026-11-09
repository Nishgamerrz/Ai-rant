function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

/**
 * A Roblox avatar is not soft skin: it is a small set of RIGID parts (head, torso,
 * upper arm, forearm, hand, thigh, shin, foot) that rotate around their joints.
 * The OBJ Roblox Studio exports already carries exactly those parts as named
 * groups (Handle1, Rig1...Rig15), so their bounding boxes say what each one is:
 * the head is the top part that straddles the centre line, arms are the parts far
 * out to one side, legs are the narrow parts below the hips, and the foot is the
 * lowest leg part with the longest Z.
 *
 * Every part is then bound 100% to ONE bone. A part that follows one joint is a
 * rigid transform of itself, so no triangle can ever stretch, tear or "explode" -
 * the failure that made the shipped MP4 look like an exploding character. The old
 * per-triangle smoothing pass is kept only as the fallback for models that have no
 * separate parts (single-mesh GLB/FBX/STL avatars).
 */
const PART_LIMIT = 512;

function partBoxes(THREE, model) {
  model.updateMatrixWorld(true);
  const entries = [];
  model.traverse((object) => {
    if (!object.isMesh || !object.geometry?.getAttribute?.('position')) return;
    const box = new THREE.Box3().setFromObject(object);
    if (!Number.isFinite(box.min.x) || !Number.isFinite(box.max.x)) return;
    entries.push({ object, box });
  });
  return entries.slice(0, PART_LIMIT);
}

function boxCentre(box) {
  return [(box.min.x + box.max.x) / 2, (box.min.y + box.max.y) / 2, (box.min.z + box.max.z) / 2];
}

/**
 * Name every rigid part of an avatar from its own geometry.
 * Returns { parts, height, centreX, confident, joints }.
 */
export function classifyAvatarParts(THREE, model) {
  const entries = partBoxes(THREE, model);
  const result = { parts: [], height: 0, centreX: 0, confident: false, joints: null };
  if (!entries.length) return result;
  const total = new THREE.Box3();
  for (const entry of entries) total.union(entry.box);
  const height = total.max.y - total.min.y;
  const width = total.max.x - total.min.x;
  result.height = height;
  result.centreX = (total.min.x + total.max.x) / 2;
  if (!(height > 0.1) || !(width > 0.05)) return result;
  const centreX = result.centreX;
  const bottom = total.min.y;
  const straddles = (box) => (box.min.x - centreX) < -0.08 * width && (box.max.x - centreX) > 0.08 * width;

  // Torso parts straddle the centre line; their widest half-extent tells an arm
  // (far out to the side) from a leg (narrow, under the hips).
  const bodyParts = entries.filter((entry) => straddles(entry.box));
  const torsoHalf = bodyParts.length
    ? Math.max(...bodyParts.map((entry) => Math.max(
      Math.abs(entry.box.max.x - centreX), Math.abs(entry.box.min.x - centreX))))
    : width * 0.25;
  const armReach = Math.max(torsoHalf * 0.9, width * 0.12);

  const parts = entries.map((entry) => {
    const centre = boxCentre(entry.box);
    return {
      object: entry.object,
      box: entry.box,
      centre,
      localX: centre[0] - centreX,
      side: centre[0] < centreX ? 'Left' : 'Right',
      spanY: entry.box.max.y - entry.box.min.y,
      spanZ: entry.box.max.z - entry.box.min.z,
      bone: null,
    };
  });

  // Arms: far out to one side, above the hips.
  const hipLine = bottom + height * 0.34;
  const limbs = parts.filter((part) => !straddles(part.box));
  const armParts = limbs.filter((part) => Math.abs(part.localX) > armReach && part.centre[1] > hipLine);
  const legParts = limbs.filter((part) => !armParts.includes(part));

  // Legs: one leg is the lowest group of parts on each side.
  for (const side of ['Left', 'Right']) {
    const sideLegs = legParts.filter((part) => part.side === side)
      .sort((a, b) => b.centre[1] - a.centre[1]);
    if (!sideLegs.length) continue;
    if (sideLegs.length === 1) { sideLegs[0].bone = `${side}UpperLeg`; continue; }
    sideLegs[0].bone = `${side}UpperLeg`;
    sideLegs[sideLegs.length - 1].bone = `${side}Foot`;
    for (let index = 1; index < sideLegs.length - 1; index += 1) sideLegs[index].bone = `${side}LowerLeg`;
  }
  // Arms: highest part is the upper arm, lowest is the hand.
  for (const side of ['Left', 'Right']) {
    const sideArms = armParts.filter((part) => part.side === side)
      .sort((a, b) => b.centre[1] - a.centre[1]);
    if (!sideArms.length) continue;
    if (sideArms.length === 1) { sideArms[0].bone = `${side}UpperArm`; continue; }
    sideArms[0].bone = `${side}UpperArm`;
    sideArms[sideArms.length - 1].bone = `${side}Hand`;
    for (let index = 1; index < sideArms.length - 1; index += 1) sideArms[index].bone = `${side}LowerArm`;
  }

  // Body parts: the CHEST is the widest piece across the shoulders (but never a
  // hat sitting in the top of the silhouette), the HEAD is the lowest piece that
  // starts above the chest, and whatever is worn above the head's own bottom is
  // worn ON the head. Run #110 shipped a head bound to the chest, which is what
  // dragged the whole face down with the torso.
  const body = parts.filter((part) => straddles(part.box));
  const widthOf = (part) => part.box.max.x - part.box.min.x;
  const chestCandidates = body.filter((part) => part.centre[1] < bottom + height * 0.78);
  const chestPart = chestCandidates.length
    ? chestCandidates.reduce((best, part) => (widthOf(part) > widthOf(best) ? part : best))
    : null;
  if (chestPart) chestPart.bone = 'Chest';
  const aboveChest = (part) => (chestPart ? part.box.min.y >= chestPart.box.max.y - height * 0.03 : false);
  const headCandidates = body.filter((part) => part !== chestPart && aboveChest(part))
    .sort((a, b) => a.box.min.y - b.box.min.y);
  const headPartChosen = headCandidates.length
    ? headCandidates[0]
    : body.filter((part) => part !== chestPart).sort((a, b) => b.centre[1] - a.centre[1])[0] || null;
  if (headPartChosen) headPartChosen.bone = 'Head';
  if (headPartChosen) {
    for (const part of body) {
      if (part === headPartChosen || part === chestPart || part.bone) continue;
      if (part.box.min.y >= headPartChosen.box.min.y - height * 0.02) part.bone = 'Head';
    }
  }
  const torsoParts = body.filter((part) => !part.bone).sort((a, b) => b.centre[1] - a.centre[1]);
  torsoParts.forEach((part, index) => {
    part.bone = index === torsoParts.length - 1 || torsoParts.length === 1 ? 'Hips'
      : (torsoParts.length >= 3 && index === 0 ? 'Spine' : 'Spine');
  });
  // Anything still unnamed (an accessory floating beside the body) follows the chest.
  for (const part of parts) if (!part.bone) part.bone = 'Chest';

  const byBone = (bone) => parts.filter((part) => part.bone === bone);
  const maxY = (bone, fallback) => {
    const list = byBone(bone);
    return list.length ? Math.max(...list.map((part) => part.box.max.y)) : fallback;
  };
  const minY = (bone, fallback) => {
    const list = byBone(bone);
    return list.length ? Math.min(...list.map((part) => part.box.min.y)) : fallback;
  };
  const meanX = (bone, fallback) => {
    const list = byBone(bone);
    return list.length ? list.reduce((sum, part) => sum + part.centre[0], 0) / list.length : fallback;
  };
  const centreZ = (parts ? boxCentre(total)[2] : 0);

  const hips = byBone('Hips')[0] || byBone('Spine')[0] || null;
  const chest = byBone('Chest')[0] || null;
  const headPart = byBone('Head')[0] || null;
  const hipY = hips ? hips.centre[1] : bottom + height * 0.46;
  const joints = {
    root: [centreX, bottom, centreZ],
    hips: [centreX, hipY, centreZ],
    spine: [centreX, chest ? Math.min(chest.box.min.y, hipY + height * 0.06) : hipY + height * 0.14, centreZ],
    chest: [centreX, chest ? chest.centre[1] : hipY + height * 0.26, centreZ],
    neck: [centreX, headPart ? headPart.box.min.y - height * 0.05 : bottom + height * 0.72, centreZ],
    head: [centreX, headPart ? headPart.box.min.y : bottom + height * 0.76, centreZ],
  };
  // Capitals too: the rig builder names bones 'Head', 'Hips'..., and a missing key
  // silently put the head joint at the origin (0,0,0) once.
  joints.Root = joints.root;
  joints.Hips = joints.hips;
  joints.Spine = joints.spine;
  joints.Chest = joints.chest;
  joints.Neck = joints.neck;
  joints.Head = joints.head;
  for (const side of ['Left', 'Right']) {
    const sign = side === 'Left' ? -1 : 1;
    const upperArm = byBone(`${side}UpperArm`);
    const lowerArm = byBone(`${side}LowerArm`);
    const hand = byBone(`${side}Hand`);
    const upperLeg = byBone(`${side}UpperLeg`);
    const lowerLeg = byBone(`${side}LowerLeg`);
    const foot = byBone(`${side}Foot`);
    joints[`${side}UpperArm`] = [
      upperArm.length ? Math.min(...upperArm.map((part) => Math.abs(part.box.max.x - centreX)), Math.abs(centreX)) * sign + centreX : centreX + sign * height * 0.14,
      upperArm.length ? Math.max(...upperArm.map((part) => part.box.max.y)) - height * 0.04 : bottom + height * 0.68,
      centreZ,
    ];
    joints[`${side}LowerArm`] = [
      meanX(`${side}LowerArm`, centreX + sign * height * 0.16),
      lowerArm.length ? Math.max(...lowerArm.map((part) => part.box.max.y)) : bottom + height * 0.5,
      centreZ,
    ];
    joints[`${side}Hand`] = [
      meanX(`${side}Hand`, centreX + sign * height * 0.17),
      hand.length ? Math.max(...hand.map((part) => part.box.max.y)) : bottom + height * 0.4,
      centreZ,
    ];
    joints[`${side}UpperLeg`] = [
      meanX(`${side}UpperLeg`, centreX + sign * height * 0.05),
      upperLeg.length ? Math.max(...upperLeg.map((part) => part.box.max.y)) : hipY,
      centreZ,
    ];
    joints[`${side}LowerLeg`] = [
      meanX(`${side}LowerLeg`, centreX + sign * height * 0.05),
      lowerLeg.length ? Math.max(...lowerLeg.map((part) => part.box.max.y)) : bottom + height * 0.22,
      centreZ,
    ];
    joints[`${side}Foot`] = [
      meanX(`${side}Foot`, centreX + sign * height * 0.05),
      foot.length ? Math.max(...foot.map((part) => part.box.max.y)) : bottom + height * 0.08,
      centreZ,
    ];
  }

  result.parts = parts;
  result.joints = joints;
  // Confident only when the avatar really is built from separate body parts.
  const needed = ['Head', 'Chest', 'LeftUpperArm', 'RightUpperArm', 'LeftUpperLeg', 'RightUpperLeg'];
  result.confident = parts.length >= 6 && needed.every((bone) => byBone(bone).length);
  return result;
}

/**
 * Build the rigid, part-aware rig. Each OBJ group is one bone, exactly like an
 * R15 avatar, so a part can never deform: it can only rotate around its joint.
 */
export function buildPartRig(THREE, model, classified) {
  const rigRoot = new THREE.Group();
  rigRoot.name = 'RigidR15Rig';
  const bones = [];
  const byName = {};
  const joints = classified.joints;
  const make = (name, parent, position) => {
    const bone = new THREE.Bone();
    bone.name = name;
    const base = joints[name] || joints[name.toLowerCase()] || [0, 0, 0];
    const origin = parent ? (joints[parent.name] || joints[parent.name.toLowerCase()] || [0, 0, 0]) : [0, 0, 0];
    bone.position.set(base[0] - origin[0], base[1] - origin[1], base[2] - origin[2]);
    parent ? parent.add(bone) : rigRoot.add(bone);
    bones.push(bone);
    byName[name] = bone;
    return bone;
  };
  const root = make('Root', null, joints.root);
  const hips = make('Hips', root);
  const spine = make('Spine', hips);
  const chest = make('Chest', spine);
  const neck = make('Neck', chest);
  make('Head', neck);
  for (const side of ['Left', 'Right']) {
    const upperArm = make(`${side}UpperArm`, chest);
    const lowerArm = make(`${side}LowerArm`, upperArm);
    make(`${side}Hand`, lowerArm);
    const upperLeg = make(`${side}UpperLeg`, hips);
    const lowerLeg = make(`${side}LowerLeg`, upperLeg);
    make(`${side}Foot`, lowerLeg);
  }

  const boneIndices = new Map(bones.map((bone, index) => [bone.name, index]));
  const meshes = [];
  for (const part of classified.parts) {
    const object = part.object;
    let geometry = object.geometry.clone();
    geometry.applyMatrix4(object.matrixWorld);
    if (geometry.getIndex()) geometry = geometry.toNonIndexed();
    const count = geometry.getAttribute('position').count;
    const index = boneIndices.get(part.bone) ?? boneIndices.get('Chest') ?? 0;
    const indices = new Uint16Array(count * 4);
    const weights = new Float32Array(count * 4);
    for (let vertex = 0; vertex < count; vertex += 1) {
      indices[vertex * 4] = index;
      weights[vertex * 4] = 1;
    }
    geometry.setAttribute('skinIndex', new THREE.Uint16BufferAttribute(indices, 4));
    geometry.setAttribute('skinWeight', new THREE.Float32BufferAttribute(weights, 4));
    geometry.computeBoundingBox();
    geometry.computeBoundingSphere();
    const skinned = new THREE.SkinnedMesh(geometry, object.material);
    skinned.name = object.name || part.bone;
    skinned.castShadow = true;
    skinned.receiveShadow = true;
    skinned.frustumCulled = false;
    const materials = Array.isArray(skinned.material) ? skinned.material : [skinned.material];
    for (const material of materials) {
      if (!material) continue;
      material.side = THREE.DoubleSide;
      material.needsUpdate = true;
    }
    rigRoot.add(skinned);
    meshes.push(skinned);
  }
  rigRoot.updateMatrixWorld(true);
  const skeleton = new THREE.Skeleton(bones);
  for (const mesh of meshes) mesh.bind(skeleton);
  rigRoot.updateMatrixWorld(true);
  const rig = {
    root: rigRoot, bones: byName, meshCount: meshes.length, skeleton, meshes,
    height: classified.height, mode: 'rigid-parts', joints,
    boneOfMesh: meshes.map((mesh) => mesh.name),
    partBones: classified.parts.map((part) => [part.object.name || part.bone, part.bone]),
  };
  rig.restProfile = recordRestProfile(THREE, rig);
  return rig;
}

/**
 * Remember, for every vertex, how far it sits from its own part's centre in the
 * bind pose. A rigid part keeps that distance exactly; if any vertex drifts, the
 * part is being stretched, which is the bug this file exists to prevent.
 */
export function recordRestProfile(THREE, rig) {
  const profile = [];
  for (const mesh of rig.meshes) {
    const position = mesh.geometry.getAttribute('position');
    const centre = new THREE.Vector3();
    const step = Math.max(1, Math.floor(position.count / 300));
    let counted = 0;
    for (let vertex = 0; vertex < position.count; vertex += step) {
      centre.add(new THREE.Vector3(position.getX(vertex), position.getY(vertex), position.getZ(vertex)));
      counted += 1;
    }
    if (counted) centre.multiplyScalar(1 / counted);
    const distances = [];
    for (let vertex = 0; vertex < position.count; vertex += step) {
      distances.push(new THREE.Vector3(position.getX(vertex), position.getY(vertex), position.getZ(vertex))
        .distanceTo(centre));
    }
    profile.push({ mesh, centre, distances, step });
  }
  return profile;
}

/**
 * Measure how far the CURRENT pose deforms each part: 0 means perfectly rigid.
 * Returns { maxStretch, worstPart, samples } where maxStretch is the largest
 * relative change of a vertex's distance from its part centre.
 */
export function measureRigStretch(THREE, rig) {
  const profile = rig.restProfile;
  if (!profile) return { maxStretch: 0, worstPart: '', samples: 0 };
  let maxStretch = 0;
  let worstPart = '';
  let samples = 0;
  for (const entry of profile) {
    const mesh = entry.mesh;
    const position = mesh.geometry.getAttribute('position');
    const posed = [];
    const centre = new THREE.Vector3();
    for (let vertex = 0; vertex < position.count; vertex += entry.step) {
      const point = mesh.getVertexPosition(vertex, new THREE.Vector3());
      posed.push(point);
      centre.add(point);
    }
    if (!posed.length) continue;
    centre.multiplyScalar(1 / posed.length);
    for (let index = 0; index < posed.length; index += 1) {
      const rest = entry.distances[index] ?? 0;
      if (rest < 1e-6) continue;
      const stretch = Math.abs(posed[index].distanceTo(centre) - rest) / rest;
      samples += 1;
      if (stretch > maxStretch) {
        maxStretch = stretch;
        worstPart = mesh.name || mesh.parent?.name || 'part';
      }
    }
  }
  return { maxStretch, worstPart, samples };
}

/**
 * The rig every avatar uses: rigid parts when the model is built from separate
 * body parts (a Roblox OBJ always is), the older region rig only for a single
 * fused mesh (GLB/FBX/STL), where per-part rigidity is not available.
 */
export function buildAvatarRig(THREE, model) {
  const classified = classifyAvatarParts(THREE, model);
  if (classified.confident) {
    try {
      const rig = buildPartRig(THREE, model, classified);
      rig.height = classified.height;
      return rig;
    } catch (error) {
      console.warn('Rigid part rig failed, falling back to the region rig:', error.message);
    }
  }
  return buildRegionRig(THREE, model);
}

/**
 * Build an approximate R15-style skeleton and skin weights for an authentic,
 * unrigged Roblox OBJ. All mesh transforms are baked into the avatar-root space
 * first, so the same rig can drive every OBJ material group/accessory.
 */
export function buildRegionRig(THREE, model) {
  model.updateMatrixWorld(true);
  const bounds = new THREE.Box3().setFromObject(model);
  const size = bounds.getSize(new THREE.Vector3());
  const height = size.y;
  if (!Number.isFinite(height) || height < 0.1) throw new Error('Avatar OBJ has invalid bounds for automatic rigging.');

  const rigRoot = new THREE.Group();
  rigRoot.name = 'AutoR15Rig';
  const bones = [];
  const byName = {};
  const makeBone = (name, parent, position) => {
    const bone = new THREE.Bone();
    bone.name = name;
    bone.position.set(position[0], position[1], position[2]);
    parent.add(bone);
    bones.push(bone);
    byName[name] = bone;
    return bone;
  };

  const torsoRoot = makeBone('Root', rigRoot, [0, 0, 0]);
  const pelvisY = height * 0.44;
  const hips = makeBone('Hips', torsoRoot, [0, pelvisY, 0]);
  const spine = makeBone('Spine', hips, [0, height * 0.12, 0]);
  const chest = makeBone('Chest', spine, [0, height * 0.10, 0]);
  const neck = makeBone('Neck', chest, [0, height * 0.08, 0]);
  makeBone('Head', neck, [0, height * 0.06, 0]);

  const shoulderX = clamp(size.x * 0.20, height * 0.07, height * 0.15);
  const armUpperLength = height * 0.14;
  const armLowerLength = height * 0.13;
  const hipX = clamp(size.x * 0.09, height * 0.025, height * 0.075);
  const legUpperLength = height * 0.22;
  const legLowerLength = height * 0.20;
  for (const [side, sign] of [['Left', -1], ['Right', 1]]) {
    const shoulder = makeBone(`${side}UpperArm`, chest, [sign * shoulderX, height * 0.04, 0]);
    makeBone(`${side}LowerArm`, shoulder,
      [sign * armUpperLength * 0.34, -armUpperLength * 0.66, 0]);
    makeBone(`${side}Hand`, byName[`${side}LowerArm`],
      [sign * armLowerLength * 0.12, -armLowerLength * 0.82, 0]);

    const upperLeg = makeBone(`${side}UpperLeg`, hips, [sign * hipX, -height * 0.015, 0]);
    const lowerLeg = makeBone(`${side}LowerLeg`, upperLeg, [0, -legUpperLength * 0.53, 0]);
    makeBone(`${side}Foot`, lowerLeg, [0, -legLowerLength * 0.88, height * 0.025]);
  }

  rigRoot.updateMatrixWorld(true);
  const bonePositions = new Map(bones.map((bone) => {
    const world = bone.getWorldPosition(new THREE.Vector3());
    return [bone.name, [world.x, world.y, world.z]];
  }));
  const boneIndices = new Map(bones.map((bone, index) => [bone.name, index]));
  const centerX = (bounds.min.x + bounds.max.x) / 2;
  const centerY = bounds.min.y;

  // Bone regions. A vertex belongs to a region of the body chosen by height and
  // side, which is how a Roblox avatar is actually built: the upper arm is a solid
  // part, the forearm is another solid part, and they meet at the elbow.
  //
  // Distance to a bone was tried first and does not work: on a limb, every point
  // is nearly the same distance from two consecutive bones, so most of the mesh
  // ended up blended and the limb bent like rubber. A region has an exact owner,
  // and only the few centimetres either side of a region border blend into the
  // neighbouring bone that is jointed to it.
  const fractionY = (value) => (value - centerY) / height;
  const chains = {
    body: [
      { bone: 'Head', low: 0.76, high: 2 },
      { bone: 'Neck', low: 0.70, high: 0.76 },
      { bone: 'Chest', low: 0.56, high: 0.70 },
      { bone: 'Spine', low: 0.44, high: 0.56 },
      { bone: 'Hips', low: -2, high: 0.44 },
    ],
    arm: [
      { bone: 'UpperArm', low: 0.60, high: 2 },
      { bone: 'LowerArm', low: 0.44, high: 0.60 },
      { bone: 'Hand', low: -2, high: 0.44 },
    ],
    leg: [
      { bone: 'UpperLeg', low: 0.26, high: 2 },
      { bone: 'LowerLeg', low: 0.10, high: 0.26 },
      { bone: 'Foot', low: -2, high: 0.10 },
    ],
  };
  // Where the legs begin, measured from the hips rather than from the full width of
  // the avatar: including the arms made this boundary land in the middle of a shoe,
  // which split the foot between the Hips and the Foot bone and tore it by 1144%.
  const legThreshold = Math.max(0.04, Math.min(shoulderX, hipX) * 0.35);

  function armReachAt(fraction) {
    // A hand hangs as low as a knee, so it is separated from the legs by REACH:
    // below the hip line a limb is an arm only if it is further out than any leg
    // can be.
    return fraction < 0.45 ? Math.max(shoulderX * 1.2, height * 0.16) : shoulderX * 0.62;
  }

  function chainFor(x, y) {
    const localX = x - centerX;
    const absX = Math.abs(localX);
    const fraction = fractionY(y);
    const side = localX < 0 ? 'Left' : 'Right';
    const reach = armReachAt(fraction);
    // Arms first: far out from the body, between a hanging hand and the head.
    if (fraction > 0.24 && fraction < 0.76 && absX > reach) {
      return { name: 'arm', side, regions: chains.arm, fraction };
    }
    // Legs: below the hip line, away from the centre line, and never as far out as
    // an arm. Everything else is the body, which keeps a hat on the head and a
    // hanging hand off the thigh.
    if (fraction < 0.42 && absX > legThreshold && absX <= reach) {
      return { name: 'leg', side, regions: chains.leg, fraction };
    }
    return { name: 'body', side, regions: chains.body, fraction };
  }

  function boneFor(x, y) {
    const chain = chainFor(x, y);
    const region = chain.regions.find((item) => chain.fraction >= item.low && chain.fraction <= item.high)
      || chain.regions[chain.regions.length - 1];
    const name = chain.name === 'body' ? region.bone : `${chain.side}${region.bone}`;
    return { chain, region, name };
  }

  // A vertex inside `blendBand` of a region border eases into the neighbouring
  // region's bone, and only into that one: both are always jointed together, so a
  // vertex is never dragged between unrelated limbs.
  // The bone a point belongs to. One answer, no blending: a body part is a solid
  // piece of a Roblox avatar, so it follows exactly one joint.
  function boneFor(x, y) {
    const chain = chainFor(x, y);
    const region = chain.regions.find((item) => chain.fraction >= item.low && chain.fraction <= item.high)
      || chain.regions[chain.regions.length - 1];
    return chain.name === 'body' ? region.bone : `${chain.side}${region.bone}`;
  }

  function addSkinWeights(geometry) {
    const position = geometry.getAttribute('position');
    if (!position?.count) throw new Error('Avatar OBJ contains an empty mesh.');
    const count = position.count;
    const index = geometry.getIndex();
    // The mesh may be indexed or not; both become a list of triangles.
    const triangles = index
      ? Array.from({ length: Math.floor(index.count / 3) }, (_, step) => [
        index.getX(step * 3), index.getX(step * 3 + 1), index.getX(step * 3 + 2)])
      : Array.from({ length: Math.floor(count / 3) }, (_, step) => [step * 3, step * 3 + 1, step * 3 + 2]);

    // ONE WEIGHT VECTOR PER TRIANGLE, shared by its three corners. This is the rule
    // that makes an exploded avatar impossible: a triangle whose corners carry the
    // same weights is an affine transform of itself, so it can rotate and slide but
    // can never be stretched into a spike. Per-vertex weights cannot promise that -
    // two corners 3 cm apart following the hip and the foot at once is exactly the
    // 1144%-stretched triangle measured on the real avatar.
    const weightsPerTriangle = triangles.map((triangle) => {
      const localXs = triangle.map((vertex) => position.getX(vertex) - centerX);
      const centroidY = (position.getY(triangle[0]) + position.getY(triangle[1]) + position.getY(triangle[2])) / 3;
      // A triangle that spans the centre line belongs to the pelvis, not to one leg:
      // sending it to the left leg while its neighbour goes to the right one tears
      // the crotch open (measured: a 1.2-stud hole) the moment the legs move apart.
      const straddlesCentre = Math.min(...localXs) <= 0 && Math.max(...localXs) >= 0
        || Math.min(...localXs.map((value) => Math.abs(value))) < legThreshold;
      const centroidX = (position.getX(triangle[0]) + position.getX(triangle[1]) + position.getX(triangle[2])) / 3;
      const name = boneFor(centroidX, centroidY);
      const bone = straddlesCentre && /(UpperLeg|LowerLeg|Foot)$/.test(name) ? 'Hips' : name;
      return new Map([[boneIndices.get(bone) ?? 0, 1]]);
    });

    // Smooth the per-triangle weights across neighbouring triangles. The triangle
    // rule above guarantees a triangle cannot stretch; this second rule keeps
    // neighbouring triangles from disagreeing so much that the seam between them
    // opens. Both are needed: rigid-but-unblended cracked the shoulder open by
    // 1.18 studs, and blended-per-vertex stretched edges by 1144%.
    const precision = 1e4;
    const cornerKey = (vertex) => `${Math.round(position.getX(vertex) * precision)},`
      + `${Math.round(position.getY(vertex) * precision)},`
      + `${Math.round(position.getZ(vertex) * precision)}`;
    const cornersPerTriangle = triangles.map((triangle) => new Set(triangle.map(cornerKey)));
    const byCorner = new Map();
    cornersPerTriangle.forEach((keys, triangle) => {
      for (const key of keys) {
        if (!byCorner.has(key)) byCorner.set(key, []);
        byCorner.get(key).push(triangle);
      }
    });
    const neighbours = triangles.map(() => new Set());
    for (const list of byCorner.values()) {
      for (const first of list) for (const second of list) if (first !== second) neighbours[first].add(second);
    }
    const SMOOTHING_PASSES = 14;
    const ownWeight = 0.5;
    for (let pass = 0; pass < SMOOTHING_PASSES; pass += 1) {
      const smoothed = weightsPerTriangle.map((own, triangle) => {
        const merged = new Map();
        for (const [bone, weight] of own) merged.set(bone, weight * ownWeight);
        const list = [...neighbours[triangle]];
        if (list.length) {
          const share = (1 - ownWeight) / list.length;
          for (const neighbour of list) {
            for (const [bone, weight] of weightsPerTriangle[neighbour]) {
              merged.set(bone, (merged.get(bone) ?? 0) + weight * share);
            }
          }
        }
        return merged;
      });
      // Never let one side of the body borrow from the other: a stripe of skin
      // dragged between the left arm and the right hip is the smear this whole
      // rewrite exists to remove.
      const guard = Math.max(0.05, Math.max(size.x, size.z) * 0.05);
      smoothed.forEach((map, triangle) => {
        const centroidX = triangles[triangle].reduce((sum, vertex) => sum + position.getX(vertex), 0) / 3;
        const localX = centroidX - centerX;
        if (Math.abs(localX) <= guard) return;
        const forbidden = localX < 0 ? 'Right' : 'Left';
        const fade = clamp((Math.abs(localX) - guard) / guard, 0, 1);
        for (const bone of [...map.keys()]) {
          if (!bones[bone]?.name.startsWith(forbidden)) continue;
          const kept = map.get(bone) * (1 - fade);
          if (kept > 1e-4) map.set(bone, kept);
          else map.delete(bone);
        }
      });
      for (let triangle = 0; triangle < smoothed.length; triangle += 1) weightsPerTriangle[triangle] = smoothed[triangle];
    }

    // Write at most four influences per vertex (the shader limit).
    const indices = new Uint16Array(count * 4);
    const weights = new Float32Array(count * 4);
    let blended = 0;
    triangles.forEach((triangle, triangleIndex) => {
      const ranked = [...weightsPerTriangle[triangleIndex].entries()]
        .filter(([, weight]) => weight > 1e-4)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 4);
      const total = ranked.reduce((sum, [, weight]) => sum + weight, 0) || 1;
      if (ranked.length > 1) blended += 1;
      for (const vertex of triangle) {
        ranked.forEach(([bone, weight], slot) => {
          indices[vertex * 4 + slot] = bone;
          weights[vertex * 4 + slot] = weight / total;
        });
      }
    });
    geometry.setAttribute('skinIndex', new THREE.Uint16BufferAttribute(indices, 4));
    geometry.setAttribute('skinWeight', new THREE.Float32BufferAttribute(weights, 4));
    return { vertices: count, triangles: triangles.length, multiBone: blended };
  }

  const meshes = [];
  model.traverse((object) => {
    if (!object.isMesh || !object.geometry?.getAttribute('position')) return;
    let geometry = object.geometry.clone();
    geometry.applyMatrix4(object.matrixWorld);
    // One owner per triangle only works if each triangle owns its corners. An
    // indexed mesh shares a corner between several triangles, so the last triangle
    // to write would win and the others would straddle two joints. Splitting the
    // index makes the rule exact (the supplied Roblox OBJ is already split this way).
    if (geometry.getIndex()) geometry = geometry.toNonIndexed();
    addSkinWeights(geometry);
    geometry.computeBoundingBox();
    geometry.computeBoundingSphere();
    const skinned = new THREE.SkinnedMesh(geometry, object.material);
    skinned.name = object.name || 'RobloxAvatarMesh';
    skinned.castShadow = true;
    skinned.receiveShadow = true;
    skinned.frustumCulled = false;
    if (skinned.material) {
      const materials = Array.isArray(skinned.material) ? skinned.material : [skinned.material];
      for (const material of materials) {
        material.side = THREE.DoubleSide;
        material.needsUpdate = true;
      }
    }
    rigRoot.add(skinned);
    meshes.push(skinned);
  });
  if (!meshes.length) throw new Error('Avatar OBJ has no mesh groups to rig.');

  rigRoot.updateMatrixWorld(true);
  const skeleton = new THREE.Skeleton(bones);
  for (const mesh of meshes) mesh.bind(skeleton);
  rigRoot.updateMatrixWorld(true);
  return { root: rigRoot, bones: byName, meshCount: meshes.length, skeleton, meshes, height };
}

/**
 * Bounding box of the head geometry in rig space, used to place the animated
 * face exactly on the front of the head instead of floating or sinking into it.
 */
export function measureHeadRegion(THREE, rig) {
  // This used to read `rig.skeleton.bones` unconditionally. The renderer passed
  // the bone map ({Head, Chest, ...}) instead of the whole rig object in some
  // paths, so a finished render died at "Cannot read properties of undefined
  // (reading 'bones')". Accept both shapes, and never throw: a face is cosmetic,
  // the short is not.
  const skeleton = rig?.skeleton || null;
  const boneList = Array.isArray(skeleton?.bones) ? skeleton.bones : [];
  const meshes = Array.isArray(rig?.meshes) ? rig.meshes : [];
  const boneMap = rig?.bones && rig.bones.Head ? rig.bones : (rig?.Head?.isBone ? rig : null);
  const fallbackHeight = Number(rig?.height) || 6.2;
  const empty = {
    center: [0, fallbackHeight * 0.9, 0], size: [fallbackHeight * 0.16, fallbackHeight * 0.16, fallbackHeight * 0.16],
    maxZ: fallbackHeight * 0.08, minZ: -fallbackHeight * 0.08,
  };
  let headBone = boneList.find((bone) => bone?.name === 'Head') || null;
  if (!headBone && boneMap?.Head) headBone = boneMap.Head;
  if (!headBone) return empty;
  // Only a real Object3D can report a world position; anything else gets the
  // plain fallback box instead of a throw in the middle of a render.
  const headOrigin = () => {
    try {
      if (typeof headBone.getWorldPosition === 'function') {
        return headBone.getWorldPosition(new THREE.Vector3());
      }
    } catch { /* fall through to the box fallback */ }
    return null;
  };

  const min = new THREE.Vector3(Infinity, Infinity, Infinity);
  const max = new THREE.Vector3(-Infinity, -Infinity, -Infinity);
  let counted = 0;
  const point = new THREE.Vector3();
  const headIndex = boneList.indexOf(headBone);

  for (const mesh of meshes) {
    const geometry = mesh?.geometry;
    const position = geometry?.getAttribute?.('position');
    if (!position) continue;
    const skinIndex = geometry.getAttribute('skinIndex');
    const step = Math.max(1, Math.floor(position.count / 6000));
    if (skinIndex && headIndex >= 0) {
      for (let vertex = 0; vertex < position.count; vertex += step) {
        const belongs = skinIndex.getX(vertex) === headIndex || skinIndex.getY(vertex) === headIndex;
        if (!belongs) continue;
        point.set(position.getX(vertex), position.getY(vertex), position.getZ(vertex));
        min.min(point);
        max.max(point);
        counted += 1;
      }
    }
  }
  if (!counted || !Number.isFinite(min.x)) {
    // No skin data (a plain mesh, or a bone map handed in on its own): measure
    // the geometry around the head joint instead, so the face still lands on the
    // head instead of floating at the top of the bounding box.
    const headAt = headOrigin();
    if (!headAt) return empty;
    const radius = Math.max(0.28, fallbackHeight * 0.1);
    for (const mesh of meshes) {
      const geometry = mesh?.geometry;
      const position = geometry?.getAttribute?.('position');
      if (!position) continue;
      const step = Math.max(1, Math.floor(position.count / 6000));
      for (let vertex = 0; vertex < position.count; vertex += step) {
        point.set(position.getX(vertex), position.getY(vertex), position.getZ(vertex));
        if (point.distanceTo(headAt) > radius) continue;
        min.min(point);
        max.max(point);
        counted += 1;
      }
    }
  }
  if (!counted || !Number.isFinite(min.x)) {
    const headAt = headOrigin();
    if (!headAt) return empty;
    const size = fallbackHeight * 0.16;
    return {
      center: [headAt.x, headAt.y, headAt.z],
      size: [size, size, size],
      maxZ: headAt.z + size / 2,
      minZ: headAt.z - size / 2,
    };
  }
  return {
    center: [(min.x + max.x) / 2, (min.y + max.y) / 2, (min.z + max.z) / 2],
    size: [max.x - min.x, max.y - min.y, max.z - min.z],
    maxZ: max.z,
    minZ: min.z,
  };
}

/**
 * Where the face plane goes, in head-bone local space.
 *
 * The head region is measured in rig space (the avatar's own coordinates, before
 * the actor is placed on the map), so the head joint is converted back into that
 * space first. Using the raw world position put the face out by the actor's whole
 * map offset once the pivot sat at, say, z = 24.
 */
export function measureFaceAnchor(THREE, rig, head, frontSign = 1) {
  const region = measureHeadRegion(THREE, rig);
  const headWorld = head.getWorldPosition(new THREE.Vector3());
  const canConvert = typeof rig?.root?.worldToLocal === 'function';
  const headOrigin = canConvert ? rig.root.worldToLocal(headWorld.clone()) : headWorld;
  const sign = Number(frontSign) >= 0 ? 1 : -1;
  return {
    region,
    width: Math.max(0.42, Math.min(1.5, region.size[0] * 0.86)),
    height: Math.max(0.3, Math.min(1.1, region.size[1] * 0.68)),
    anchor: new THREE.Vector3(
      region.center[0] - headOrigin.x,
      region.center[1] - headOrigin.y,
      (sign >= 0 ? region.maxZ + 0.012 : region.minZ - 0.012) - headOrigin.z,
    ),
  };
}

const nativeTrackCache = new WeakMap();
const nativeRestPoseCache = new WeakMap();
const NATIVE_POSE_TO_BONE = {
  HumanoidRootPart: 'Root', Root: 'Root',
  LowerTorso: 'Hips', UpperTorso: 'Chest', Torso: 'Spine',
  Head: 'Head', Neck: 'Neck',
  LeftShoulder: 'LeftUpperArm', 'Left Arm': 'LeftUpperArm', LeftUpperArm: 'LeftUpperArm',
  LeftElbow: 'LeftLowerArm', LeftLowerArm: 'LeftLowerArm',
  LeftWrist: 'LeftHand', LeftHand: 'LeftHand',
  RightShoulder: 'RightUpperArm', 'Right Arm': 'RightUpperArm', RightUpperArm: 'RightUpperArm',
  RightElbow: 'RightLowerArm', RightLowerArm: 'RightLowerArm',
  RightWrist: 'RightHand', RightHand: 'RightHand',
  LeftHip: 'LeftUpperLeg', 'Left Leg': 'LeftUpperLeg', LeftUpperLeg: 'LeftUpperLeg',
  LeftKnee: 'LeftLowerLeg', LeftLowerLeg: 'LeftLowerLeg', LeftAnkle: 'LeftFoot', LeftFoot: 'LeftFoot',
  RightHip: 'RightUpperLeg', 'Right Leg': 'RightUpperLeg', RightUpperLeg: 'RightUpperLeg',
  RightKnee: 'RightLowerLeg', RightLowerLeg: 'RightLowerLeg', RightAnkle: 'RightFoot', RightFoot: 'RightFoot',
};

function tracksForNativeClip(THREE, clip) {
  let tracks = nativeTrackCache.get(clip);
  if (tracks) return tracks;
  tracks = new Map();
  for (const frame of clip.keyframes || []) {
    for (const [poseName, pose] of Object.entries(frame.poses || {})) {
      const boneName = NATIVE_POSE_TO_BONE[poseName];
      if (!boneName || !Array.isArray(pose.orientation) || pose.orientation.length !== 9) continue;
      const m = pose.orientation;
      const rotationMatrix = new THREE.Matrix4().set(m[0],m[1],m[2],0,m[3],m[4],m[5],0,m[6],m[7],m[8],0,0,0,0,1);
      const rotation = new THREE.Quaternion().setFromRotationMatrix(rotationMatrix).normalize();
      const position = new THREE.Vector3(...(pose.position || [0,0,0]));
      const weight = clamp(Number(pose.weight ?? 1), 0, 1);
      if (!tracks.has(boneName)) tracks.set(boneName, []);
      tracks.get(boneName).push({ time: Number(frame.time), rotation, position, weight });
    }
  }
  for (const track of tracks.values()) {
    track.sort((a,b)=>a.time-b.time);
    // Roblox Pose.CFrame.Position includes a static joint offset. The generated
    // skeleton already contains its own neutral offsets, so apply only the
    // native animation's displacement from its first pose; otherwise each
    // limb receives the rest offset twice and visibly stretches away from joints.
    const restOffset = track[0]?.position.clone();
    if (restOffset) for (const key of track) key.position.sub(restOffset);
  }
  nativeTrackCache.set(clip, tracks);
  return tracks;
}

/** Sample Roblox KeyframeSequence Pose channels on the generated avatar rig. */
export function applyRobloxAnimationRig(THREE, bones, clip, time, loop = true, positionScale = 1, blend = 1) {
  if (!clip?.keyframes?.length || !Number.isFinite(clip.duration) || clip.duration <= 0) return 0;
  let restPose = nativeRestPoseCache.get(bones);
  if (!restPose) {
    restPose = new Map(Object.entries(bones).map(([name,bone])=>[name,{position:bone.position.clone(),rotation:bone.quaternion.clone()}]));
    nativeRestPoseCache.set(bones,restPose);
  }
  for (const [name,rest] of restPose) {
    bones[name].position.copy(rest.position);
    bones[name].quaternion.copy(rest.rotation);
  }
  const tracks = tracksForNativeClip(THREE,clip);
  const duration = clip.duration;
  const sampleTime = loop ? ((time % duration) + duration) % duration : clamp(time,0,duration);
  let applied = 0;
  for (const [boneName,track] of tracks) {
    const bone = bones[boneName];
    if (!bone || !track.length) continue;
    let right = track.findIndex((key)=>key.time>=sampleTime);
    let left = right<=0?0:right-1;
    if (right<0) right=track.length-1;
    const a=track[left],b=track[right];
    const span=b.time-a.time;
    const alpha=span>1e-8?clamp((sampleTime-a.time)/span,0,1):0;
    const rotation=a.rotation.clone().slerp(b.rotation,alpha);
    // `blend` fades the whole clip: 1 = walking, 0 = the rig's rest stance, which
    // stops a walk cycle from running under a character who is standing still.
    const weight=(a.weight+(b.weight-a.weight)*alpha)*clamp(blend,0,1);
    // Roblox Animate Poses are rotations. Replaying their CFrame position deltas
    // on this generated skeleton pushed limb bones away from their sockets,
    // which is what looked like stretching arms. Only the root/hip may translate,
    // and even then by a small, clamped amount so the body never detaches.
    bone.quaternion.identity().slerp(rotation,weight);
    if(boneName==='Root'||boneName==='Hips'){
      const offset=a.position.clone().lerp(b.position,alpha).multiplyScalar(positionScale*weight);
      offset.x=clamp(offset.x,-0.12,0.12);
      offset.z=clamp(offset.z,-0.12,0.12);
      offset.y=clamp(offset.y,-0.18,0.18);
      bone.position.add(offset);
    }
    applied+=1;
  }
  return applied;
}

/**
 * Procedural walk cycle. `gaitAmount` is the amplitude: 1 while the body is
 * travelling, 0 while it stands still. A walk cycle running under a motionless
 * body is exactly what makes feet skate, and it is what the shipped MP4 showed.
 */
export function animateAvatarRig(bones, time, phase, jumpAmount = 0, gaitAmount = 1) {
  const amount = clamp(gaitAmount, 0, 1);
  const gait = Math.sin(time * 2.8 + phase) * amount;
  const opposite = -gait;
  const jump = clamp(jumpAmount, 0, 1);
  bones.LeftUpperArm.rotation.x = gait * 0.62;
  bones.RightUpperArm.rotation.x = opposite * 0.62;
  bones.LeftLowerArm.rotation.x = (-0.10 + Math.max(0, opposite) * 0.30) * amount;
  bones.RightLowerArm.rotation.x = (-0.10 + Math.max(0, gait) * 0.30) * amount;
  bones.LeftUpperArm.rotation.z = 0.04 * amount - jump * 0.46;
  bones.RightUpperArm.rotation.z = -0.04 * amount + jump * 0.46;
  bones.LeftHand.rotation.x = -0.08 * amount;
  bones.RightHand.rotation.x = -0.08 * amount;

  bones.LeftUpperLeg.rotation.x = opposite * 0.58;
  bones.RightUpperLeg.rotation.x = gait * 0.58;
  bones.LeftLowerLeg.rotation.x = Math.max(0, gait) * 0.50 + jump * 0.18;
  bones.RightLowerLeg.rotation.x = Math.max(0, opposite) * 0.50 + jump * 0.18;
  bones.LeftFoot.rotation.x = -bones.LeftLowerLeg.rotation.x * 0.45;
  bones.RightFoot.rotation.x = -bones.RightLowerLeg.rotation.x * 0.45;
  bones.Hips.rotation.y = Math.sin(time * 0.9 + phase) * 0.035 * amount;
  bones.Spine.rotation.x = (0.025 + Math.sin(time * 2.8 + phase) * 0.035) * amount;
  bones.Chest.rotation.x = -bones.Spine.rotation.x * 0.45;
  bones.Head.rotation.y = Math.sin(time * 1.15 + phase) * 0.08;
}

/**
 * Standing still, alive: breathing, a slow weight shift and a small head turn.
 * Used while the camera holds on a character, so they read as acting rather than
 * frozen. It never touches the legs - feet stay planted.
 */
export function idleAvatarRig(bones, time, phase, amount = 1) {
  const strength = clamp(amount, 0, 1);
  if (strength <= 0) return;
  const breath = Math.sin(time * 1.6 + phase) * strength;
  const sway = Math.sin(time * 0.7 + phase * 1.4) * strength;
  bones.Chest.rotation.x += breath * 0.035;
  bones.Spine.rotation.x += breath * 0.02;
  bones.Spine.rotation.z = sway * 0.02;
  bones.Head.rotation.y += sway * 0.10;
  bones.Head.rotation.x = Math.sin(time * 1.1 + phase * 0.7) * 0.03 * strength;
  if (bones.LeftUpperArm) {
    bones.LeftUpperArm.rotation.z += breath * 0.05 - 0.05 * strength;
    bones.RightUpperArm.rotation.z -= breath * 0.05 - 0.05 * strength;
    bones.LeftUpperArm.rotation.x += Math.sin(time * 0.9 + phase) * 0.05 * strength;
    bones.RightUpperArm.rotation.x += Math.sin(time * 0.9 + phase + 1.2) * 0.05 * strength;
    bones.LeftLowerArm.rotation.x -= 0.12 * strength;
    bones.RightLowerArm.rotation.x -= 0.12 * strength;
  }
}
