import bpy,sys,os,importlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
addon=importlib.import_module(os.environ.get('BCK_TEST_MODULE','Faidlix_BatchCleanKey'))
if not hasattr(bpy.types.WindowManager,'faidlix_batch_clean_key'): addon.register()
if bpy.context.object and bpy.context.object.mode!='OBJECT': bpy.ops.object.mode_set(mode='OBJECT')
def rig(name,bone):
 arm=bpy.data.armatures.new(name); obj=bpy.data.objects.new(name,arm); bpy.context.collection.objects.link(obj)
 for o in bpy.context.selected_objects: o.select_set(False)
 obj.select_set(True); bpy.context.view_layer.objects.active=obj
 bpy.ops.object.mode_set(mode='EDIT'); b=arm.edit_bones.new(bone); b.head=(0,0,0); b.tail=(0,1,0)
 bpy.ops.object.mode_set(mode='OBJECT'); return obj
a,b=rig('ReverseRigA','Main'),rig('ReverseRigB','Accessory')
action=bpy.data.actions.new('ReverseShared')
sa=action.slots.new('OBJECT',a.name); sb=action.slots.new('OBJECT',b.name)
strip=action.layers.new('Layer').strips.new(type='KEYFRAME')
ba=strip.channelbag(sa,ensure=True); bb=strip.channelbag(sb,ensure=True)
for bag,bone in [(ba,'Main'),(bb,'Accessory')]:
 c=bag.fcurves.new('pose.bones["'+bone+'"].location',index=0)
 for frame,value in [(1.5,0),(4,2),(9.5,-1)]:
  p=c.keyframe_points.insert(frame,value); p.interpolation='BEZIER'
 c.keyframe_points[0].handle_right_type='FREE'; c.keyframe_points[0].handle_right=(2,1.5)
 c.update()
for obj,slot in [(a,sa),(b,sb)]:
 obj.animation_data_create(); obj.animation_data.action=action; obj.animation_data.action_slot=slot
state=bpy.context.window_manager.faidlix_batch_clean_key
state.target_armature=a
assert addon.ui.rig(bpy.context)==a and bpy.context.object==b
assert addon.core.slot_for(action,a)==sa and addon.core.slot_for(action,b)==sb
foreign=bpy.data.actions.new('AccessoryOnly'); foreign.slots.new('OBJECT',b.name)
addon.ui.refresh(bpy.context)
assert foreign not in [i.action for i in state.browser]
count=len(state.browser); assert bpy.ops.faidlix_batch_clean_key.new()=={'FINISHED'}
assert len(state.browser)==count+1 and b.animation_data.action==action
state.target_armature=b; addon.ui.refresh(bpy.context)
assert foreign in [i.action for i in state.browser]
state.target_armature=a; addon.core.assign_action(bpy.context,a,action)
original=addon.core.snapshot(ba.fcurves[0]); untouched=addon.core.snapshot(bb.fcurves[0])
def consume(g):
 while True:
  try: next(g)
  except StopIteration as e: return e.value
g=addon.ui.mirror.reverse_steps(bpy.context,a,action); next(g); g.close()
assert addon.core.snapshot(ba.fcurves[0])==original
result=consume(addon.ui.mirror.reverse_steps(bpy.context,a,action))
out=bpy.data.actions[result['flip_action']]
out_a=out.layers[0].strips[0].channelbag(addon.core.slot_for(out,a)).fcurves[0]
out_b=out.layers[0].strips[0].channelbag(next(s for s in out.slots if s.identifier==sb.identifier)).fcurves[0]
assert addon.core.snapshot(out_b)==untouched
assert [p.co.x for p in out_a.keyframe_points]==[1.5,7,9.5]
for j in range(65):
 t=1.5+j*8/64
 assert abs(out_a.evaluate(t)-ba.fcurves[0].evaluate(11-t))<2e-5,(t,out_a.evaluate(t),ba.fcurves[0].evaluate(11-t))
assert addon.core.snapshot(ba.fcurves[0])==original
assert b.animation_data.action==action
# UI operator follows the time mode and selected rig, not the active object.
assert bpy.ops.faidlix_batch_clean_key.flip(action_name=action.name,kind='TIME')=={'FINISHED'}
assert a.animation_data.action.name.startswith('ReverseShared_Reversed') and b.animation_data.action==action
assert bpy.ops.faidlix_batch_clean_key.duplicate(action_name=action.name,destination=b.name)=={'FINISHED'}
assert b.animation_data.action!=action and a.animation_data.action.name.startswith('ReverseShared_Reversed')
assert len(b.animation_data.action.slots)==1
# Unequal bone-channel bounds are padded when explicitly switching the Action.
state.target_armature=a; addon.core.assign_action(bpy.context,a,action)
other=ba.fcurves.new('pose.bones["Main"].location',index=1)
other.keyframe_points.insert(4,3); other.keyframe_points.insert(7,4)
assert bpy.ops.faidlix_batch_clean_key.switch(action_name=action.name)=={'FINISHED'}
assert [p.co.x for p in other.keyframe_points]==[1.5,4,7,9.5]
assert addon.core.snapshot(bb.fcurves[0])==untouched
state.target_armature=None
print('REVERSE_RIGS_PASS selected_rig filter count new_action multi_slot reverse_Bezier_handles original_key_count subframes cancel source_preserved')
