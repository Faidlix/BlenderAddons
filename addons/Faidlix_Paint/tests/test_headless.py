import importlib.util
import pathlib
import sys
from array import array
import bpy
from mathutils import Vector

root = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("faidlix_paint", root / "__init__.py")
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)

addon.register()
assert hasattr(bpy.types.Scene, "faidlix_paint")
assert hasattr(bpy.ops.faidlix_paint, "fill")
assert hasattr(bpy.ops.faidlix_paint, "online_update")
assert hasattr(bpy.ops.faidlix_paint, "mask_to_image")
assert addon.ADDON_VERSION == (0, 4, 8)
assert addon.GITHUB_REPOSITORY_URL.endswith("Faidlix/BlenderAddons/main/repository/index.json")
assert hasattr(bpy.ops.ui, "eyedropper_color")
assert "prop_data_path" in bpy.ops.ui.eyedropper_color.get_rna_type().properties.keys()
assert "faidlix_paint.eyedropper_view3d" not in addon._TOOL_SYNC

from bl_ui.space_toolsystem_common import ToolSelectPanelHelper
from bl_ui.space_toolsystem_common import ToolDef
toolbar = ToolSelectPanelHelper._tool_class_from_space_type('VIEW_3D')
assert toolbar._tools['PAINT_TEXTURE'][0].idname == "faidlix_paint.update_view3d"
assert toolbar._tools['PAINT_TEXTURE'][1] is None
fill_group = next(
    item for item in toolbar._tools['PAINT_TEXTURE']
    if isinstance(item, tuple) and not isinstance(item, ToolDef)
    and any(getattr(entry, "idname", "") == "builtin_brush.fill" for entry in item)
)
assert [entry.idname for entry in fill_group] == [
    "builtin_brush.fill", "faidlix_paint.island_view3d"
]
image_toolbar = ToolSelectPanelHelper._tool_class_from_space_type('IMAGE_EDITOR')
image_fill_group = next(
    item for item in image_toolbar._tools['PAINT']
    if isinstance(item, tuple) and not isinstance(item, ToolDef)
    and any(getattr(entry, "idname", "") == "builtin_brush.fill" for entry in item)
)
assert [entry.idname for entry in image_fill_group] == [
    "builtin_brush.fill", "faidlix_paint.island_image"
]
assert addon.FAIDLIXPAINT_WST_island_view3d._bl_tool.options is None
view3d_tools = toolbar._tools['PAINT_TEXTURE']
eyedropper_index = next(i for i, item in enumerate(view3d_tools)
                        if getattr(item, "idname", "") == "faidlix_paint.eyedropper_view3d")
assert eyedropper_index == len(view3d_tools) - 1
assert view3d_tools[eyedropper_index - 1] is None
mask_group = next(
    item for item in toolbar._tools['PAINT_TEXTURE']
    if isinstance(item, tuple) and not isinstance(item, ToolDef)
    and any(getattr(entry, "idname", "") == "builtin_brush.mask" for entry in item)
)
assert [entry.idname for entry in mask_group] == [
    "builtin_brush.mask", "faidlix_paint.mask_brush_view3d",
    "faidlix_paint.mask_island_view3d", "faidlix_paint.mask_lasso_view3d",
    "faidlix_paint.mask_box_view3d", "faidlix_paint.mask_circle_view3d"
]
assert 'USE_BRUSHES' in addon.FAIDLIXPAINT_WST_mask_brush_view3d._bl_tool.options
mask_keymap = addon.FAIDLIXPAINT_WST_mask_lasso_view3d._bl_tool.keymap
tool_keymap = bpy.context.window_manager.keyconfigs.addon.keymaps.get(mask_keymap[0])
assert tool_keymap is not None
assert any(item.idname == "faidlix_paint.mask_edit" and item.ctrl
           for item in tool_keymap.keymap_items)
ctrl_mask_item = next(item for item in tool_keymap.keymap_items
                      if item.idname == "faidlix_paint.mask_edit" and item.ctrl)
assert ctrl_mask_item.properties.erase is True
mask_items = [item for item in tool_keymap.keymap_items
              if item.idname == "faidlix_paint.mask_edit"]
assert mask_items[0].ctrl and mask_items[0].properties.erase is True
addon_keymaps = bpy.context.window_manager.keyconfigs.addon.keymaps
assert any(item.idname == "faidlix_paint.activate_eyedropper" and item.type == 'C'
           for keymap in addon_keymaps for item in keymap.keymap_items)
shortcut_maps = {keymap.name: keymap.space_type for keymap in addon_keymaps
                 if any(item.idname == "faidlix_paint.activate_eyedropper"
                        for item in keymap.keymap_items)}
assert shortcut_maps["3D View"] == 'VIEW_3D'
assert shortcut_maps["Image Paint"] == 'EMPTY'

covered = addon._rasterized_pixels(4, 4, [((0.0, 0.0), (1.0, 0.0), (0.0, 1.0))])
assert 0 in covered
assert 15 not in covered
assert len(addon._expand_pixels({5}, 4, 4, 1)) == 5
assert addon._point_in_polygon((0.25, 0.25), [(0, 0), (1, 0), (1, 1), (0, 1)])
assert not addon._point_in_polygon((1.25, 0.25), [(0, 0), (1, 0), (1, 1), (0, 1)])
test_pixels = array('f', [0.0, 0.0, 1.0, 1.0])
addon._blend(test_pixels, 0, (1.0, 0.0, 0.0, 0.5))
assert tuple(round(v, 3) for v in test_pixels) == (1.0, 0.0, 0.0, 0.5)
test_pixels = array('f', [0.0, 0.0, 1.0, 1.0])
addon._blend(test_pixels, 0, (1.0, 0.0, 0.0, 1.0), 0.5, 'MIX')
assert tuple(round(v, 3) for v in test_pixels) == (0.5, 0.0, 0.5, 1.0)
test_pixels = array('f', [0.25, 0.5, 0.75, 1.0])
addon._blend(test_pixels, 0, (0.5, 0.5, 0.5, 1.0), 1.0, 'MUL')
assert tuple(round(v, 3) for v in test_pixels[:3]) == (0.125, 0.25, 0.375)

mesh = bpy.data.meshes.new("TwoUvIslands")
mesh.from_pydata(
    [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
     (2, 0, 0), (3, 0, 0), (3, 1, 0), (2, 1, 0)],
    [], [(0, 1, 2, 3), (4, 5, 6, 7)])
uv = mesh.uv_layers.new(name="UVMap")
coords = [(0.0, 0.0), (0.4, 0.0), (0.4, 1.0), (0.0, 1.0),
          (0.6, 0.0), (1.0, 0.0), (1.0, 1.0), (0.6, 1.0)]
for loop, value in zip(uv.data, coords):
    loop.uv = value
assert addon._seed_from_uv(mesh, (0.2, 0.5)) == 0
assert [poly.index for poly in addon._uv_island(mesh, 0)] == [0]
assert [poly.index for poly in addon._uv_island(mesh, 1)] == [1]

# Modifier regression: ray-cast face indices belong to evaluated geometry and
# must be resolved against the evaluated mesh/UV layer, not the source mesh.
modifier_obj = bpy.data.objects.new("EvaluatedUvObject", mesh)
bpy.context.scene.collection.objects.link(modifier_obj)
subsurf = modifier_obj.modifiers.new("Subdivision", 'SUBSURF')
subsurf.levels = 2
evaluated = modifier_obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
evaluated_mesh = evaluated.data
assert len(evaluated_mesh.polygons) > len(mesh.polygons)
evaluated_uv = addon._uv_data(evaluated_mesh)
assert evaluated_uv is not None
assert max(loop for poly in evaluated_mesh.polygons for loop in poly.loop_indices) < len(evaluated_uv)
import gpu
gpu.init()
mask_shader = addon._get_mask_gpu_shader()
assert mask_shader is not None
image_mask_shader = addon._get_mask_image_gpu_shader()
assert image_mask_shader is not None
assert addon._mask_gpu_batch(modifier_obj, mask_shader) is not None

image = bpy.data.images.new("FaidlixPaintTest", width=4, height=4, alpha=True)
bpy.context.scene.faidlix_paint.color = (1.0, 0.0, 0.0, 1.0)
mask = addon._mask_image(image, create=True)
assert tuple(mask.size[:]) == (4, 4)
addon._write_mask(image, {5, 6})
mask_pixels = array('f', [0.0]) * 64
mask.pixels.foreach_get(mask_pixels)
assert mask_pixels[5 * 4 + 1] == 1.0 and mask_pixels[5 * 4] == 1.0
addon._write_mask(image, {5}, 0.0)
mask.pixels.foreach_get(mask_pixels)
assert mask_pixels[5 * 4 + 1] == 0.0 and mask_pixels[6 * 4 + 1] == 1.0
addon._write_all_mask(image, 1.0)
mask.pixels.foreach_get(mask_pixels)
assert all(mask_pixels[index * 4 + 1] == 1.0 for index in range(16))
addon._write_all_mask(image, 0.0)
mask.pixels.foreach_get(mask_pixels)
assert all(mask_pixels[index * 4 + 1] == 0.0 for index in range(16))
addon._write_mask(image, {0}, 1.0, strength=0.25)
mask.pixels.foreach_get(mask_pixels)
assert abs(mask_pixels[1] - 0.25) < 0.01
assert addon._mask_protected_indices(mask, 16) == {0}
assert addon._mask_horizontal_runs(mask) == [(0, 0, 1)]

feather_source = bpy.data.images.new("FaidlixFeatherTest", width=5, height=1, alpha=True)
bpy.context.scene.faidlix_paint.mask_feather = 1
addon._write_mask(feather_source, {2}, 1.0)
feather_mask = addon._mask_image(feather_source, create=False)
feather_pixels = array('f', [0.0]) * 20
feather_mask.pixels.foreach_get(feather_pixels)
assert feather_pixels[2 * 4] == 1.0
assert feather_pixels[1 * 4] == 0.0
assert 0.0 < feather_pixels[1 * 4 + 1] < 1.0
assert 0.0 < feather_pixels[2 * 4 + 1] < 1.0
mask_bw = addon._mask_to_bw_image(feather_source)
bw_pixels = array('f', [0.0]) * 20
mask_bw.pixels.foreach_get(bw_pixels)
assert bw_pixels[1 * 4] == bw_pixels[1 * 4 + 1] == bw_pixels[1 * 4 + 2]
bpy.context.scene.faidlix_paint.mask_feather = 0
assert addon._lasso_preview["erase"] is False
assert addon._circle_pixels(4, 4, (0.5, 0.5), 1)
assert addon._lasso_pixels(4, 4, [(0, 0), (0.5, 0), (0.5, 0.5), (0, 0.5)])
assert addon._uv_inside_image((0.0, 1.0))
assert not addon._uv_inside_image((-0.01, 0.5))
assert addon._TOOL_SYNC['faidlix_paint.mask_brush_view3d'] == \
    'faidlix_paint.mask_brush_image'
assert addon._adaptive_subdivisions(
    [Vector((0.0, 0.0)), Vector((800.0, 0.0)), Vector((0.0, 600.0))]) > 4
assert addon.FAIDLIXPAINT_WST_update_view3d._bl_tool.icon == \
    "ops.mesh.primitive_sphere_add_gizmo"

for area in bpy.context.screen.areas if bpy.context.screen else []:
    if area.type == 'IMAGE_EDITOR':
        area.spaces.active.image = image

assert image.is_dirty is False
addon.unregister()
assert not hasattr(bpy.types.Scene, "faidlix_paint")
remaining_ids = []
for item in toolbar._tools['PAINT_TEXTURE']:
    entries = (item,) if isinstance(item, ToolDef) else (item if isinstance(item, tuple) else (item,))
    remaining_ids.extend(getattr(entry, "idname", "") for entry in entries)
assert "builtin_brush.fill" in remaining_ids
assert not any(name.startswith("faidlix_paint.") for name in remaining_ids)
print("FAIDLIX_PAINT_HEADLESS_OK")
