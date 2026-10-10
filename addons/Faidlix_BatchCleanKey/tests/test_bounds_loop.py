import bpy, importlib, os, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
addon=importlib.import_module(os.environ.get('BCK_TEST_MODULE','Faidlix_BatchCleanKey'))
if not hasattr(bpy.types.WindowManager,'faidlix_batch_clean_key'): addon.register()
if bpy.context.object and bpy.context.object.mode!='OBJECT': bpy.ops.object.mode_set(mode='OBJECT')
arm=bpy.data.armatures.new('Bounds'); obj=bpy.data.objects.new('Bounds',arm)
bpy.context.collection.objects.link(obj)
for o in bpy.context.selected_objects: o.select_set(False)
obj.select_set(True); bpy.context.view_layer.objects.active=obj
bpy.ops.object.mode_set(mode='EDIT')
for i,name in enumerate(('Animated','Static','Euler','Axis')):
 b=arm.edit_bones.new(name); b.head=(i,0,0); b.tail=(i,0,1)
bpy.ops.object.mode_set(mode='OBJECT')
obj.pose.bones['Static'].location=(2,3,4)
obj.pose.bones['Euler'].rotation_mode='XYZ'
obj.pose.bones['Axis'].rotation_mode='AXIS_ANGLE'
action=bpy.data.actions.new('BoundsAction'); slot=action.slots.new('OBJECT',obj.name)
strip=action.layers.new('Layer').strips.new(type='KEYFRAME'); bag=strip.channelbag(slot,ensure=True)
c=bag.fcurves.new('pose.bones["Animated"].location',index=0)
for f,v in ((2,0),(8,2),(17,4)): c.keyframe_points.insert(f,v)
c.modifiers.new('CYCLES'); c.lock=True
short=bag.fcurves.new('pose.bones["Animated"].location',index=1)
for f,v in ((5,1),(11,3)): short.keyframe_points.insert(f,v)
source=[addon.core.snapshot(c),addon.core.snapshot(short)]
def consume(g):
 while True:
  try: next(g)
  except StopIteration as e: return e.value
g=addon.core.loop_copy_steps(action,obj,keyed_only=True); next(g); g.close()
assert [addon.core.snapshot(c),addon.core.snapshot(short)]==source
copy=consume(addon.core.loop_copy_steps(action,obj,keyed_only=True))
out=copy.layers[0].strips[0].channelbag(addon.core.slot_for(copy,obj))
assert len(out.fcurves)==2
assert [p.co.x for p in out.fcurves[0].keyframe_points]==[2,8,17]
assert [p.co.x for p in out.fcurves[1].keyframe_points]==[2,5,11,17]
assert not out.fcurves[0].modifiers and not out.fcurves[0].lock
for curve in out.fcurves:
 assert abs(curve.evaluate(2)-curve.evaluate(17))<1e-6
assert [addon.core.snapshot(c),addon.core.snapshot(short)]==source
state=bpy.context.window_manager.faidlix_batch_clean_key; state.target_armature=obj
assert bpy.ops.faidlix_batch_clean_key.switch(action_name=action.name)=={'FINISHED'}
assert (bpy.context.scene.frame_start,bpy.context.scene.frame_end)==(2,17)
for bone in obj.pose.bones:
 rot='rotation_euler' if bone.rotation_mode=='XYZ' else 'rotation_axis_angle' if bone.rotation_mode=='AXIS_ANGLE' else 'rotation_quaternion'
 for prop in ('location',rot,'scale'):
  for index in range(len(getattr(bone,prop))):
   curve=bag.fcurves.find(bone.path_from_id(prop),index=index)
   assert curve and {2,17}<={p.co.x for p in curve.keyframe_points},(bone.name,prop,index)
assert len(c.modifiers)==1 and c.lock
assert [p.co.y for p in bag.fcurves.find('pose.bones["Static"].location',index=0).keyframe_points]==[2,2]
assert addon.core.pad_bone_bounds(action,obj)==0
state.target_armature=None
print('BOUNDS_LOOP_PASS all_bones_TRS static_pose modes bounds keyed_only_cycles sparse_keys cancel source_preserved idempotent')
