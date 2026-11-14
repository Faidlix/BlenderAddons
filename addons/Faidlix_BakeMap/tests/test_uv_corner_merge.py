"""Run in Blender background mode to check face-mode two-edge UV stitching."""

import runpy
from pathlib import Path
from types import SimpleNamespace

import bmesh
import bpy

addon = runpy.run_path(str(Path(__file__).resolve().parents[1] / "__init__.py"))
bpy.ops.object.select_all(action='DESELECT')
mesh = bpy.data.meshes.new("Corner")
mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)],
                 [], [(0, 1, 2, 3), (2, 1, 0)])
obj = bpy.data.objects.new("Corner", mesh)
bpy.context.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
mesh.uv_layers.new()
settings = bpy.context.scene.tool_settings
settings.use_uv_select_sync = True
settings.mesh_select_mode = (False, False, True)
bpy.ops.object.mode_set(mode='EDIT')
context = SimpleNamespace(edit_object=obj, active_object=obj, scene=bpy.context.scene,
                          area=SimpleNamespace(tag_redraw=lambda: None))
operator = SimpleNamespace(report=lambda *_: None)
source = {0: (0, 0), 1: (1, 0), 2: (1, 1), 3: (0, 1)}
target = {0: (2, 0), 1: (4, 0), 2: (5, 3)}
for kind in ("self", "island"):
    bm = bmesh.from_edit_mesh(mesh)
    layer = bm.loops.layers.uv.active
    for face in bm.faces:
        face.select_set(len(face.loops) == 4)
        for loop in face.loops:
            loop[layer].uv = (source if len(face.loops) == 4 else target)[loop.vert.index]
    bmesh.update_edit_mesh(mesh)
    cls = addon[f"FAIDLIX_OT_uv_merge_{kind}_to_nearest"]
    assert cls.execute(operator, context) == {'FINISHED'}
    for face in bm.faces:
        coords = {loop.vert.index: tuple(loop[layer].uv) for loop in face.loops}
        expected = dict(target)
        if len(face.loops) == 4:
            expected[3] = (0, 1) if kind == "self" else (3, 3)
        assert coords == expected, (kind, coords, expected)
    print("TWO EDGE PASS", kind)

bpy.ops.object.mode_set(mode='OBJECT')
bpy.ops.object.select_all(action='DESELECT')
bpy.ops.mesh.primitive_cube_add()
obj = bpy.context.object
context.edit_object = context.active_object = obj
bpy.ops.object.mode_set(mode='EDIT')
bm = bmesh.from_edit_mesh(obj.data)
layer = bm.loops.layers.uv.active
patch = next(iter(bm.faces))
for kind in ("self", "island"):
    for face in bm.faces:
        face.select_set(face == patch)
        for loop in face.loops:
            x, y, z = loop.vert.co
            loop[layer].uv = (x + 0.3 * z, y + 0.7 * z)
    patch.loops[0][layer].uv.x += 0.5
    bmesh.update_edit_mesh(obj.data)
    assert len(addon["_uv_face_components"](bm, layer)[1]) == 1
    fixed = {loop: tuple(loop[layer].uv) for face in bm.faces if face != patch for loop in face.loops}
    _, _, candidates = addon["_uv_counterpart_pairs"](obj, 'FACE', True)
    assert candidates
    joined = [(loop, other) for loop in patch.loops for other in loop.edge.link_loops
              if other.face != patch and addon["_uv_faces_share_representation"](loop, other, layer)]
    before = [loop[layer].uv.copy() for loop in patch.loops]
    cls = addon[f"FAIDLIX_OT_uv_merge_{kind}_to_nearest"]
    assert cls.execute(operator, context) == {'FINISHED'}
    if kind == "self":
        assert all(addon["_uv_faces_share_representation"](a, b, layer) for a, b in joined)
    else:
        assert all(addon["_uv_faces_share_representation"](a, b, layer) for a, b in joined)
        after = [loop[layer].uv.copy() for loop in patch.loops]
        scale = (after[0] - after[1]).length / (before[0] - before[1]).length
        for i in range(len(before)):
            for j in range(i):
                assert abs((after[i] - after[j]).length - scale * (before[i] - before[j]).length) < 1e-5
    assert any(addon["_uv_faces_share_representation"](source['loops'][0], target['loops'][0], layer)
               for source, targets in candidates for target in targets)
    print("SAME ISLAND PASS", kind)
