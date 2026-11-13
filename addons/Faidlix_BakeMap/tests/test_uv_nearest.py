"""Validate UV counterpart discovery and nearest similarity alignment.

Run with Blender 5.2 in background mode and set FAIDLIX_BAKEMAP_SOURCE to the
add-on's __init__.py path. The test creates two triangles split at one UV seam.
"""

import importlib.util
import os
from types import SimpleNamespace

import bmesh
import bpy


source = os.environ["FAIDLIX_BAKEMAP_SOURCE"]
spec = importlib.util.spec_from_file_location("faidlix_bakemap_uv_test", source)
addon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(addon)

# View2D accepts normalized UVs even when an image is loaded and the
# coordinates are outside the first tile. Its RNA exposes no cur rectangle.
view = SimpleNamespace(view_to_region=lambda u, v, *, clip: (u, v, clip))
context = SimpleNamespace(
    region=SimpleNamespace(view2d=view),
    space_data=SimpleNamespace(image=SimpleNamespace(size=(4096, 2048))),
)
assert addon._uv_to_region(context, (0.25, 1.35)) == (0.25, 1.35, False)


def close(first, second, epsilon=1.0e-5):
    return all(abs(first[index] - second[index]) <= epsilon for index in range(2))


mapped = addon._uv_similarity_point((0.0, 1.0), (0.0, 0.0), (1.0, 0.0), (2.0, 3.0), (2.0, 5.0))
assert close(mapped, (0.0, 3.0)), mapped

mesh = bpy.data.meshes.new("FaidlixUVNearestMesh")
mesh.from_pydata(
    [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, -1.0, 0.0)],
    [],
    [(0, 1, 2), (1, 0, 3)],
)
mesh.update()
obj = bpy.data.objects.new("FaidlixUVNearestObject", mesh)
bpy.context.scene.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
uv_layer = mesh.uv_layers.new(name="UVMap")
face_uvs = (
    {0: (0.0, 0.0), 1: (1.0, 0.0), 2: (0.0, 1.0)},
    {1: (4.0, 0.0), 0: (2.0, 0.0), 3: (4.0, -1.0)},
)
for polygon, uv_values in zip(mesh.polygons, face_uvs):
    for loop_index in polygon.loop_indices:
        vertex_index = mesh.loops[loop_index].vertex_index
        uv_layer.data[loop_index].uv = uv_values[vertex_index]

bpy.context.scene.tool_settings.use_uv_select_sync = False
bpy.context.scene.tool_settings.uv_select_mode = 'EDGE'
bpy.ops.object.mode_set(mode='EDIT')
bm = bmesh.from_edit_mesh(mesh)
bm_uv = bm.loops.layers.uv.active
for face in bm.faces:
    for loop in face.loops:
        loop.uv_select_vert_set(False)
        loop.uv_select_edge_set(False)
        if face.index == 0 and {loop.vert.index, loop.link_loop_next.vert.index} == {0, 1}:
            loop.uv_select_edge_set(True)
bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)

_bm, _layer, pairs = addon._uv_counterpart_pairs(obj, 'EDGE')
assert len(pairs) == 1, pairs
source_edge, targets = pairs[0]
assert len(targets) == 1, targets
assert source_edge['endpoints'][0][0] == 0
assert source_edge['endpoints'][1][0] == 1
assert close(source_edge['endpoints'][0][1], (0.0, 0.0))
assert close(source_edge['endpoints'][1][1], (1.0, 0.0))
assert close(targets[0]['endpoints'][0][1], (2.0, 0.0))
assert close(targets[0]['endpoints'][1][1], (4.0, 0.0))

# Sync uses the mesh selection buttons. A face counterpart is a segment.
settings = SimpleNamespace(use_uv_select_sync=True, mesh_select_mode=(False, False, True),
                           uv_select_mode='VERTEX')
assert addon._uv_selection_mode(settings) == 'FACE'
bm.faces[0].select = True
bm.faces[1].select = False
coords = addon._uv_overlay_coordinates(obj, 'FACE', True)
assert len(coords) == 2 and set(coords) == {(2.0, 0.0), (4.0, 0.0)}, coords
assert addon._uv_overlay_coordinates(obj, 'FACE', True) is coords
addon._invalidate_uv_overlay()
bm.faces[0].select = False
assert addon._uv_overlay_coordinates(obj, 'FACE', True) == ()
addon._invalidate_uv_overlay()

class RedrawArea:
    def tag_redraw(self):
        return None


class FakeContext:
    area = RedrawArea()
    scene = bpy.context.scene
    edit_object = obj
    active_object = obj


class FakeOperator:
    def report(self, _levels, _message):
        print(f"UV_NEAREST_REPORT={_message}")


result = addon.FAIDLIX_OT_uv_merge_self_to_nearest.execute(FakeOperator(), FakeContext())
assert result == {'FINISHED'}, result
bm = bmesh.from_edit_mesh(mesh)
bm_uv = bm.loops.layers.uv.active
source_loop = next(
    loop for loop in bm.faces[0].loops
    if {loop.vert.index, loop.link_loop_next.vert.index} == {0, 1}
)
self_endpoints = addon._uv_edge_endpoints(source_loop, bm_uv)
assert close(self_endpoints[0][1], (2.0, 0.0))
assert close(self_endpoints[1][1], (4.0, 0.0))

# Restore the split seam, then verify whole-island translation/rotation/scale.
for face in bm.faces:
    values = face_uvs[face.index]
    for loop in face.loops:
        loop[bm_uv].uv = values[loop.vert.index]
        loop.uv_select_edge_set(bool(
            face.index == 0 and {loop.vert.index, loop.link_loop_next.vert.index} == {0, 1}
        ))
bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
result = addon.FAIDLIX_OT_uv_merge_island_to_nearest.execute(FakeOperator(), FakeContext())
assert result == {'FINISHED'}, result
bm = bmesh.from_edit_mesh(mesh)
bm_uv = bm.loops.layers.uv.active
face_zero = bm.faces[0]
coords = {loop.vert.index: tuple(loop[bm_uv].uv) for loop in face_zero.loops}
assert close(coords[0], (2.0, 0.0))
assert close(coords[1], (4.0, 0.0))
assert close(coords[2], (2.0, 2.0))

bpy.ops.object.mode_set(mode='OBJECT')
bpy.data.objects.remove(obj, do_unlink=True)
bpy.data.meshes.remove(mesh)

# Use a fresh edit mesh for vertex mode; changing UV selection modes in
# background mode clears the previous mesh's synthetic selection state.
vertex_mesh = bpy.data.meshes.new("FaidlixUVNearestVertexMesh")
vertex_mesh.from_pydata(
    [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, -1.0, 0.0)],
    [],
    [(0, 1, 2), (1, 0, 3)],
)
vertex_mesh.update()
vertex_obj = bpy.data.objects.new("FaidlixUVNearestVertexObject", vertex_mesh)
bpy.context.scene.collection.objects.link(vertex_obj)
bpy.context.view_layer.objects.active = vertex_obj
vertex_obj.select_set(True)
vertex_uv_layer = vertex_mesh.uv_layers.new(name="UVMap")
for polygon, uv_values in zip(vertex_mesh.polygons, face_uvs):
    for loop_index in polygon.loop_indices:
        vertex_index = vertex_mesh.loops[loop_index].vertex_index
        vertex_uv_layer.data[loop_index].uv = uv_values[vertex_index]
bpy.context.scene.tool_settings.uv_select_mode = 'VERTEX'
bpy.ops.object.mode_set(mode='EDIT')
bm = bmesh.from_edit_mesh(vertex_mesh)
bm.faces.ensure_lookup_table()
bm_uv = bm.loops.layers.uv.active
for face in bm.faces:
    for loop in face.loops:
        loop.uv_select_vert_set(face.index == 0 and loop.vert.index == 0)
bmesh.update_edit_mesh(vertex_mesh, loop_triangles=False, destructive=False)
_bm, _layer, vertex_pairs = addon._uv_counterpart_pairs(vertex_obj, 'VERTEX')
assert len(vertex_pairs) == 1, vertex_pairs

class VertexContext:
    area = RedrawArea()
    scene = bpy.context.scene
    edit_object = vertex_obj
    active_object = vertex_obj


result = addon.FAIDLIX_OT_uv_merge_island_to_nearest.execute(FakeOperator(), VertexContext())
assert result == {'FINISHED'}, result
bm = bmesh.from_edit_mesh(vertex_mesh)
bm_uv = bm.loops.layers.uv.active
coords = {loop.vert.index: tuple(loop[bm_uv].uv) for loop in bm.faces[0].loops}
assert close(coords[0], (2.0, 0.0))
assert close(coords[1], (3.0, 0.0))
assert close(coords[2], (2.0, 1.0))
bpy.ops.object.mode_set(mode='OBJECT')
bpy.data.objects.remove(vertex_obj, do_unlink=True)
bpy.data.meshes.remove(vertex_mesh)
print("FAIDLIX_BAKEMAP_UV_NEAREST_TEST=PASS")
