"""Test browser opt-in and scoped deletion; run with Blender --factory-startup --python this file.

With a window, pass --enable-event-simulate to check native Undo.
"""
import importlib
import os
from pathlib import Path
import sys
import traceback

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
addon = importlib.import_module(os.environ.get('BCK_TEST_MODULE', 'Faidlix_BatchCleanKey'))
if not hasattr(bpy.types.WindowManager, 'faidlix_batch_clean_key'):
    addon.register()


def make_rig(name):
    obj = bpy.data.objects.new(name, bpy.data.armatures.new(name))
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    bone = obj.data.edit_bones.new('Bone')
    bone.tail = (0, 0, 1)
    bpy.ops.object.mode_set(mode='OBJECT')
    return obj


def make_action(name, obj):
    action = bpy.data.actions.new(name)
    slot = action.slots.new('OBJECT', obj.name)
    bag = action.layers.new('Layer').strips.new(type='KEYFRAME').channelbag(slot, ensure=True)
    bag.fcurves.new('location', index=0).keyframe_points.insert(1, 0)
    action.use_fake_user = True
    return action


def check():
    context = bpy.context
    scene = context.scene
    state = context.window_manager.faidlix_batch_clean_key
    rig = make_rig('BrowserRig')
    other = make_rig('OtherBrowserRig')
    first = make_action('BrowserFirst', rig)
    second = make_action('BrowserSecond', rig)
    unrelated = make_action('BrowserUnrelated', other)
    rig.animation_data_create().action = first
    context.view_layer.objects.active = other
    state.target_armature = rig
    addon.ui.sync_timer()
    assert state.target_armature == rig
    assert not scene.faidlix_action_browser_enabled
    assert not bpy.ops.faidlix_batch_clean_key.delete_all_actions.poll()
    state.browser_index = next(i for i, row in enumerate(state.browser) if row.action == second)
    assert rig.animation_data.action == first
    assert rig.mode == 'OBJECT'
    context.view_layer.objects.active = None
    scene.faidlix_action_browser_enabled = True
    assert bpy.ops.faidlix_batch_clean_key.delete_all_actions.poll()
    assert {row.action for row in state.browser} == {first, second}
    if not bpy.app.background:
        return
    assert bpy.ops.faidlix_batch_clean_key.delete_all_actions() == {'FINISHED'}
    assert not state.browser and not rig.animation_data.action
    assert bpy.data.actions.get('BrowserUnrelated') == unrelated
    print('BROWSER_TOGGLE_PASS', flush=True)


if bpy.app.background:
    check()
else:
    steps = 0

    def run():
        global steps
        try:
            area = next(area for area in bpy.context.screen.areas if area.type == 'VIEW_3D')
            region = next(region for region in area.regions if region.type == 'WINDOW')
            with bpy.context.temp_override(area=area, region=region):
                if steps == 0:
                    check()
                    bpy.ops.ed.undo_push(message='Before deleting Action list')
                    event = bpy.context.window.event_simulate
                    event(type='MOUSEMOVE', value='NOTHING', x=region.x+region.width//2,
                          y=region.y+region.height//2)
                elif steps == 1:
                    assert bpy.ops.faidlix_batch_clean_key.delete_all_actions('INVOKE_DEFAULT') == {'RUNNING_MODAL'}
                elif steps == 2:
                    assert 'BrowserFirst' in bpy.data.actions
                    bpy.context.window.event_simulate(type='RET', value='PRESS')
                elif steps == 3:
                    assert 'BrowserFirst' not in bpy.data.actions and 'BrowserSecond' not in bpy.data.actions
                    assert 'BrowserUnrelated' in bpy.data.actions
                    assert bpy.ops.ed.undo() == {'FINISHED'}
                else:
                    assert bpy.data.objects['BrowserRig'].animation_data.action.name == 'BrowserFirst'
                    assert {'BrowserFirst', 'BrowserSecond', 'BrowserUnrelated'} <= set(bpy.data.actions.keys())
                    print('BROWSER_UNDO_PASS', flush=True)
                    bpy.ops.wm.quit_blender()
                    return None
            steps += 1
            return 0.6
        except Exception:
            traceback.print_exc()
        bpy.ops.wm.quit_blender()
    bpy.app.timers.register(run, first_interval=0.5)
