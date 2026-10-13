import bpy,sys,os,importlib,math
from pathlib import Path
from mathutils import Matrix,Vector
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
a=importlib.import_module(os.environ.get('BCK_TEST_MODULE','Faidlix_BatchCleanKey'))
if not hasattr(bpy.types.WindowManager,'faidlix_batch_clean_key'): a.register()
if bpy.context.object and bpy.context.object.mode!='OBJECT': bpy.ops.object.mode_set(mode='OBJECT')
arm=bpy.data.armatures.new('Adjust'); obj=bpy.data.objects.new('Adjust',arm); bpy.context.collection.objects.link(obj)
for o in bpy.context.selected_objects: o.select_set(False)
obj.select_set(True); bpy.context.view_layer.objects.active=obj
bpy.ops.object.mode_set(mode='EDIT')
root=arm.edit_bones.new('Root'); root.head=(0,0,0); root.tail=(0,1,0)
child=arm.edit_bones.new('Hand'); child.head=(2,0,0); child.tail=(2,1,0); child.parent=root
bpy.ops.object.mode_set(mode='POSE')
for b in obj.pose.bones: b.rotation_mode='XYZ'; b.select=True
arm.bones.active=arm.bones['Root']
action=bpy.data.actions.new('AdjustWalk'); slot=action.slots.new('OBJECT',obj.name)
other=action.slots.new('OBJECT','OtherAdjustRig'); strip=action.layers.new('Layer').strips.new(type='KEYFRAME')
bag=strip.channelbag(slot,ensure=True); foreign=strip.channelbag(other,ensure=True).fcurves.new('location',index=0)
foreign.keyframe_points.insert(30,9); foreign_before=a.core.snapshot(foreign)
for path,index,values in [('pose.bones["Root"].location',0,[(1,0),(6,5),(11,10)]),('pose.bones["Root"].rotation_euler',2,[(1,0),(11,0)]),('pose.bones["Hand"].rotation_euler',2,[(1,.2),(11,.4)])]:
 c=bag.fcurves.new(path,index=index)
 for frame,value in values:
  p=c.keyframe_points.insert(frame,value); p.select_control_point=frame!=6; p.interpolation='BEZIER'
obj.animation_data_create().action=action; obj.animation_data.action_slot=slot
bpy.context.scene.frame_set(1); bpy.context.scene.tool_settings.transform_pivot_point='CURSOR'; bpy.context.scene.cursor.location=(0,0,0)
r=a.adjust.capture(bpy.context,obj)
assert r['times']=={'Root':[1,11],'Hand':[1,11]}
delta=Matrix.Rotation(math.pi/2,4,'Z'); deltas={n:delta for n in r['times']}
def consume(g):
 while True:
  try: next(g)
  except StopIteration as e: return e.value
before=repr([(c.data_path,a.core.snapshot(c)) for c in bag.fcurves])
g=a.adjust.steps(r,deltas,'PATH','Root'); next(g); g.close()
assert before==repr([(c.data_path,a.core.snapshot(c)) for c in bag.fcurves])
plans=consume(a.adjust.steps(r,deltas,'PATH','Root'))
assert abs(plans['Root','location',1][11]-10)<1e-5
assert ('Hand','rotation_euler',2) not in plans # Parent rotation is applied once.
assert all(set(v)<={1,11} for v in plans.values())
keep=consume(a.adjust.steps(r,deltas,'KEEP_PATH','Root'))
assert not any(n=='Root' and p=='location' for n,p,i in keep)
count=a.adjust.commit(r,plans); assert count>0
assert a.core.snapshot(foreign)==foreign_before
x=bag.fcurves.find('pose.bones["Root"].location',index=0)
assert next(p.co.y for p in x.keyframe_points if p.co.x==6)==5
y=bag.fcurves.find('pose.bones["Root"].location',index=1)
assert {p.co.x for p in y.keyframe_points}=={1,11}
assert all(p.interpolation=='BEZIER' for p in y.keyframe_points)
bpy.context.scene.frame_set(11)
assert abs(obj.pose.bones['Root'].matrix.translation.y-10)<1e-4
assert abs(obj.pose.bones['Hand'].matrix.translation.y-12)<1e-4
# Native local move: existing point times preserved; missing axes only at those times.
r=a.adjust.capture(bpy.context,obj)
translate={n:Matrix.Translation((0,0,2)) for n in r['times']}
p=consume(a.adjust.steps(r,translate,'LOCAL'))
assert all(set(v)<={1,11} for v in p.values())
a.adjust.commit(r,p)
assert set(p['Root','location',2])=={1,11}
blocked=bag.fcurves.find('pose.bones["Root"].rotation_euler',index=2); blocked.modifiers.new('NOISE')
digest=repr([(c.data_path,a.core.snapshot(c)) for c in bag.fcurves])
try: consume(a.adjust.steps(r,translate,'LOCAL'))
except ValueError: pass
else: raise AssertionError('modifier must fail before writing')
assert digest==repr([(c.data_path,a.core.snapshot(c)) for c in bag.fcurves])
print('ADJUST_PASS path facing local parent_once same_frame_missing_axes unselected_key foreign_slot Bezier cancel blockers')

# Transaction cancellation after writes also restores original curve/group data.
for modifier in list(blocked.modifiers): blocked.modifiers.remove(modifier)
digest=repr([(c.data_path,c.array_index,a.core.snapshot(c)) for c in bag.fcurves]); group_names=[g.name for g in bag.groups]
values={('Root','location',0):{float(i):i for i in range(1,400)}}
g=a.adjust.commit_steps(r,values); next(g); g.close()
assert digest==repr([(c.data_path,c.array_index,a.core.snapshot(c)) for c in bag.fcurves])
assert [g.name for g in bag.groups]==group_names
values={('Hand','scale',1):{float(i):2 for i in range(1,400)}}
g=a.adjust.commit_steps(r,values); next(g); g.close()
assert digest==repr([(c.data_path,c.array_index,a.core.snapshot(c)) for c in bag.fcurves])
assert [g.name for g in bag.groups]==group_names
# Quaternion and axis-angle channels keep their representation and selected times.
for mode in ('QUATERNION','AXIS_ANGLE'):
 act=bpy.data.actions.new('Adjust_'+mode); sl=act.slots.new('OBJECT',obj.name)
 bg=act.layers.new('Layer').strips.new(type='KEYFRAME').channelbag(sl,ensure=True)
 prop='rotation_quaternion' if mode=='QUATERNION' else 'rotation_axis_angle'
 obj.pose.bones['Root'].rotation_mode=mode
 obj.pose.bones['Root'].rotation_quaternion=(1,0,0,0); obj.pose.bones['Root'].rotation_axis_angle=(0,0,0,1);
 obj.pose.bones['Root'].select=True; obj.pose.bones['Hand'].select=False
 curve=bg.fcurves.new('pose.bones["Root"].'+prop,index=0)
 for frame in (1,11):
  point=curve.keyframe_points.insert(frame,1 if mode=='QUATERNION' else 0); point.select_control_point=True
 obj.animation_data.action=act; obj.animation_data.action_slot=sl
 bpy.context.scene.frame_set(1)
 req=a.adjust.capture(bpy.context,obj)
 plans=consume(a.adjust.steps(req,{'Root':delta},'PATH','Root'))
 a.adjust.commit(req,plans)
 assert all({p.co.x for p in c.keyframe_points}<={1,11} for c in bg.fcurves)
 bpy.context.scene.frame_set(11)
 assert (obj.pose.bones['Root'].matrix.to_quaternion()@Vector((1,0,0))-Vector((0,1,0))).length<1e-4
 assert obj.pose.bones['Root'].rotation_mode==mode
# IK target and pole detection, with the selected-key frame union for added controls.
bpy.ops.object.mode_set(mode='EDIT')
for name in ('IKControl','PoleControl'):
 b=arm.edit_bones.new(name); b.head=(3,0,0); b.tail=(3,1,0)
bpy.ops.object.mode_set(mode='POSE')
ik=obj.pose.bones['Hand'].constraints.new('IK'); ik.target=obj; ik.subtarget='IKControl'; ik.pole_target=obj; ik.pole_subtarget='PoleControl'; ik.chain_count=2
assert a.adjust.missing_ik(obj,{'Root','Hand'})==['IKControl','PoleControl']
assert not a.adjust.missing_ik(obj,{'Root','Hand','IKControl','PoleControl'})
print('ADJUST_EXTRA_PASS staged_write_cancel rollback_groups quaternion axis_angle IK_target_pole')

obj.pose.bones['Hand'].constraints.remove(ik)
obj.pose.bones['Root'].rotation_mode='XYZ'
obj.animation_data.action=action; obj.animation_data.action_slot=slot
for b in obj.pose.bones: b.select=b.name in {'Root','Hand'}
bpy.context.scene.frame_set(1)

# Empty Cycles placeholders do not replace static pose values with zero.
empty=bag.fcurves.new('pose.bones["Root"].scale',index=0); empty.modifiers.new('CYCLES')
obj.pose.bones['Root'].scale=(1,1,1); bpy.context.scene.frame_set(1)
req=a.adjust.capture(bpy.context,obj)
plans=consume(a.adjust.steps(req,{n:Matrix.Translation((0,0,1)) for n in req['times']},'PATH','Root'))
assert ('Root','scale',0) not in plans
assert not empty.keyframe_points and len(empty.modifiers)==1
bag.fcurves.remove(empty)
print('ADJUST_EMPTY_CYCLES_PASS static_scale_preserved')
