# Faidlix Texture Marge

正式更新來源：`https://raw.githubusercontent.com/Faidlix/BlenderAddons/main/repository/index.json`

Blender 5.2 extension for merging arbitrary source image channels into one RGBA image and building a new material from the result.

## Features

- Material scan or manual Blender/external image sources.
- Add or remove any number of source images.
- Source semantic types including Diffuse, Normal, Metallic, Roughness, Emission, AO, Alpha, Height and Specular.
- Multiple source components per output channel with Add, Average, Multiply, Maximum or Minimum mixing.
- Per-output-channel material purpose.
- Color (sRGB) or Data (Non-Color) output.
- 256, 512, 1024, 2048, 4096 and custom output sizes.
- Bilinear or nearest resizing.
- Generated images remain inside the `.blend` until exported.
- Separate Merge, Build Material and Export operations.
- Online update through the shared Faidlix Blender Extension repository.
- The optional Faidlix Manager is the only provider of the global Update All panel.
- Source mode uses tab-style buttons, and changing an image type refreshes its channel purpose automatically.
- Adding content to output A defaults the format to TGA; choosing PNG shows an alpha-channel warning.
- Collapsible image rows, compact channel mapping, button-style output settings, editable final output names, and non-destructive material-slot assignment.
- One global image-list foldout, inline R/G/B/A channel editors, expanded channel summaries, and evenly aligned controls.
- Inline channel editing locks unrelated controls until OK/Cancel, operation results appear briefly, and exported files can be revealed directly in Explorer.
- Source controls stay compact: scan and model information share a row, while the global foldout and always-visible Add Image control share the next row.
- Model scans replace only prior model-derived images and preserve manually added images; source rows use Blender's native image selector and can be cleared back to two empty slots.
- Source images and materials are never overwritten.

## Usage

Open `3D Viewport > N > Faidlix > Faidlix Texture Marge`.

1. Choose Material Scan or Manual Images.
2. Add images and set each source type.
3. Open each R/G/B/A selector and enable one or more source channels.
4. Set the output purpose of each channel.
5. Choose output type, size, resize mode, format and optional name.
6. Press `1. Merge Texture`.
7. Optionally press `2. Build Copied Material`.
8. Press `3. Export Texture` to choose a file destination.
9. Use `線上更新` to sync and install the latest release from `Faidlix/BlenderAddons`.
9. Use the folder button beside the merged image name to open its last export location.

`全部重置` resets the panel only. It does not delete generated images or materials.

## Installation

Add the shared Repository URL above in Blender Extensions, then install `Faidlix Texture Marge`.
