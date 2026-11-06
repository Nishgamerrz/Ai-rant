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

  function candidatesFor(x, y) {
    const localX = x - centerX;
    const fractionY = (y - centerY) / height;
    const absX = Math.abs(localX);
    if (fractionY > 0.78) return ['Head', 'Neck', 'Chest'];
    if (fractionY > 0.34 && fractionY < 0.81 && absX > shoulderX * 0.72) {
      const side = localX < 0 ? 'Left' : 'Right';
      return [`${side}UpperArm`, `${side}LowerArm`, `${side}Hand`, 'Chest'];
    }
    if (fractionY < 0.49 && absX > hipX * 0.40) {
      const side = localX < 0 ? 'Left' : 'Right';
      return [`${side}UpperLeg`, `${side}LowerLeg`, `${side}Foot`, 'Hips'];
    }
    if (fractionY < 0.47) return ['Hips', 'Spine', 'Chest'];
    return ['Hips', 'Spine', 'Chest', 'Neck'];
  }

  // Roblox avatars are made of rigid parts, so skinning must be rigid too.
  // Blending one vertex across two bones (the previous behaviour) is what made
  // arms and legs visibly stretch like rubber when a joint rotated. Every
  // vertex now follows exactly one bone at full weight, and the bone is chosen
  // by distance to that bone's *segment* (origin -> child), which keeps the
  // forearm/hand/calf bindings anatomically correct.
  const boneSegments = bones.map((bone) => {
    const start = bone.getWorldPosition(new THREE.Vector3());
    const child = bone.children.find((item) => item.isBone);
    const end = child ? child.getWorldPosition(new THREE.Vector3()) : start.clone();
    return { name: bone.name, start, end };
  });
  const segmentsByName = new Map(boneSegments.map((segment) => [segment.name, segment]));

  function distanceToSegment(point, segment) {
    const ax = segment.start.x, ay = segment.start.y, az = segment.start.z;
    const bx = segment.end.x - ax, by = segment.end.y - ay, bz = segment.end.z - az;
    const lengthSq = bx * bx + by * by + bz * bz;
    const t = lengthSq > 1e-9
      ? Math.max(0, Math.min(1, ((point.x - ax) * bx + (point.y - ay) * by + (point.z - az) * bz) / lengthSq))
      : 0;
    const dx = point.x - (ax + bx * t), dy = point.y - (ay + by * t), dz = point.z - (az + bz * t);
    return Math.sqrt(dx * dx + dy * dy + dz * dz);
  }

  function addSkinWeights(geometry) {
    const position = geometry.getAttribute('position');
    if (!position?.count) throw new Error('Avatar OBJ contains an empty mesh.');
    const indices = new Uint16Array(position.count * 4);
    const weights = new Float32Array(position.count * 4);
    const point = new THREE.Vector3();
    for (let vertex = 0; vertex < position.count; vertex += 1) {
      point.set(position.getX(vertex), position.getY(vertex), position.getZ(vertex));
      let bestIndex = 0;
      let bestDistance = Infinity;
      for (const name of candidatesFor(point.x, point.y)) {
        const segment = segmentsByName.get(name);
        if (!segment) continue;
        const distance = distanceToSegment(point, segment);
        if (distance < bestDistance) {
          bestDistance = distance;
          bestIndex = boneIndices.get(name);
        }
      }
      const offset = vertex * 4;
      indices[offset] = bestIndex;
      weights[offset] = 1;
    }
    geometry.setAttribute('skinIndex', new THREE.Uint16BufferAttribute(indices, 4));
    geometry.setAttribute('skinWeight', new THREE.Float32BufferAttribute(weights, 4));
  }

  const meshes = [];
  model.traverse((object) => {
    if (!object.isMesh || !object.geometry?.getAttribute('position')) return;
    const geometry = object.geometry.clone();
    geometry.applyMatrix4(object.matrixWorld);
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
  const headIndex = rig.skeleton.bones.findIndex((bone) => bone.name === 'Head');
  const fallbackHeight = Number(rig.height) || 6.2;
  const empty = {
    center: [0, fallbackHeight * 0.9, 0], size: [fallbackHeight * 0.16, fallbackHeight * 0.16, fallbackHeight * 0.16],
    maxZ: fallbackHeight * 0.08, minZ: -fallbackHeight * 0.08,
  };
  if (headIndex < 0) return empty;
  const min = new THREE.Vector3(Infinity, Infinity, Infinity);
  const max = new THREE.Vector3(-Infinity, -Infinity, -Infinity);
  let counted = 0;
  const point = new THREE.Vector3();
  for (const mesh of rig.meshes || []) {
    const geometry = mesh.geometry;
    const position = geometry.getAttribute('position');
    const skinIndex = geometry.getAttribute('skinIndex');
    if (!position || !skinIndex) continue;
    const step = Math.max(1, Math.floor(position.count / 6000));
    for (let vertex = 0; vertex < position.count; vertex += step) {
      const belongs = skinIndex.getX(vertex) === headIndex || skinIndex.getY(vertex) === headIndex;
      if (!belongs) continue;
      point.set(position.getX(vertex), position.getY(vertex), position.getZ(vertex));
      min.min(point);
      max.max(point);
      counted += 1;
    }
  }
  if (!counted || !Number.isFinite(min.x)) return empty;
  return {
    center: [(min.x + max.x) / 2, (min.y + max.y) / 2, (min.z + max.z) / 2],
    size: [max.x - min.x, max.y - min.y, max.z - min.z],
    maxZ: max.z,
    minZ: min.z,
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
