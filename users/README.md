# Optional local avatar meshes

The workflow checks this folder before attempting the Roblox 3D-mesh API. It matches the username entered in the GitHub Actions form case-insensitively:

```text
users/
  Builderman/
    avatar.obj
    avatar.mtl       # optional; a neutral material is generated if absent
    texture.png      # optional; keep textures at the relative paths used by the MTL
```

Put each user's OBJ and its MTL/texture files in a folder named exactly after their Roblox username. The OBJ must contain readable vertex (`v`) and face (`f`) records. The workflow copies the files into its temporary render assets and auto-rigs the mesh. It does not commit generated render assets.

If no matching `users/<username>/avatar.obj` exists, the workflow continues with its normal automatic Roblox mesh lookup and official thumbnail fallback. If Roblox cannot resolve the username but a local OBJ exists, the MP4 can still render that local mesh under the entered username. This folder is an optional local asset source; it does not bypass Roblox authentication or retrieve protected meshes by itself.
