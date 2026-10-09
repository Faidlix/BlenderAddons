import bpy
import importlib
import os
import sys
from pathlib import Path
from mathutils import Euler, Quaternion
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
addon = importlib.import_module(os.environ.get('BCK_TEST_MODULE', 'Faidlix_BatchCleanKey'))
if not hasattr(bpy.types.WindowManager, 'faidlix_batch_clean_key'):
    addon.register()
core, ui = addon.core, addon.ui
if bpy.context.object and bpy.context.object.mode != 'OBJECT':
    bpy.ops.object.mode_set(mode='OBJECT')
arm = bpy.data.armatures.new('RotationRig')
obj = bpy.data.objects.new('RotationRig', arm)
bpy.context.collection.objects.link(obj)
for o in bpy.context.selected_objects:
    o.select_set(False)
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
bpy.ops.object.mode_set(mode='EDIT')
for name in ['Rotate', 'Untouched']:
    b = arm.edit_bones.new(name)
    b.head, b.tail = (0,0,0), (0,0,1)
bpy.ops.object.mode_set(mode='POSE')
bone = obj.pose.bones['Rotate']
bone.rotation_mode = 'QUATERNION'
actions, bags = [], []
for n in range(2):
    action = bpy.data.actions.new('RotationTest' + str(n))
    slot = action.slots.new('OBJECT', obj.name)
    bag = action.layers.new('Layer').strips.new(type='KEYFRAME').channelbag(slot, ensure=True)
    for index in range(4):
        c = bag.fcurves.new(bone.path_from_id()+'.rotation_quaternion', index=index)
        for frame, angles in [(2.25,(.2,.4,.6)), (5.75,(1.1,.6,2.5))]:
            p = c.keyframe_points.insert(frame, Euler(angles,'XYZ').to_quaternion()[index])
            p.interpolation = 'LINEAR'
    c = bag.fcurves.new('pose.bones["Untouched"].location', index=0)
    c.keyframe_points.insert(3,9)
    actions.append(action)
    bags.append(bag)
core.assign_action(bpy.context,obj,actions[0])
def consume(steps):
    while True:
        try:
            next(steps)
        except StopIteration as done:
            return done.value
def digest():
    return [[(c.data_path,c.array_index,core.snapshot(c)) for c in bag.fcurves] for bag in bags]
before = digest()
try:
    consume(core.rotation_steps(bpy.context,obj,['Rotate'],actions[:1],'XYZ'))
    raise AssertionError('Unselected Action must block mode switch')
except ValueError as e:
    assert '一併勾選' in str(e)
assert digest() == before
steps = core.rotation_steps(bpy.context,obj,['Rotate'],actions,'XYZ',.25)
assert next(steps)[0] == 1
steps.close()
assert digest() == before and bone.rotation_mode == 'QUATERNION'
# Cancellation is also safe once the destination write has begun.
steps = core.rotation_steps(bpy.context,obj,['Rotate'],actions,'XYZ',.25)
while '寫回中' not in next(steps)[2]:
    pass
steps.close()
assert digest() == before and bone.rotation_mode == 'QUATERNION'
times = [2.25+i*.25 for i in range(15)]
expected = [[Quaternion([bag.fcurves.find(bone.path_from_id()+'.rotation_quaternion',index=i).evaluate(t)
                        for i in range(4)]).normalized() for t in times] for bag in bags]
result = consume(core.rotation_steps(bpy.context,obj,['Rotate'],actions,'XYZ',.25))
assert result['actions'] == 2 and bone.rotation_mode == 'XYZ'
for bag, quats in zip(bags,expected):
    assert not any(c.data_path.endswith('rotation_quaternion') for c in bag.fcurves)
    assert bag.fcurves.find('pose.bones["Untouched"].location',index=0).evaluate(3)==9
    for t,q in zip(times,quats):
        actual = Euler([bag.fcurves.find(bone.path_from_id()+'.rotation_euler',index=i).evaluate(t) for i in range(3)],'XYZ').to_quaternion()
        assert abs(actual.dot(q)) > .999999, (t,actual,q)
consume(core.rotation_steps(bpy.context,obj,['Rotate'],actions,'QUATERNION',.25))
assert bone.rotation_mode == 'QUATERNION'
for bag, quats in zip(bags,expected):
    for t,q in zip(times,quats):
        actual = Quaternion([bag.fcurves.find(bone.path_from_id()+'.rotation_quaternion',index=i).evaluate(t) for i in range(4)]).normalized()
        assert abs(actual.dot(q)) > .999999
core.sync_scene_range(bpy.context.scene,actions[0])
assert (bpy.context.scene.frame_start,bpy.context.scene.frame_end)==(2,6)
actions[1].use_frame_range=True
actions[1].frame_end=80
actions[1].frame_start=20
ui.refresh(bpy.context)
state=bpy.context.window_manager.faidlix_batch_clean_key
state.browser_index=next(i for i,item in enumerate(state.browser) if item.action==actions[1])
assert obj.animation_data.action==actions[1]
assert (bpy.context.scene.frame_start,bpy.context.scene.frame_end)==(20,80)
actions[1].name='RenamedRotation'
ui.refresh(bpy.context)
assert state.browser[state.browser_index].action==actions[1]
# Inject a failed destination write: source curves and mode must remain intact.
before=digest()
write=core.snapshot
def fail(curve):
    raise RuntimeError('injected commit failure')
core.snapshot=fail
try:
    consume(core.rotation_steps(bpy.context,obj,['Rotate'],actions,'XYZ'))
    raise AssertionError('Expected failure')
except RuntimeError:
    pass
finally:
    core.snapshot=write
assert digest()==before and bone.rotation_mode=='QUATERNION'
print('BATCH_ROTATION_TEST_OK bidirectional samples cancellation rollback blockers range browser rename')

# Curve union bounds, shorter channels, unchanged interior keys, seamless tangents.
loop=bpy.data.actions.new('LoopTest')
slot=loop.slots.new('OBJECT',obj.name)
bag=loop.layers.new('Layer').strips.new(type='KEYFRAME').channelbag(slot,ensure=True)
long=bag.fcurves.new('pose.bones["Rotate"].location',index=0)
short=bag.fcurves.new('pose.bones["Untouched"].location',index=1)
for c,points in [(long,[(1.25,2),(4,5),(10.75,9)]),(short,[(3,7),(6,8)])]:
    for t,v in points:
        p=c.keyframe_points.insert(t,v)
        p.interpolation='LINEAR'
count,added,start,end=core.make_loop(loop,obj)
assert (count,added,start,end)==(2,2,1.25,10.75)
for c in (long,short):
    assert c.keyframe_points[0].co.x==start and c.keyframe_points[-1].co.x==end
    assert c.evaluate(start)==c.evaluate(end)
    first,last=c.keyframe_points[0],c.keyframe_points[-1]
    slope1=(first.handle_right.y-first.co.y)/(first.handle_right.x-first.co.x)
    slope2=(last.co.y-last.handle_left.y)/(last.co.x-last.handle_left.x)
    assert abs(slope1-slope2)<1e-5
assert long.keyframe_points[1].co.y==5 and short.keyframe_points[1].co.y==7
short.lock=True
saved=[core.snapshot(c) for c in (long,short)]
try:
    core.make_loop(loop,obj)
    raise AssertionError('Locked loop must fail atomically')
except ValueError:
    pass
assert saved==[core.snapshot(c) for c in (long,short)]
print('BATCH_LOOP_TEST_OK union_bounds added_keys values tangents interiors locked_atomic')
