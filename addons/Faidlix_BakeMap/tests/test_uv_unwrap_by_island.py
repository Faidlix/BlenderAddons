"""Run in Blender background mode to verify all ByIsland unwrap methods."""

import runpy
from pathlib import Path
from types import SimpleNamespace

import bmesh
import bpy

addon = runpy.run_path(str(Path(__file__).resolve().parents[1] / "__init__.py"))
addon["register"]()
area = next(area for area in bpy.context.screen.areas if area.type == 'VIEW_3D')
area.type = 'IMAGE_EDITOR'
area.spaces.active.mode = 'UV'
region = next(region for region in area.regions if region.type == 'WINDOW')


class MenuRecorder:
    def __init__(self):
        self.labels = []

    def operator(self, identifier, *, text=None):
        self.labels.append(text)
        return SimpleNamespace()

    def separator(self):
        pass


menu = MenuRecorder()
with bpy.context.temp_override(area=area, region=region):
    bpy.types.IMAGE_MT_uvs_unwrap.draw(SimpleNamespace(layout=menu), bpy.context)
assert menu.labels[:6] == [
    f"Unwrap {label}{suffix}"
    for _, label, _ in addon["_UV_ISLAND_UNWRAP_METHODS"]
    for suffix in ("", " ByIsland")
]


def bounds_center(coords):
    return tuple((min(p[i] for p in coords) + max(p[i] for p in coords)) / 2 for i in range(2))


bpy.context.tool_settings.mesh_select_mode = (False, False, True)

for method, _, _ in addon["_UV_ISLAND_UNWRAP_METHODS"]:
    for partial in (False, True):
        bpy.ops.object.select_all(action='DESELECT')
        mesh = bpy.data.meshes.new("ByIsland")
        mesh.from_pydata([(0,0,0), (1,0,0), (2,0,0), (0,1,0), (1,1,0), (2,1,0)],
                         [], [(0,1,4,3), (1,2,5,4)])
        obj = bpy.data.objects.new("ByIsland", mesh)
        bpy.context.collection.objects.link(obj)
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        mesh.uv_layers.new()
        bpy.context.tool_settings.use_uv_select_sync = not partial
        bpy.context.tool_settings.uv_select_mode = 'FACE'
        bpy.ops.object.mode_set(mode='EDIT')
        bm = bmesh.from_edit_mesh(mesh)
        layer = bm.loops.layers.uv.active
        for index, face in enumerate(bm.faces):
            face.select_set(True)
            for loop, (u, v) in zip(face.loops, [(0,0), (.2,0), (.3,.4), (0,.4)]):
                loop[layer].uv = (u + index * .6, v)
            if partial:
                face.uv_select_set(index == 0)
        bmesh.update_edit_mesh(mesh)
        before = [tuple(tuple(loop[layer].uv) for loop in face.loops) for face in bm.faces]
        assert not any(edge.seam for edge in bm.edges)
        assert len(addon["_uv_face_components"](bm, layer)[1]) == 2
        with bpy.context.temp_override(area=area, region=region):
            assert bpy.ops.faidlix.uv_unwrap_by_island(method=method) == {'FINISHED'}
        assert not any(edge.seam for edge in bm.edges)
        assert len(addon["_uv_face_components"](bm, layer)[1]) == 2, method
        after = [tuple(tuple(loop[layer].uv) for loop in face.loops) for face in bm.faces]
        assert before[0] != after[0]
        assert (before[1] == after[1]) == partial, (method, partial)
        for old, new in zip(before, after):
            assert all(abs(a - b) < 1e-6 for a, b in zip(bounds_center(old), bounds_center(new)))
        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.meshes.remove(mesh)
    print("BYISLAND PASS", method)
