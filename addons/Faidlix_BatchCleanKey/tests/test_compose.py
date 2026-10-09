import importlib
import os
from pathlib import Path
import sys
import bpy
from mathutils import Quaternion

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
addon = importlib.import_module(os.environ.get('BCK_TEST_MODULE','Faidlix_BatchCleanKey'))
if not hasattr(bpy.types.WindowManager,'faidlix_batch_clean_key'):
    addon.register()
core, comp, ui = addon.core, addon.compose, addon.ui
arm = bpy.data.armatures.new('ComposeRig')
obj = bpy.data.objects.new('ComposeRig',arm)
bpy.context.collection.objects.link(obj)
for o in bpy.context.selected_objects:
    o.select_set(False)
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
bpy.ops.object.mode_set(mode='EDIT')
for i,name in enumerate(('Root','Hand','Empty')):
    b = arm.edit_bones.new(name)
    b.head,b.tail = (i,0,0),(i,0,1)
    if i:
        b.parent = arm.edit_bones['Root']
bpy.ops.object.mode_set(mode='POSE')
obj.animation_data_create()
actions = []
for name,offset,prop,size in [('MainCompose',0,'rotation_quaternion',4),('LowerCompose',100,'rotation_euler',3)]:
    a = bpy.data.actions.new(name)
    slot = a.slots.new('OBJECT',obj.name)
    bag = a.layers.new('L').strips.new(type='KEYFRAME').channelbag(slot,ensure=True)
    for bone in ('Root','Hand'):
        c = bag.fcurves.new(f'pose.bones["{bone}"].location',index=0)
        for t in (1,11):
            p = c.keyframe_points.insert(t,t+offset); p.interpolation='LINEAR'
        for i in range(size):
            c = bag.fcurves.new(f'pose.bones["{bone}"].{prop}',index=i)
            for t in (1,11):
                p = c.keyframe_points.insert(t,1 if prop=='rotation_quaternion' and i==0 else .5 if prop=='rotation_euler' and i==2 else 0)
                p.interpolation='LINEAR'
    actions.append(a)
obj.animation_data.action=actions[0]; obj.animation_data.action_slot=actions[0].slots[0]
def digest():
    return [[(c.data_path,c.array_index,core.snapshot(c)) for c in core.action_curves(a)] for a in actions]
before = digest()
main = comp.Clip.from_action(actions[0])
lower = comp.Clip.from_action(actions[1],3)
lower.resize('RIGHT',8)
assert (lower.source_start,lower.source_end,lower.start,lower.duration)==(1,6,3,5)
duplicate = lower.duplicate()
assert duplicate.start==8 and duplicate.action==actions[1]
retime = comp.Clip.from_action(actions[1],3)
retime.mode='RETIME'; retime.resize('RIGHT',8)
assert retime.source_end==11 and retime.source_frame(5.5)==6
tracks = [[main],[lower]]
e = comp.Evaluator(obj,tracks,['Hand'])
key=('pose.bones["Hand"].location',0)
assert e.sample(2)[key]==2
assert e.sample(5)[key]==103
assert e.sample(9)[key]==9
assert e.sample(5)[('pose.bones["Root"].location',0)]==5
q=Quaternion([e.sample(5)[('pose.bones["Hand"].rotation_quaternion',i)] for i in range(4)])
assert abs(q.angle-.5)<1e-5
assert comp.Evaluator(obj,tracks,['Hand'],2).sample(3)[key]==3
worker=comp.bake_steps(obj,tracks,['Hand'],'CombinedTest',1,11,.25)
next(worker); worker.close()
assert not bpy.data.actions.get('CombinedTest') and digest()==before
worker=comp.bake_steps(obj,tracks,['Hand'],'CombinedTest',1,11,.25)
while next(worker)[0] <= 41:
    pass
worker.close()
assert not bpy.data.actions.get('CombinedTest') and digest()==before
def consume(worker):
    while True:
        try: next(worker)
        except StopIteration as done: return done.value
output=consume(comp.bake_steps(obj,tracks,['Hand'],'CombinedTest',1,11,.25))
assert core.actual_range(output)==(1,11) and digest()==before
curves=list(core.action_curves(output))
assert next(c for c in curves if (c.data_path,c.array_index)==key).evaluate(5)==103
assert obj.animation_data.action==actions[0]
# Preview copies are independent; cancellation removes all temporary data.
session=addon.compose_ui.Session(bpy.context)
session.make_preview(); session.preview()
assert session.preview_obj.data != obj.data
assert obj.animation_data.action==actions[0] and digest()==before
preview_name=session.preview_scene.name
session.close(False)
assert not bpy.data.scenes.get(preview_name) and digest()==before
# Live selected-bone checkboxes and select-all buttons.
ui.populate(bpy.context)
bpy.ops.faidlix_batch_clean_key.bones_all(value=True)
assert all(b.select for b in obj.pose.bones)
bpy.ops.faidlix_batch_clean_key.bones_all(value=False)
assert not any(b.select for b in obj.pose.bones)
# Empty locked/muted rotation channels do not prevent real-key conversion.
empty=bpy.data.actions.new('EmptyRotation')
slot=empty.slots.new('OBJECT',obj.name)
bag=empty.layers.new('L').strips.new(type='KEYFRAME').channelbag(slot,ensure=True)
for i in range(4):
    c=bag.fcurves.new('pose.bones["Empty"].rotation_quaternion',index=i)
    c.lock=True; c.mute=True
consume(core.rotation_steps(bpy.context,obj,['Root','Empty'],[actions[0],output],'XYZ'))
assert obj.pose.bones['Root'].rotation_mode=='XYZ' and obj.pose.bones['Empty'].rotation_mode=='XYZ'
# Complete reset includes every rotation representation without changing mode.
bone=obj.pose.bones['Hand']
bone.location=(3,4,5); bone.scale=(2,3,4); bone.rotation_euler=(1,2,3)
bone.rotation_quaternion=(.5,.5,.5,.5); bone.rotation_axis_angle=(2,1,0,0)
core.reset_pose(obj,['Hand'])
assert tuple(bone.location)==(0,0,0) and tuple(bone.scale)==(1,1,1)
assert tuple(bone.rotation_euler)==(0,0,0) and tuple(bone.rotation_quaternion)==(1,0,0,0)
assert tuple(bone.rotation_axis_angle)==(0,0,1,0)
# Exercise reset through the actual batch Delete path, not only the helper.
delete_action=bpy.data.actions.new('DeleteReset')
slot=delete_action.slots.new('OBJECT',obj.name)
bag=delete_action.layers.new('L').strips.new(type='KEYFRAME').channelbag(slot,ensure=True)
c=bag.fcurves.new(bone.path_from_id()+'.location',index=0)
c.keyframe_points.insert(1,7); c.keyframe_points.insert(11,8)
core.assign_action(bpy.context,obj,delete_action)
bone.select=True
state=ui.populate(bpy.context)
for item in state.actions: item.selected=item.action==delete_action
state.operation='DELETE'; state.reset_bones=True
bone.scale=(2,3,4)
assert bpy.ops.faidlix_batch_clean_key.batch()=={'FINISHED'}
assert not c.keyframe_points and tuple(bone.location)==(0,0,0) and tuple(bone.scale)==(1,1,1)
# Re-clicking even the current Action uses newly edited key bounds.
curve=next(iter(core.action_curves(output)))
curve.keyframe_points[-1].co.x=25
output.use_frame_range=True; output.frame_end=99
bpy.ops.faidlix_batch_clean_key.switch(action_name=output.name)
assert bpy.context.scene.frame_end==25 and output.frame_end==25
curve.keyframe_points[-1].co.x=30
bpy.ops.faidlix_batch_clean_key.switch(action_name=output.name)
assert bpy.context.scene.frame_end==30 and output.frame_end==30
print('BATCH_COMPOSE_PASS trim retime overrides rotation preview cancellation mode_sync reset latest_bounds')
