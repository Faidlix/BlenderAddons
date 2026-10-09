# Faidlix_Fbx ZipExporter

Blender 5.2+ Extension. It exposes adjustable FBX export settings and packages the exported FBX plus selected Actions and material image textures into one ZIP file.

## Install

Add the shared repository URL below in Blender Preferences > Get Extensions, then install `Faidlix_Fbx ZipExporter`:

`https://raw.githubusercontent.com/Faidlix/BlenderAddons/main/repository/index.json`

After enabling it, open the 3D View sidebar (`N`) and choose **Faidlix**. The collapsed **Faidlix_Fbx ZipExporter** panel appears below BakeMap and Texture Marge.

Choose **線上更新** in the panel to synchronize the shared `Faidlix/BlenderAddons` repository and install a newer release. The optional Faidlix Manager can update this and other installed Faidlix Extensions together; this Extension remains independently installable and does not depend on Manager.

The export dialog reads the current settings from Blender's native FBX exporter when it opens. Shared settings are written back after export. **Sync FBX Defaults** is inside the export dialog, under the top preset selector.

The export dialog's top **Operator Presets** menu uses the same native `export_scene.fbx` preset folder as Blender's FBX exporter. Presets such as `ToUnity` and `ToUnityPackTexture` therefore appear in both places; the `+` button saves a shared FBX preset.

Materials always use **Keep Blender Materials**; the shader dropdown is removed. The original shader graph is retained. The default texture mode traces backwards from active material outputs on exported objects and used material slots, including nested node groups. The optional all-textures mode includes every image node in those materials while still excluding unrelated scene images. The texture dialog can include/exclude and rename package files; temporary image paths keep FBX references synchronized with renamed files.

Packed and generated images are written before exporting FBX. Temporary file-backed images provide valid texture references and are restored afterwards. A required missing texture cancels export instead of silently creating an incomplete package. Collected textures use portable paths; Embed Textures is honored with native COPY mode. Batch export is currently rejected explicitly.

## Notes

- `Embed Textures` is passed through to Blender's FBX exporter.
- `打包貼圖` controls packaging. Its text mode button switches between connected textures and all image nodes in exported-object materials.
- `貼圖設定…` supports per-image inclusion, ZIP filename editing, reset, and side-by-side duplicate-name resolution.
- The Action list is rebuilt when export starts. Checked Actions become separate FBX AnimStacks whose Unity clip names exactly match the editable Action export names, without an `Armature|` prefix.
- Procedural textures are not image files and therefore cannot be collected automatically.
- Generated/UV test images and packed images are exported as PNG files when collecting textures.
- Presets are stored in Blender's user scripts preset folder; locked/portable installations use the add-on's `presets` folder as a fallback.
