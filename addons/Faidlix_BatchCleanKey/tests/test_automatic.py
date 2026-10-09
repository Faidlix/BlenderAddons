import bpy,sys,os,importlib
from pathlib import Path
from mathutils import Euler,Quaternion
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
addon=importlib.import_module(os.environ.get('BCK_TEST_MODULE','Faidlix_BatchCleanKey'))
if not hasattr(bpy.types.WindowManager,'faidlix_batch_clean_key'): addon.register()
if bpy.context.object and bpy.context.object.mode!='OBJECT': bpy.ops.object.mode_set(mode='OBJECT')
arm=bpy.data.armatures.new('AutomaticRig')
obj=bpy.data.objects.new('AutomaticRig',arm)
bpy.context.collection.objects.link(obj)
for o in bpy.context.selected_objects: o.select_set(False)
obj.select_set(True); bpy.context.view_layer.objects.active=obj
bpy.ops.object.mode_set(mode='EDIT')
b=arm.edit_bones.new('AutoBone'); b.head,b.tail=(0,0,0),(0,0,1)
bpy.ops.object.mode_set(mode='POSE')
bone=obj.pose.bones['AutoBone']; bone.rotation_mode='QUATERNION'
actions=[]
for n in range(2):
 a=bpy.data.actions.new('AutomaticAction'+str(n)); a.use_fake_user=True
 slot=a.slots.new('OBJECT',obj.name)
 bag=a.layers.new('Layer').strips.new(type='KEYFRAME').channelbag(slot,ensure=True)
 for i in range(4):
  c=bag.fcurves.new(bone.path_from_id()+'.rotation_quaternion',index=i)
  for f,angles in [(1,(.2,.3,.4)),(5,(.5,.6,.7))]:
   p=c.keyframe_points.insert(f,Euler(angles,'XYZ').to_quaternion()[i]); p.interpolation='LINEAR'
  c.modifiers.new('CYCLES'); c.lock=True
  if i==1: c.mute=True
 c=bag.fcurves.new(bone.path_from_id()+'.location',index=0)
 for f in (1,9): c.keyframe_points.insert(f,9)
 # Existing destination and inactive rotation representations must be replaced.
 for prop,count in [('rotation_euler',3),('rotation_axis_angle',4)]:
  for i in range(count):
   c=bag.fcurves.new(bone.path_from_id()+'.'+prop,index=i)
   for f in (2,8): c.keyframe_points.insert(f,123)
 actions.append(a)
addon.core.assign_action(bpy.context,obj,actions[0])
track=obj.animation_data.nla_tracks.new()
strip=track.strips.new('NLAUser',20,actions[1]); strip.mute=True
def digest():
 return repr([(a.name,[(c.data_path,c.array_index,c.lock,c.mute,[m.type for m in c.modifiers],addon.core.snapshot(c)) for c in addon.core.action_curves(a)]) for a in actions])
before=digest()
def consume(worker):
 while True:
  try: next(worker)
  except StopIteration as end: return end.value
work=addon.ui.automatic.rotation_steps(bpy.context,obj,['AutoBone'],actions[:1],'XYZ',.25)
next(work); work.close()
assert digest()==before and bone.rotation_mode=='QUATERNION'
assert not any(a.name.startswith('__BCK_Auto__') for a in bpy.data.actions)
# Commit-stage cancellation also keeps Action IDs, NLA users and original modifiers.
work=addon.ui.automatic.rotation_steps(bpy.context,obj,['AutoBone'],actions[:1],'XYZ',.25)
while '寫回中' not in next(work)[2]: pass
work.close()
assert digest()==before and strip.action==actions[1] and obj.animation_data.action==actions[0]
times=[1,5]
expected=[]
for a in actions:
 curves={c.array_index:c for c in addon.core.action_curves(a) if c.data_path.endswith('rotation_quaternion')}
 expected.append([Quaternion([curves[i].evaluate(t) for i in range(4)]).normalized() for t in times])
unselected=repr([(c.data_path,c.array_index,c.lock,c.mute,[m.type for m in c.modifiers],addon.core.snapshot(c)) for c in addon.core.action_curves(actions[1])])
result=consume(addon.ui.automatic.rotation_steps(bpy.context,obj,['AutoBone'],actions[:1],'XYZ',.25))
assert result['actions']==2 and bone.rotation_mode=='XYZ'
assert obj.animation_data.action.name=='AutomaticAction0' and strip.action.name=='AutomaticAction1'
for n,quats in enumerate(expected):
 a=bpy.data.actions['AutomaticAction'+str(n)]
 curves={c.array_index:c for c in addon.core.action_curves(a) if c.data_path.endswith('rotation_euler')}
 for t,q in zip(times,quats):
  actual=Euler([curves[i].evaluate(t) for i in range(3)],'XYZ').to_quaternion()
  assert abs(actual.dot(q))>.999999,(t,actual,q)
 assert all(not c.modifiers and not c.lock and not c.mute for c in curves.values())
 assert len(curves)==3
 assert all([p.co.x for p in c.keyframe_points]==times for c in curves.values())
 assert all(p.interpolation=='BEZIER' and p.handle_left_type==p.handle_right_type=='AUTO_CLAMPED' for c in curves.values() for p in c.keyframe_points)
 assert not any(c.data_path.endswith(('rotation_quaternion','rotation_axis_angle')) for c in addon.core.action_curves(a))
 assert next(c for c in addon.core.action_curves(a) if c.data_path.endswith('location')).evaluate(4)==9
assert not any(a.name.startswith('__BCK_Auto__') for a in bpy.data.actions)
addon.core.assign_action(bpy.context,obj,bpy.data.actions['AutomaticAction0'])
assert bone.rotation_mode=='XYZ'
print('AUTOMATIC_ROTATION_PASS unified original_key_times no_extra_frames replaces_stale_rotations Bezier_AutoClamped cycles locked mute rollback NLA users')

# Sampled channels, missing components and unsafe Driver cancellation.
a=bpy.data.actions['AutomaticAction0']
bag=a.layers[0].strips[0].channelbags[0]
c=next(c for c in bag.fcurves if c.data_path.endswith('rotation_euler') and c.array_index==2)
bag.fcurves.remove(c)
for c in bag.fcurves:
 if c.data_path.endswith('rotation_euler'): c.convert_to_samples(1,9)
consume(addon.ui.automatic.rotation_steps(bpy.context,obj,['AutoBone'],[bpy.data.actions['AutomaticAction0']],'QUATERNION',.25))
assert bone.rotation_mode=='QUATERNION'
assert all(not c.sampled_points for a in bpy.data.actions if a.name.startswith('AutomaticAction') for c in addon.core.action_curves(a) if c.data_path.endswith('rotation_quaternion'))
driver=obj.driver_add(bone.path_from_id()+'.rotation_quaternion',0)
_,_,failures=addon.ui.automatic.inspect(obj,['AutoBone'],[obj.animation_data.action],'XYZ')
assert failures and 'Driver' in failures[0]
try:
 consume(addon.ui.automatic.rotation_steps(bpy.context,obj,['AutoBone'],[obj.animation_data.action],'XYZ'))
 raise AssertionError('Driver must cancel')
except ValueError: pass
assert bone.rotation_mode=='QUATERNION' and not any(a.name.startswith('__BCK_Auto__') for a in bpy.data.actions)
obj.driver_remove(bone.path_from_id()+'.rotation_quaternion',0)
print('AUTOMATIC_SAMPLED_MISSING_DRIVER_CANCEL_PASS')
