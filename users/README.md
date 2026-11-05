# Username-matched Roblox avatar models

In the GitHub Actions **Character usernames** field, enter only the Roblox username (for example, `normal`)—do not append `.rbxm` and do not upload a file. The workflow automatically checks this folder for the matching **flat, username-named RBXM file first**; no per-user subdirectories are required:

```text
users/
  normal.rbxm
  AnotherUsername.rbxm
```

For a workflow username of `normal`, the matching source is `users/normal.rbxm`. Matching is case-insensitive. The file must be a Roblox **model** (`.rbxm`) containing a Humanoid, a HumanoidRootPart, and MeshParts. A `.rbxl` is a whole place file and is not used as an avatar model.

The RBXM keeps its native rig and animation references. Its MeshParts refer to Roblox asset IDs, so the automated MP4 step resolves those official mesh/texture assets, converts the geometry into a temporary renderer format, and applies the existing Three.js motion system. The MP4 is not a Roblox Studio capture, and Roblox's native `Animate` script does not execute in the MP4 renderer. Native animation IDs from the RBXM are also passed to the generated Studio experience, where the avatars move with Roblox Humanoids. The original RBXM is included in the downloadable package under `avatar-assets/source-rbxm/`.

When no matching RBXM exists, the workflow retains the optional legacy mesh layout below, then continues with the existing Roblox mesh lookup and official thumbnail fallback:

```text
users/
  SomeUsername/
    avatar.obj
    avatar.mtl       # optional
    texture.png      # optional; relative paths referenced by the MTL
```

No model file is uploaded through the Actions form; that form accepts text inputs, not files. Do not put Roblox cookies or API keys in this folder or in chat. Some referenced Roblox assets may require permission; if the model's assets cannot be fetched, the workflow uses the existing authorized-mesh or same-account thumbnail fallback when available.
