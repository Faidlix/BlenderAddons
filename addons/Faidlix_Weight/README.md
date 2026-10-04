# Faidlix_Weight 1.3.0

Blender 5.2 add-on for copying selected Weight Paint vertex weights across the
object's local X axis.

## Usage

1. Select a mesh and enter **Weight Paint** mode.
2. Enable **Vertex Selection** and select one or more vertices.
3. Right-click in the 3D Viewport.
4. Optionally enable **Flip**, then press **MirrorSelectWeight**.

**Smart Match** is enabled by default. The add-on first looks for an exact
local-X mirror. If that fails, it searches nearby vertices using mirrored
relative position, connected-edge count, adjacent-face count, boundary state,
and normalized neighboring-edge lengths. Disable Smart Match when only exact
symmetry should be accepted.

With Flip disabled, selected weights are copied to the opposite side. With
Flip enabled, weights from the opposite side are copied onto the selected
vertices. If a mirrored pair is selected on both sides, Flip is enabled and
locked automatically, and the pair's weights are exchanged.

Vertex-group names are mirrored case-insensitively. Supported forms include
`RightHand` / `LeftHand`, `Hand.L` / `Hand.R`, `Hand_L` / `Hand_R`, and
`Hand-L` / `Hand-R`. Groups without a side marker, such as `Spine`, keep the
same name. Missing counterpart groups are created automatically.

The operation replaces each destination vertex's complete unlocked weight set.
It skips center-line vertices and vertices without a mirror match. If a locked
group would have to change, the entire operation is cancelled before any
weights are written.

## Online Update

Use **Online Update** in the Weight Paint right-click menu or
**Check and Install Online Update** in the add-on preferences. The add-on syncs
the shared Faidlix Blender Add-ons repository, compares the published version, and
downloads a newer package only when one is available.

Repository URL:

`https://raw.githubusercontent.com/Faidlix/BlenderAddons/main/repository/index.json`
