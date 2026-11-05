import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const Module = require('node:module');
const lz4js = require('lz4js');
const originalLoad = Module._load;
// rbxm-parser only needs raw-block LZ4 decoding here. Use the pure-JS decoder so
// the workflow does not need a native compiler or a Roblox Studio installation.
Module._load = function load(request, parent, isMain) {
  if (request === 'lz4') {
    return {
      decodeBlock(source, destination) {
        return lz4js.decompressBlock(
          new Uint8Array(source.buffer, source.byteOffset, source.byteLength),
          new Uint8Array(destination.buffer, destination.byteOffset, destination.byteLength),
          0, source.byteLength, 0,
        );
      },
      encodeBound() { throw new Error('RBXM writing is not used by this importer.'); },
      encodeBlock() { throw new Error('RBXM writing is not used by this importer.'); },
    };
  }
  return originalLoad.call(this, request, parent, isMain);
};
const { RobloxFile } = require('rbxm-parser');

function assetId(value) {
  if (typeof value !== 'string') return null;
  const match = value.match(/(?:[?&]id=|rbxassetid:\/\/)(\d{1,20})/i);
  return match?.[1] ?? null;
}

function finiteVector(value, names) {
  const vector = names.map((name) => Number(value?.[name]));
  if (vector.some((n) => !Number.isFinite(n))) throw new Error('RBXM contains a non-finite transform or size.');
  return vector;
}

function vector3(value, fallback = [1, 1, 1]) {
  if (!value) return fallback;
  return finiteVector(value, ['X', 'Y', 'Z']);
}

function color3(value) {
  if (!value) return [0.8, 0.8, 0.8];
  return finiteVector(value, ['R', 'G', 'B']).map((component) => Math.max(0, Math.min(1, component)));
}

function cframe(value) {
  const position = vector3(value?.Position, [0, 0, 0]);
  const orientation = Array.isArray(value?.Orientation) ? value.Orientation.map(Number) : [];
  if (orientation.length !== 9 || orientation.some((n) => !Number.isFinite(n))) {
    throw new Error('RBXM part is missing a valid CFrame orientation.');
  }
  return { position, orientation };
}

function walk(instance, result = []) {
  result.push(instance);
  for (const child of instance.Children ?? []) walk(child, result);
  return result;
}

function readAnimationIds(instances) {
  const animationIds = {};
  const locomotion = new Set(['idle', 'walk', 'run', 'jump', 'fall', 'climb', 'swim']);
  for (const animation of instances.filter((instance) => instance.ClassName === 'Animation')) {
    const id = assetId(animation.AnimationId);
    if (!id) continue;
    let parent = animation.Parent;
    let key = '';
    while (parent) {
      const candidate = String(parent.Name || '').toLowerCase();
      if (locomotion.has(candidate)) { key = candidate; break; }
      parent = parent.Parent;
    }
    if (!key) {
      const name = String(animation.Name || '').toLowerCase();
      key = [...locomotion].find((kind) => name.includes(kind)) || name;
    }
    if (key) animationIds[key] ??= `rbxassetid://${id}`;
  }
  return animationIds;
}

function transformFromPose(pose) {
  const frame = pose.CFrame;
  if (!frame?.Position) return null;
  const position = vector3(frame.Position, [0, 0, 0]);
  const orientation = Array.isArray(frame.Orientation) ? frame.Orientation.map(Number) : [];
  if (orientation.length !== 9 || orientation.some((value) => !Number.isFinite(value))) return null;
  return { position, orientation, weight: Number.isFinite(Number(pose.Weight)) ? Number(pose.Weight) : 1 };
}

function poseChannels(pose, output = {}) {
  if (pose.ClassName === 'Pose') {
    const transform = transformFromPose(pose);
    if (transform) output[String(pose.Name || '')] = transform;
  }
  for (const child of pose.Children ?? []) {
    if (child.ClassName === 'Pose') poseChannels(child, output);
  }
  return output;
}

async function fetchNativeAnimationClip(id, label) {
  const response = await fetch(`https://assetdelivery.roblox.com/v1/asset/?id=${id}`, {
    headers: { Accept: '*/*', 'User-Agent': 'Ai-rant-Roblox-animation-renderer/1.0' },
    signal: AbortSignal.timeout(45000),
  });
  if (!response.ok) throw new Error(`${label} animation asset ${id} returned HTTP ${response.status}`);
  const bytes = Buffer.from(await response.arrayBuffer());
  if (!bytes.length || bytes.length > 64 * 1024 * 1024) throw new Error(`${label} animation asset ${id} has an invalid size`);
  const file = RobloxFile.ReadFromBuffer(bytes);
  if (!file?.Roots?.length) throw new Error(`${label} animation asset ${id} is not a readable Roblox keyframe file`);
  const instances = file.Roots.flatMap((root) => walk(root));
  const keyframes = instances.filter((instance) => instance.ClassName === 'Keyframe')
    .map((keyframe) => ({ time: Number(keyframe.Time), poses: poseChannels(keyframe) }))
    .filter((keyframe) => Number.isFinite(keyframe.time) && Object.keys(keyframe.poses).length)
    .sort((a, b) => a.time - b.time);
  const duration = keyframes.at(-1)?.time ?? 0;
  if (keyframes.length < 2 || duration <= 0) throw new Error(`${label} animation asset ${id} has no usable Pose timeline`);
  return { asset_id: String(id), duration, keyframes };
}

async function fetchNativeAnimationClips(animationIds) {
  const clips = {};
  const errors = {};
  const playbackStates = ['idle', 'walk', 'run', 'jump', 'fall', 'climb', 'swim'];
  for (const name of playbackStates) {
    const id = assetId(animationIds[name]);
    if (!id) continue;
    try {
      clips[name] = await fetchNativeAnimationClip(id, name);
      console.log(`Fetched native ${name} animation ${id}: ${clips[name].keyframes.length} keyframes.`);
    } catch (error) {
      errors[name] = String(error.message || error);
      console.warn(`Native ${name} animation was unavailable: ${errors[name]}`);
    }
  }
  return { clips, errors };
}

async function fetchAsset(url, destination, label, optional = false) {
  try {
    const response = await fetch(url, {
      headers: { Accept: '*/*', 'User-Agent': 'Ai-rant-RBXM-avatar-renderer/1.0' },
      signal: AbortSignal.timeout(45000),
    });
    if (!response.ok) throw new Error(`Roblox asset request returned HTTP ${response.status}`);
    const bytes = Buffer.from(await response.arrayBuffer());
    if (!bytes.length || bytes.length > 64 * 1024 * 1024) throw new Error('Roblox asset response has an invalid size.');
    await fs.mkdir(path.dirname(destination), { recursive: true });
    await fs.writeFile(destination, bytes);
    return { path: destination, bytes: bytes.length };
  } catch (error) {
    if (optional) {
      console.warn(`Optional RBXM texture ${label} was not available (${error.message}); using its part color.`);
      return null;
    }
    throw new Error(`Could not load required mesh ${label}: ${error.message}`);
  }
}

async function prepareProfile(profile) {
  if (!profile.rbxm_path) return profile;
  const source = path.resolve(profile.rbxm_path);
  const bytes = await fs.readFile(source);
  const file = RobloxFile.ReadFromBuffer(bytes);
  if (!file || !file.Roots?.length) throw new Error(`users/${path.basename(source)} is not a readable Roblox model file.`);
  const instances = file.Roots.flatMap((root) => walk(root));
  const humanoid = instances.find((instance) => instance.ClassName === 'Humanoid');
  const meshParts = instances.filter((instance) => instance.ClassName === 'MeshPart' && assetId(instance.MeshId));
  if (!humanoid || meshParts.length < 6) {
    throw new Error(`users/${path.basename(source)} must contain a Humanoid and at least six MeshParts; found ${meshParts.length}.`);
  }
  const rootPart = instances.find((instance) => instance.ClassName === 'BasePart' && instance.Name === 'HumanoidRootPart')
    ?? instances.find((instance) => instance.ClassName === 'Part' && instance.Name === 'HumanoidRootPart');
  if (!rootPart) throw new Error(`users/${path.basename(source)} has no HumanoidRootPart.`);
  const rootTransform = cframe(rootPart.CFrame);
  // Extract native animation IDs before downloading external meshes so the Studio project
  // can still use Roblox's Animator if a protected MeshPart asset returns HTTP 401.
  const animationIds = readAnimationIds(instances);
  profile.rbxm_animation_ids = animationIds;
  const nativeAnimations = await fetchNativeAnimationClips(animationIds);
  profile.rbxm_animation_clips = nativeAnimations.clips;
  profile.rbxm_animation_errors = nativeAnimations.errors;
  if (profile.model_ready && ['users-file', 'users-folder'].includes(profile.model_source)) {
    console.log(`Using the self-contained ${profile.model_format || 'OBJ'} avatar mesh for MP4; extracted ${Object.keys(animationIds).length} native animation references from the matching RBXM for Studio.`);
    return profile;
  }
  const outputDir = path.resolve(profile.rbxm_output_dir);
  await fs.mkdir(outputDir, { recursive: true });
  const meshCache = new Map();
  const textureCache = new Map();
  const parts = [];

  for (const part of meshParts) {
    const meshId = assetId(part.MeshId);
    const meshUrl = `https://assetdelivery.roblox.com/v1/asset/?id=${meshId}`;
    let mesh = meshCache.get(meshId);
    if (!mesh) {
      const destination = path.join(outputDir, 'rbxm-meshes', `${meshId}.mesh`);
      mesh = await fetchAsset(meshUrl, destination, `${part.Name} (${meshId})`);
      meshCache.set(meshId, mesh);
    }
    const textureId = assetId(part.TextureID);
    let texture = null;
    if (textureId) {
      texture = textureCache.get(textureId);
      if (texture === undefined) {
        const url = `https://assetdelivery.roblox.com/v1/asset/?id=${textureId}`;
        const response = await fetch(url, {
          headers: { Accept: '*/*', 'User-Agent': 'Ai-rant-RBXM-avatar-renderer/1.0' },
          signal: AbortSignal.timeout(45000),
        }).catch(() => null);
        if (response?.ok) {
          const image = Buffer.from(await response.arrayBuffer());
          let extension = null;
          if (image.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))) extension = '.png';
          else if (image.subarray(0, 3).equals(Buffer.from([255, 216, 255]))) extension = '.jpg';
          else if (image.subarray(0, 4).toString() === 'RIFF' && image.subarray(8, 12).toString() === 'WEBP') extension = '.webp';
          if (extension && image.length <= 32 * 1024 * 1024) {
            const texturePath = path.join(outputDir, 'rbxm-textures', `${textureId}${extension}`);
            await fs.mkdir(path.dirname(texturePath), { recursive: true });
            await fs.writeFile(texturePath, image);
            texture = { path: texturePath, bytes: image.length };
          }
        }
        textureCache.set(textureId, texture);
        if (!texture) console.warn(`Optional RBXM texture ${part.Name} (${textureId}) was not available; using its part color.`);
      }
    }
    parts.push({
      name: String(part.Name || 'MeshPart').replace(/[^A-Za-z0-9_ -]/g, '_'),
      mesh_path: mesh.path,
      mesh_id: meshId,
      texture_path: texture?.path ?? null,
      texture_id: textureId,
      size: vector3(part.Size),
      initial_size: vector3(part.InitialSize, vector3(part.Size)),
      cframe: cframe(part.CFrame),
      color: color3(part.Color),
    });
  }
  const manifest = {
    format: 'rbxm-avatar-manifest-v1',
    username: profile.username,
    source_file: source,
    root_cframe: rootTransform,
    parts,
    animation_ids: animationIds,
  };
  const manifestPath = path.join(outputDir, 'rbxm-avatar-manifest.json');
  await fs.writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
  profile.rbxm_manifest = manifestPath;
  profile.rbxm_animation_ids = animationIds;
  profile.model_source = 'rbxm-file';
  console.log(`Parsed ${profile.username}'s RBXM rig: ${parts.length} MeshParts, ${Object.keys(animationIds).length} native animation references.`);
  return profile;
}

async function main() {
  const [profilesPathArg, assetRootArg] = process.argv.slice(2);
  if (!profilesPathArg || !assetRootArg) throw new Error('usage: prepare_rbxm_avatar.mjs PROFILES.json ASSET_ROOT');
  const profilesPath = path.resolve(profilesPathArg);
  const assetRoot = path.resolve(assetRootArg);
  const profiles = JSON.parse(await fs.readFile(profilesPath, 'utf8'));
  if (!Array.isArray(profiles)) throw new Error('Avatar profiles must be a JSON array.');
  for (const profile of profiles) {
    if (!profile.rbxm_path) continue;
    profile.rbxm_output_dir = path.join(assetRoot, String(profile.user_id));
    try {
      const sourceCopy = path.join(assetRoot, 'source-rbxm', `${profile.username}.rbxm`);
      await fs.mkdir(path.dirname(sourceCopy), { recursive: true });
      await fs.copyFile(profile.rbxm_path, sourceCopy);
      profile.source_rbxm_copy = sourceCopy;
      await prepareProfile(profile);
    } catch (error) {
      profile.rbxm_import_error = String(error.message || error);
      const preservedAnimationCount = Object.keys(profile.rbxm_animation_ids || {}).length;
      console.warn(`Could not render ${profile.username}'s RBXM (${profile.rbxm_import_error}); preserving ${preservedAnimationCount} native animation references for Studio.`);
      if (profile.model_ready && ['users-file', 'users-folder'].includes(profile.model_source)) {
        console.warn(`Keeping the self-contained local mesh for ${profile.username}; only RBXM animation metadata was unavailable.`);
      } else if (profile.fallback_model_ready && profile.fallback_model_obj && profile.fallback_model_mtl) {
        profile.model_obj = profile.fallback_model_obj;
        profile.model_mtl = profile.fallback_model_mtl;
        profile.model_ready = true;
        profile.model_source = 'rbxm-unavailable-remote-mesh-fallback';
      } else if (!profile.thumbnail_ready) {
        throw new Error(`RBXM import failed and no real avatar fallback is available for ${profile.username}: ${error.message}`);
      } else {
        profile.model_source = 'official-thumbnail-fallback';
      }
      delete profile.rbxm_manifest;
      delete profile.fallback_model_obj;
      delete profile.fallback_model_mtl;
      delete profile.fallback_model_ready;
    } finally {
      delete profile.rbxm_output_dir;
      delete profile.rbxm_path;
    }
  }
  await fs.writeFile(profilesPath, `${JSON.stringify(profiles, null, 2)}\n`);
}

main().catch((error) => {
  console.error(`RBXM avatar import failed: ${error.message}`);
  process.exitCode = 1;
});
