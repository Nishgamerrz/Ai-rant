# Username-matched avatar models

In the GitHub Actions **Character usernames** field, enter the usernames separated by **commas** (for example `normal, noob`). Spaces, semicolons and newlines also work; the first name is the lead. Do not add `@`, links or IDs. The workflow checks the matching files in this folder automatically; you do not upload a model through the Actions form.

## Direct mesh files (preferred)

The workflow prefers a self-contained username-matched mesh over the `.rbxm` model and its externally hosted Roblox asset references:

```text
users/
  normal.obj
  normal.mtl                 # optional; OBJ material/texture definitions
  normal_assets/              # optional sibling folder for OBJ textures
    body.png
  AnotherUser.glb
  AvatarUser.gltf             # plus referenced .bin/images beside it
  FbxUser.fbx                 # optional FbxUser_assets/ texture folder
```

Supported mesh formats are **OBJ, glTF (`.gltf`), GLB (`.glb`), FBX (`.fbx`), COLLADA (`.dae`), PLY, STL, and 3DS**. OBJ uses a matching `.mtl` and local texture paths where present. glTF/COLLADA dependencies must be local files referenced by the model. FBX/3DS textures can be placed in a sibling `<model>_assets/` or `<model>.fbm/` directory. Remote model dependencies are not fetched. Files are matched by username, case-insensitively; folder-based `users/<username>/avatar.<format>` sources are also accepted.

Unrigged mesh files are automatically skinned to an R15-style skeleton using mesh bounds and vertex positions; the auto-rig is best-effort and may differ from a carefully authored Roblox rig. When a matching RBXM is present, the workflow fetches its native walk/jump KeyframeSequence assets and retargets those actual Roblox pose tracks onto the generated rig. The RBXM is parsed for animation metadata only, so its protected body meshes are not downloaded when a direct mesh is available. If the native walk/jump keyframes cannot be accessed, the MP4 step refuses to substitute procedural limb motion. Without RBXM animation IDs, the renderer can still use its procedural fallback.

## Checking an uploaded GLB

Run `npm run test:avatar-glb` inside `tools/video_renderer` (or `node avatar_glb_smoke_test.mjs users/<name>.glb`) to see whether an uploaded `.glb` is already rigged. It reports the embedded skin bindings and animation clips, then runs the automatic rig.

`users/noob.glb` is a real example: it ships a Sketchfab `Armature` with bone nodes but **0 skin bindings and 0 animation clips**, so it is not directly animatable. The check confirms the auto-rig binds all 6 mesh parts to the 18 R15-style joints with rigid weights and measures the head region, so the avatar renders with native limb motion *and* an animated face.

## Roblox model files

A flat `users/<username>.rbxm` is still supported after the direct mesh formats. If both are present, the local mesh drives the MP4 and the RBXM is parsed only to preserve native animation IDs for the separate Studio project; its protected MeshParts are not downloaded or used to replace the local mesh. If no direct mesh is present, RBXM MeshParts can only be converted when their referenced Roblox assets are accessible. A `.rbxl` or `.rbxlx` is a whole Roblox place, not a standalone avatar mesh, and is not treated as a direct avatar model.

The MP4 renderer uses Three.js and the generated procedural rig; it does not run Roblox Studio or execute the Roblox `Animate` script. The Studio project remains a separate downloadable artifact. No Roblox cookies or API keys should be placed in this folder or in chat.
