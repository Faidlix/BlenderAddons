"""Run UV split and move regression in a standalone Blender window.

Launch Blender with factory settings and --python this file. The script
opens a UV Editor, waits for actual redraws, then splits and moves a face.
"""

import runpy
from pathlib import Path

import bmesh
import bpy

addon = runpy.run_path(str(Path(__file__).resolve().parents[1] / "__init__.py"))
addon["register"]()
obj = bpy.context.object
ts = bpy.context.tool_settings
ts.use_uv_select_sync = True
ts.mesh_select_mode = (False, False, True)
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='DESELECT')
bm = bmesh.from_edit_mesh(obj.data)
next(iter(bm.faces)).select_set(True)
bmesh.update_edit_mesh(obj.data)
area = next(area for area in bpy.context.screen.areas if area.type == 'VIEW_3D')
area.type = 'IMAGE_EDITOR'
area.spaces.active.mode = 'UV'
region = next(region for region in area.regions if region.type == 'WINDOW')
draws = 0
stage = 0
previous_draws = 0


def count_draw():
    global draws
    draws += 1


handle = bpy.types.SpaceImageEditor.draw_handler_add(count_draw, (), 'WINDOW', 'POST_PIXEL')


def step():
    global stage, previous_draws
    try:
        assert draws > previous_draws, "UV Editor did not redraw"
        previous_draws = draws
        with bpy.context.temp_override(area=area, region=region):
            coords = addon["_uv_overlay_coordinates"]
            assert bpy.context.scene.faidlix_bakemap.show_uv_counterparts
            if stage == 0:
                assert coords(obj, 'FACE', True), "Expected an initial seam"
                assert bpy.ops.mesh.split() == {'FINISHED'}
                assert coords(obj, 'FACE', True) == (), "Stale counterpart after split"
            elif stage == 1:
                assert bpy.ops.transform.translate(value=(0.3, 0, 0)) == {'FINISHED'}
            else:
                assert coords(obj, 'FACE', True) == ()
                print("FAIDLIX_UV_SPLIT_WINDOW=PASS", flush=True)
                bpy.types.SpaceImageEditor.draw_handler_remove(handle, 'WINDOW')
                bpy.ops.wm.quit_blender()
                return None
        stage += 1
        area.tag_redraw()
        return 0.75
    except Exception:
        import traceback
        traceback.print_exc()
        bpy.ops.wm.quit_blender()
        return None


bpy.app.timers.register(step, first_interval=2.0)
