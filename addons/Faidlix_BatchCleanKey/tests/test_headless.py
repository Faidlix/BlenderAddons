import importlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
addon = importlib.import_module(os.environ.get('BCK_TEST_MODULE', 'Faidlix_BatchCleanKey'))
core = addon.core
if not hasattr(bpy.types.WindowManager, 'faidlix_batch_clean_key'):
    addon.register()


def fixture():
    arm = bpy.data.armatures.new('BatchTest')
    obj = bpy.data.objects.new('BatchTest', arm)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    for name in ['Target', 'Other', 'TargetExtra', 'quote"slash\\']:
        b = arm.edit_bones.new(name)
        b.head = (0, 0, 0)
        b.tail = (0, 0, 1)
    bpy.ops.object.mode_set(mode='POSE')
    for b in obj.pose.bones:
        b.select = b.name == 'Target'
    arm.bones.active = arm.bones['Target']
    obj.animation_data_create()
    return obj


def action(obj, name, count=9, interp='LINEAR'):
    act = bpy.data.actions.new(name)
    slot = act.slots.new('OBJECT', obj.name)
    bag = act.layers.new('Layer').strips.new(type='KEYFRAME').channelbag(slot, ensure=True)
    for path in ['pose.bones["Target"].location', 'pose.bones["Other"].location',
                 'pose.bones["TargetExtra"].location', 'location',
                 'pose.bones["quote\\"slash\\\\"].location']:
        curve = bag.fcurves.new(path, index=0)
        for i in range(count):
            p = curve.keyframe_points.insert(i + 1, float(i))
            p.interpolation = interp
        curve.update()
    obj.animation_data.action = act
    obj.animation_data.action_slot = slot
    return act, bag


obj = fixture()
window, scene = bpy.context.window, bpy.context.scene
area = next(a for a in window.screen.areas if a.type == 'VIEW_3D')
checks = []
with bpy.context.temp_override(area=area, region=next(r for r in area.regions if r.type == 'WINDOW')):
    for operation, mode in [('CLEAN', 'RATIO'), ('DECIMATE', 'RATIO'), ('DECIMATE', 'ERROR'), ('DELETE', 'RATIO')]:
        a, bag = action(obj, operation + mode)
        b, bag_b = action(obj, operation + mode + 'Second')
        if operation == 'CLEAN':
            for cb in (bag, bag_b):
                for p in cb.fcurves[0].keyframe_points:
                    p.co.y = 1
                cb.fcurves[0].update()
        unchanged = [core.snapshot(c) for c in list(bag.fcurves)[1:]]
        active_action, active_slot = obj.animation_data.action, obj.animation_data.action_slot
        before_ids = (len(bpy.data.actions), len(bpy.data.objects), len(bpy.data.scenes))
        result = core.process(bpy.context, obj, ['Target'], [a, b], operation, mode=mode, error=0.001)
        assert result['actions'] == 2 and result['removed'] > 0, result
        assert [core.snapshot(c) for c in list(bag.fcurves)[1:]] == unchanged
        assert obj.animation_data.action == active_action and obj.animation_data.action_slot == active_slot
        assert bpy.context.scene == scene and obj.mode == 'POSE' and area.type == 'VIEW_3D'
        assert before_ids == (len(bpy.data.actions), len(bpy.data.objects), len(bpy.data.scenes))
        assert core.selected_bones(bpy.context) == ['Target']
        if operation == 'DELETE':
            assert len(bag.fcurves[0].keyframe_points) == 0 and len(bag.fcurves) == 5
        checks.append(operation + mode)

    a, bag = action(obj, 'Locked')
    c = bag.fcurves[0]
    c.lock = True
    original = core.snapshot(c)
    result = core.process(bpy.context, obj, ['Target'], [a], 'DELETE')
    assert result['removed'] == 0 and core.snapshot(c) == original
    checks.append('LOCKED')

    a, bag = action(obj, 'Constant', interp='CONSTANT')
    original = core.snapshot(bag.fcurves[0])
    result = core.process(bpy.context, obj, ['Target'], [a], 'DECIMATE')
    assert result['removed'] == 0 and core.snapshot(bag.fcurves[0]) == original
    checks.append('CONSTANT_SKIP')

    a, bag = action(obj, 'MultiSlot')
    other = a.slots.new('OBJECT', 'Different')
    other_bag = a.layers[0].strips[0].channelbag(other, ensure=True)
    c = other_bag.fcurves.new('pose.bones["Target"].location', index=0)
    c.keyframe_points.insert(1, 99)
    original = core.snapshot(c)
    core.process(bpy.context, obj, ['Target'], [a], 'DELETE')
    assert core.snapshot(c) == original
    # Unused ambiguous action must not fall back to all slots.
    obj.animation_data.action = None
    assert core.target_curves(a, obj, ['Target']) == []
    checks.append('SLOT_ISOLATION')

    a, bag = action(obj, 'Escaped')
    curves = core.target_curves(a, obj, ['quote"slash\\'])
    assert len(curves) == 1
    core.process(bpy.context, obj, ['quote"slash\\'], [a], 'DELETE')
    assert len(curves[0].keyframe_points) == 0 and len(bag.fcurves[0].keyframe_points) == 9
    checks.append('ESCAPED_BONE')

    a, bag = action(obj, 'Modified')
    c = bag.fcurves[0]
    mod = c.modifiers.new('NOISE')
    mod.strength = 3.5
    core.process(bpy.context, obj, ['Target'], [a], 'CLEAN')
    assert len(c.modifiers) == 1 and c.modifiers[0].strength == 3.5
    checks.append('MODIFIER_PRESERVED')

    a, bag = action(obj, 'Failure')
    original = core.snapshot(bag.fcurves[0])
    native_run = core.NativeProcessor.run
    def fail(*args, **kwargs):
        raise RuntimeError('Injected native failure')
    core.NativeProcessor.run = fail
    try:
        try:
            core.process(bpy.context, obj, ['Target'], [a], 'CLEAN')
            raise AssertionError('Expected failure')
        except RuntimeError:
            pass
        assert core.snapshot(bag.fcurves[0]) == original
        assert bpy.context.scene == scene and area.type == 'VIEW_3D'
        assert not any(s.name.startswith('__BatchCleanKey_Work__') for s in bpy.data.scenes)
    finally:
        core.NativeProcessor.run = native_run
    checks.append('FAILURE_ATOMIC')

    addon.populate(bpy.context)
    state = bpy.context.window_manager.faidlix_batch_clean_key
    state.operation = 'DELETE'
    assert bpy.ops.faidlix_batch_clean_key.batch() == {'FINISHED'}
    assert len(bag.fcurves[0].keyframe_points) == 0
    checks.append('OPERATOR')

items = [SimpleNamespace(selected=False) for _ in range(6)]
anchor = core.choose(items, 1, -1)
anchor = core.choose(items, 3, anchor, ctrl=True)
assert [i for i, x in enumerate(items) if x.selected] == [1, 3]
anchor = core.choose(items, 1, anchor, ctrl=True)
assert [i for i, x in enumerate(items) if x.selected] == [3]
anchor = core.choose(items, 4, anchor, shift=True)
assert [i for i, x in enumerate(items) if x.selected] == [1, 2, 3, 4]
core.choose(items, 0, anchor, ctrl=True, shift=True)
assert [i for i, x in enumerate(items) if x.selected] == [0, 1, 2, 3, 4]
checks.append('CTRL_SHIFT_SELECTION')
for space, mode in [('VIEW_3D', None), ('DOPESHEET_EDITOR', 'DOPESHEET'),
                    ('DOPESHEET_EDITOR', 'ACTION'), ('GRAPH_EDITOR', 'FCURVES')]:
    area.type = space
    if mode:
        area.spaces.active.mode = mode
    with bpy.context.temp_override(area=area, region=next(r for r in area.regions if r.type == 'WINDOW')):
        assert addon.BCK_OT_Batch.poll(bpy.context), (space, mode)
        a, bag = action(obj, space + (mode or ''))
        for p in bag.fcurves[0].keyframe_points:
            p.co.y = 1
        bag.fcurves[0].update()
        result = core.process(bpy.context, obj, ['Target'], [a], 'CLEAN')
        assert result['removed'] > 0, (space, mode, result)
        assert area.type == space
        if mode:
            assert area.spaces.active.mode == mode
checks.append('FOUR_EDITOR_CONTEXTS')
print('BATCH_CLEAN_KEY_TEST_OK ' + json.dumps(checks))
