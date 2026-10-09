import importlib
import os
from pathlib import Path
import sys
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
addon = importlib.import_module(os.environ.get('BCK_TEST_MODULE', 'Faidlix_BatchCleanKey'))
if not hasattr(bpy.types.WindowManager, 'faidlix_batch_clean_key'):
    addon.register()
core, ui = addon.core, addon.ui
arm = bpy.data.armatures.new('Management')
obj = bpy.data.objects.new('Management', arm)
bpy.context.collection.objects.link(obj)
for o in bpy.context.selected_objects:
    o.select_set(False)
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
for i, name in enumerate(['Hand.L', 'Hand.R', 'Center', 'Missing.L']):
    b = arm.edit_bones.new(name)
    b.head, b.tail = (i, 0, 0), (i, 0, 1)
bpy.ops.object.mode_set(mode='POSE')
for bone in obj.pose.bones:
    bone.select = bone.name == 'Hand.L'
    bone.rotation_mode = 'XYZ'
obj.animation_data_create()
act = bpy.data.actions.new('ManageAction')
slot = act.slots.new('OBJECT', obj.name)
bag = act.layers.new('Layer').strips.new(type='KEYFRAME').channelbag(slot, ensure=True)
for name, value in [('Hand.L', 2), ('Hand.R', 5), ('Center', 7), ('Missing.L', 9)]:
    for path, index in [('location', 0), ('rotation_euler', 1), ('rotation_quaternion', 2),
                        ('rotation_axis_angle', 3), ('scale', 0)]:
        c = bag.fcurves.new(f'pose.bones["{name}"].{path}', index=index)
        for frame in (10.25, 20.75):
            p = c.keyframe_points.insert(frame, value)
            p.interpolation = 'BEZIER'
obj.animation_data.action = act
obj.animation_data.action_slot = slot
state = addon.populate(bpy.context)
assert len(state.bones) == 4
left = next(b for b in state.bones if b.name == 'Hand.L')
right = next(b for b in state.bones if b.name == 'Hand.R')
assert left.selected and not right.selected
initial = next(i.keys for i in state.actions if i.action == act)
right.selected = True
assert obj.pose.bones['Hand.R'].select
assert next(i.keys for i in state.actions if i.action == act) == initial * 2
obj.pose.bones['Hand.L'].select = False
ui.refresh(bpy.context)
assert not left.selected and right.selected
assert next(i.keys for i in state.actions if i.action == act) == initial

original = [(c.data_path, core.snapshot(c)) for c in bag.fcurves]
count, skipped = core.mirror_action(act, obj)
assert count == 15 and skipped == 5, (count, skipped)
assert bag.fcurves.find('pose.bones["Hand.R"].location', index=0).evaluate(15) == -2
assert bag.fcurves.find('pose.bones["Hand.L"].location', index=0).evaluate(15) == -5
assert bag.fcurves.find('pose.bones["Center"].rotation_quaternion', index=2).evaluate(15) == -7
assert bag.fcurves.find('pose.bones["Hand.R"].scale', index=0).evaluate(15) == 2
assert bag.fcurves.find('pose.bones["Missing.L"].location', index=0).evaluate(15) == 9
core.mirror_action(act, obj)
assert [(c.data_path, core.snapshot(c)) for c in bag.fcurves] == original

before_actions = set(bpy.data.actions)
assert bpy.ops.faidlix_batch_clean_key.flip(action_name=act.name, mode='COPY') == {'FINISHED'}
copy = obj.animation_data.action
assert copy != act and copy.use_fake_user
assert [(c.data_path, core.snapshot(c)) for c in bag.fcurves] == original
assert set(bpy.data.actions) - before_actions == {copy}
assert bpy.ops.faidlix_batch_clean_key.switch(action_name=act.name) == {'FINISHED'}
assert obj.animation_data.action == act
assert next(i for i in state.browser if i.action == act).selected
assert bpy.ops.faidlix_batch_clean_key.duplicate(action_name=act.name) == {'FINISHED'}
duplicate = obj.animation_data.action
assert duplicate != act and duplicate.use_fake_user
dup_curve = duplicate.layers[0].strips[0].channelbags[0].fcurves[0]
dup_curve.keyframe_points[0].co.y = 100
assert bag.fcurves[0].keyframe_points[0].co.y != 100
assert bpy.ops.faidlix_batch_clean_key.new() == {'FINISHED'}
new = obj.animation_data.action
assert new.use_fake_user and not list(core.action_curves(new))
new_name = new.name
assert bpy.ops.faidlix_batch_clean_key.delete_action() == {'FINISHED'}
assert new_name not in bpy.data.actions and obj.animation_data.action is None
assert act.name in bpy.data.actions

assert core.actual_range(act) == (10.25, 20.75)
act.use_frame_range = True
act.frame_start, act.frame_end = 100, 150
snapshot = [(c.data_path, core.snapshot(c)) for c in bag.fcurves]
changed, skipped = core.sync_ranges([act, bpy.data.actions.new('Empty')])
assert changed == skipped == 1
assert act.frame_start == 10.25 and act.frame_end == 20.75
assert snapshot == [(c.data_path, core.snapshot(c)) for c in bag.fcurves]

core.assign_action(bpy.context, obj, act)
steps = core.process_steps(bpy.context, obj, ['Hand.L'], [act], 'DELETE')
progress = next(steps)
assert progress[0] == 1 and progress[1] == 5
steps.close()
assert [(c.data_path, core.snapshot(c)) for c in bag.fcurves] == snapshot
steps = core.process_steps(bpy.context, obj, ['Hand.L'], [act], 'CLEAN')
next(steps)
steps.close()
assert not any(s.name.startswith('__BatchCleanKey_Work__') for s in bpy.data.scenes)
assert [(c.data_path, core.snapshot(c)) for c in bag.fcurves] == snapshot
print('BATCH_MANAGEMENT_TEST_OK bones_sync mirror copy switch new delete ranges progress_cancel')
