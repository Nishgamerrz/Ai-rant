function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

/**
 * Build an approximate R15-style skeleton and skin weights for an authentic,
 * unrigged Roblox OBJ. All mesh transforms are baked into the avatar-root space
 * first, so the same rig can drive every OBJ material group/accessory.
 */
export function buildAvatarRig(THREE, model) {
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
export function applyRobloxAnimationRig(THREE, bones, clip, time, loop = true, positionScale = 1) {
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
    const weight=a.weight+(b.weight-a.weight)*alpha;
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

/** Procedural fallback for profiles that have no native Roblox KeyframeSequence. */
export function animateAvatarRig(bones, time, phase, jumpAmount = 0) {
  const gait = Math.sin(time * 2.8 + phase);
  const opposite = -gait;
  const jump = clamp(jumpAmount, 0, 1);
  bones.LeftUpperArm.rotation.x = gait * 0.62;
  bones.RightUpperArm.rotation.x = opposite * 0.62;
  bones.LeftLowerArm.rotation.x = -0.10 + Math.max(0, opposite) * 0.30;
  bones.RightLowerArm.rotation.x = -0.10 + Math.max(0, gait) * 0.30;
  bones.LeftUpperArm.rotation.z = 0.04 - jump * 0.46;
  bones.RightUpperArm.rotation.z = -0.04 + jump * 0.46;
  bones.LeftHand.rotation.x = -0.08;
  bones.RightHand.rotation.x = -0.08;

  bones.LeftUpperLeg.rotation.x = opposite * 0.58;
  bones.RightUpperLeg.rotation.x = gait * 0.58;
  bones.LeftLowerLeg.rotation.x = Math.max(0, gait) * 0.50 + jump * 0.18;
  bones.RightLowerLeg.rotation.x = Math.max(0, opposite) * 0.50 + jump * 0.18;
  bones.LeftFoot.rotation.x = -bones.LeftLowerLeg.rotation.x * 0.45;
  bones.RightFoot.rotation.x = -bones.RightLowerLeg.rotation.x * 0.45;
  bones.Hips.rotation.y = Math.sin(time * 0.9 + phase) * 0.035;
  bones.Spine.rotation.x = 0.025 + Math.sin(time * 2.8 + phase) * 0.035;
  bones.Chest.rotation.x = -bones.Spine.rotation.x * 0.45;
  bones.Head.rotation.y = Math.sin(time * 1.15 + phase) * 0.08;
}
