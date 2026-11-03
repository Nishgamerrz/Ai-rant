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

  function addSkinWeights(geometry) {
    const position = geometry.getAttribute('position');
    if (!position?.count) throw new Error('Avatar OBJ contains an empty mesh.');
    const indices = new Uint16Array(position.count * 4);
    const weights = new Float32Array(position.count * 4);
    for (let vertex = 0; vertex < position.count; vertex += 1) {
      const x = position.getX(vertex), y = position.getY(vertex), z = position.getZ(vertex);
      const nearest = candidatesFor(x, y)
        .map((name) => {
          const point = bonePositions.get(name);
          const dx = x - point[0], dy = y - point[1], dz = z - point[2];
          return { index: boneIndices.get(name), distance: Math.sqrt(dx * dx + dy * dy + dz * dz) };
        })
        .sort((a, b) => a.distance - b.distance)
        .slice(0, 2);
      const first = nearest[0], second = nearest[1];
      const firstInfluence = 1 / ((first.distance + 0.08) ** 2);
      const secondInfluence = second ? 1 / ((second.distance + 0.08) ** 2) : 0;
      const total = firstInfluence + secondInfluence;
      const offset = vertex * 4;
      indices[offset] = first.index;
      weights[offset] = firstInfluence / total;
      if (second) {
        indices[offset + 1] = second.index;
        weights[offset + 1] = secondInfluence / total;
      }
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
  return { root: rigRoot, bones: byName, meshCount: meshes.length, skeleton };
}

/** Procedural, Roblox-style walk cycle and small expressive pose for auto-rigged meshes. */
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
