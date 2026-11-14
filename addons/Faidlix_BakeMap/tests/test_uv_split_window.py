"""Run the UV Editor face drag regression in a standalone Blender window.

Launch with --factory-startup --enable-event-simulate --python this file.
The script invokes the native modal move, sends mouse motion to the UV Editor,
and checks all UVs.
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
first = next(iter(bm.faces))
first.select_set(True)
layer = bm.loops.layers.uv.active
for loop in first.loops:
    loop[layer].uv.x += 0.2
bmesh.update_edit_mesh(obj.data)
area = next(area for area in bpy.context.screen.areas if area.type == 'VIEW_3D')
area.type = 'IMAGE_EDITOR'
area.spaces.active.mode = 'UV'
region = next(region for region in area.regions if region.type == 'WINDOW')
draws = 0
stage = 0
previous_draws = 0
window = bpy.context.window
before = None


def snapshot():
    mesh = bmesh.from_edit_mesh(obj.data)
    uv = mesh.loops.layers.uv.active
    return [(face.select, tuple(tuple(loop[uv].uv) for loop in face.loops))
            for face in mesh.faces]


def count_draw():
    global draws
    draws += 1


handle = bpy.types.SpaceImageEditor.draw_handler_add(count_draw, (), 'WINDOW', 'POST_PIXEL')


def step():
    global stage, previous_draws, before
    try:
        x = region.x + region.width // 2
        y = region.y + region.height // 2
        assert draws > previous_draws, "UV Editor did not redraw"
        previous_draws = draws
        with bpy.context.temp_override(area=area, region=region):
            coords = addon["_uv_overlay_coordinates"]
            assert bpy.context.scene.faidlix_bakemap.show_uv_counterparts
            if stage == 0:
                assert coords(obj, 'FACE', True), "Expected an initial seam"
                before = snapshot()
                assert sum(selected for selected, _ in before) == 1
                window.event_simulate(type='MOUSEMOVE', value='NOTHING', x=x, y=y)
                assert bpy.ops.transform.translate('INVOKE_DEFAULT') == {'RUNNING_MODAL'}
            elif stage <= 8:
                modal = [op.bl_idname for op in window.modal_operators]
                assert 'TRANSFORM_OT_translate' in modal, (modal, x, y, region.width, region.height)
                window.event_simulate(type='MOUSEMOVE', value='NOTHING', x=x + stage * 6, y=y)
            elif stage == 9:
                window.event_simulate(type='LEFTMOUSE', value='PRESS', x=x + 48, y=y)
            else:
                after = snapshot()
                assert len(before) == len(after)
                for (selected, original), (still_selected, current) in zip(before, after):
                    assert selected == still_selected
                    assert all((old != new) == selected for old, new in zip(original, current))
                assert coords(obj, 'FACE', True)
                print("FAIDLIX_UV_DRAG_WINDOW=PASS", flush=True)
                bpy.types.SpaceImageEditor.draw_handler_remove(handle, 'WINDOW')
                bpy.ops.wm.quit_blender()
                return None
        stage += 1
        area.tag_redraw()
        return 0.2
    except Exception:
        import traceback
        traceback.print_exc()
        bpy.ops.wm.quit_blender()
        return None


bpy.app.timers.register(step, first_interval=2.0)
