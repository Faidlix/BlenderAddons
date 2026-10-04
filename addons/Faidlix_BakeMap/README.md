# Faidlix_BakeMap 2.3.9

Canonical source and updates: https://github.com/Faidlix/BlenderAddons

The add-on is distributed through a Blender Extension repository hosted on
GitHub. The first panel row contains equal-width **全部重置** and
**線上更新** buttons. The update button checks the GitHub `main` repository,
installs a newer package after the button operator returns. Blender must be
restarted before relying on the updated extension. Progress messages replace the
update button text. The controls respect Blender's **Allow Online Access**
preference and do not enable network access automatically.

The main N-panel is collapsed by default. Online installation is deferred until
the update button event has finished. The add-on never accesses its own Blender
RNA after asking Blender to install its replacement and never manually reloads
itself inside the running UI. Restart Blender after an installed update.

Bake map choices, roughness output, image sizes, diffuse contributions, and
source scopes use direct toggle buttons in the sidebar. Size labels are
abbreviated to 256, 512, 1024, 2048, and 4096; Custom reveals width and height
fields. Size controls use a fixed three-column layout so every button label
remains visible at normal sidebar widths. Combined remains supported internally but is currently hidden from the
Bake Maps interface.

Blender 5.2 add-on for baking one or more `ReferenceObject` meshes to one
`TargetObject`. The panel is available only in **3D Viewport > Sidebar >
Faidlix**.

Each completed bake pass rebuilds the target material connections from every
enabled map that already exists. Diffuse and Normal therefore remain connected
together after the Normal pass completes, and complex copied materials always
use the Principled BSDF that actually drives the active Material Output.

Before baking, the add-on checks image files used by the selected Reference
materials. If one is missing, it stops before changing Target geometry or
materials and reports the affected image. Use **File > External Data > Find
Missing Files** to locate it, then retry. Background Bake also restores
relative image paths when its temporary scene snapshot is opened elsewhere.

Roughness can use a separate image or be packed into the Metallic image alpha.
Packed mode also bakes Metallic into RGB and uses the Roughness size for the
combined image. The copied Target material connects Metallic RGB to Principled
Metallic and Metallic Alpha to Principled Roughness; the intermediate Roughness
image is kept only to support rebaking and is excluded from Pack.

When a 3D Viewport uses Local View, the add-on temporarily includes the
Reference and Target in that view for baking, then restores their original
Local View membership afterward, including on bake failure.

Bake material and image names are deterministic. Partial Bake uses the target,
source material, and map name; Multi Material additionally includes the target
slot. Re Bake keeps those names instead of creating `.001`/`.002` copies, and
Background Bake replaces unused older bake datablocks before restoring the
same stable names.

`全部重置` at the top of the panel restores every add-on option to its default
and clears the Reference/Target fields without deleting scene data. Selecting a
Target automatically uses its object name as the default texture name; clearing
the Target clears that name. `Match Target Normals to Reference` compares each
Target face with the nearest Reference surface and reverses only opposing faces
before foreground or background baking.

## Background Bake

Background Bake saves a temporary scene snapshot and runs each selected map in
a separate hidden Blender process. Reference, target, shared-mesh, and
shared-material objects are temporarily locked against normal viewport
selection while unrelated scene work remains available. Before applying a
result, the add-on verifies a fingerprint of geometry, transforms, UVs, source
scope, vertex-group weights, modifiers, materials, nodes, links, and image
references.

The running panel shows the current map and completed count. Cancel stops the
background Blender and restores the original object lock states. Maps completed
before cancellation or an unexpected interruption remain recoverable when the
scene fingerprint still matches. Job records and map files are kept under the
system temporary `Faidlix_BakeMap` directory so a reopened Blender session can
detect interrupted or completed work.

## Reference Objects

- Add or remove complete `ReferenceObject + Scope` rows.
- After an object is selected, each ReferenceObject and TargetObject row keeps
  the object name/clear control plus Viewport Eyedropper, Scene Search, and
  External File buttons.
- The eyedropper can pick from the 3D Viewport or accept a mesh selected in the
  Outliner.
- `Reset ReferenceObjects` clears add-on references without deleting scene data.
- Scope uses same-row buttons for Automatic, Material Slot, and Vertex Group.
- Scene and external `.blend`, `.fbx`, `.obj`, `.glb`, and `.gltf` meshes are
  supported.

## Workflows

### Partial Bake

The default workflow. It projects the selected area of a full source model to
an extracted or re-UV target, such as a complete head to a separate face mesh.
Material Slot and Vertex Group scopes are isolated with temporary source
copies; the original source geometry and materials are not modified.

### Multi Material

Available when the references contain multiple objects or materials. Source
materials are mapped to target material slots. Each target slot receives a new
material copy and separate generated images, so UVs may overlap between
different materials. Every material/map image has its own preset or custom
width and height. Reference materials are never assigned directly to the
target.

### Single Atlas

Available under the same multi-source conditions. All source objects and
materials are baked into one copied target material and one image per enabled
map type. Use a non-overlapping target UV layout for this workflow.

## Bake maps and output

Diffuse, Normal, Emit, Combined, Metallic, and Roughness are supported.
Diffuse contributions, Normal Space, Selected to Active, Extrusion, Max Ray
Distance, and Margin remain configurable. Smart UV Project, Lightmap Pack, and
Pack Islands use the approved fixed settings.

All enabled maps are rebuilt as one material network after every pass:
Diffuse/Combined feed Base Color, Normal passes through a Normal Map node,
Emit feeds Emission Color, and Metallic/Roughness feed their matching inputs.
When Diffuse and Combined are both enabled, both textures connect through a
selector with Diffuse as the visible default. Disabling a map disconnects its
previous texture node on the next bake/reconnect.

`New Bake Material` creates only the selected images and node connections.
`Re Bake Map` reuses those materials and images; enabling another map later
adds only the missing output. `Pack` packs every generated image used by the
target's bake materials.

Metallic and Roughness are temporarily routed to grayscale Diffuse Color on
source-material copies, then restored. Object selection, mode, render engine,
viewport visibility, render visibility, and per-view-layer hidden state are
restored after success or failure.

