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
