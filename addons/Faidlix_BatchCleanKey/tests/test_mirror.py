import bpy,sys,os,importlib
from pathlib import Path
from mathutils import Matrix,Vector,Euler
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
addon=importlib.import_module(os.environ.get('BCK_TEST_MODULE','Faidlix_BatchCleanKey'))
if not hasattr(bpy.types.WindowManager,'faidlix_batch_clean_key'): addon.register()
if bpy.context.object and bpy.context.object.mode!='OBJECT': bpy.ops.object.mode_set(mode='OBJECT')
arm=bpy.data.armatures.new('MirrorRig'); obj=bpy.data.objects.new('MirrorRig',arm)
bpy.context.collection.objects.link(obj)
for o in bpy.context.selected_objects: o.select_set(False)
obj.select_set(True); bpy.context.view_layer.objects.active=obj
bpy.ops.object.mode_set(mode='EDIT')
# The user's Hips has local Z along armature X, not local X.
hips=Matrix(((0,0,-1,0),(-1,0,0,0),(0,1,0,.525),(0,0,0,1)))
rests={'Hips':hips}
for name,x,angles,parent in [('Left_UpperLeg',.053,(.8,.3,1.2),'Hips'),('Right_UpperLeg',-.053,(-.3,-.9,.4),'Hips'),
 ('Left_LowerLeg',.057,(.4,-.5,.6),'Left_UpperLeg'),('Right_LowerLeg',-.057,(-.2,.8,-.7),'Right_UpperLeg'),
 ('FBR_IK_Hand.L',.275,(1.57,0,.0246),None),('FBR_IK_Hand.R',-.275,(1.57,0,-.0246),None)]:
 mat=Euler(angles).to_matrix().to_4x4(); mat.translation=(x,0,.3 if 'Lower' in name else .49 if 'Leg' in name else .73)
 rests[name]=mat
for name,mat in rests.items():
 b=arm.edit_bones.new(name); b.head=mat.translation; b.tail=b.head+mat.to_3x3()@Vector((0,.12,0)); b.matrix=mat
for name in rests:
 parent='Hips' if 'UpperLeg' in name else name.replace('Lower','Upper') if 'LowerLeg' in name else None
 if parent: arm.edit_bones[name].parent=arm.edit_bones[parent]
bpy.ops.object.mode_set(mode='POSE')
a=bpy.data.actions.new('RestAwareMirror'); a.use_fake_user=True
slot=a.slots.new('OBJECT',obj.name); bag=a.layers.new('Layer').strips.new(type='KEYFRAME').channelbag(slot,ensure=True)
for j,b in enumerate(obj.pose.bones):
 b.rotation_mode='XYZ' if j%2 else 'QUATERNION'
 for frame in (1,3,5):
  q=Euler((.1*j+.03*frame,.2*frame,.1*j-.12*frame)).to_quaternion()
  data={'location':(.02*frame,.01*j,-.03*frame),'scale':(1,1,1)}
  data['rotation_euler' if b.rotation_mode=='XYZ' else 'rotation_quaternion']=tuple(q.to_euler('XYZ') if b.rotation_mode=='XYZ' else q)
  for prop,values in data.items():
   for i,v in enumerate(values):
    path=b.path_from_id()+'.'+prop
    c=bag.fcurves.find(path,index=i) or bag.fcurves.new(path,index=i)
    c.keyframe_points.insert(frame,v).interpolation='LINEAR'
# Modifiers are evaluated and baked, rather than rejected.
c=bag.fcurves.find(obj.pose.bones['Hips'].path_from_id()+'.location',index=1)
c.modifiers.new('CYCLES')
def digest(action):
 return repr([(c.data_path,c.array_index,[m.type for m in c.modifiers],addon.core.snapshot(c)) for c in addon.core.action_curves(action)])
original=digest(a)
addon.core.assign_action(bpy.context,obj,a)
times=[1+i*.25 for i in range(17)]
source={}
for t in times:
 bpy.context.scene.frame_set(int(t),subframe=t%1)
 source[t]={b.name:b.matrix.copy() for b in obj.pose.bones}
def consume(g):
 while True:
  try: next(g)
  except StopIteration as end: return end.value
g=addon.ui.mirror.steps(bpy.context,obj,a,'COPY',.25)
next(g); g.close()
assert digest(a)==original and not any(x.name.startswith('__BCK_Mirror__') for x in bpy.data.actions)
result=consume(addon.ui.mirror.steps(bpy.context,obj,a,'COPY',.25))
flipped=bpy.data.actions[result['flip_action']]
assert digest(a)==original and flipped!=a
reflect=Matrix.Diagonal((-1,1,1,1)); maxerror=0
for t in times:
 bpy.context.scene.frame_set(int(t),subframe=t%1)
 for b in obj.pose.bones:
  src=bpy.utils.flip_name(b.name)
  expected=reflect@source[t][src]@obj.data.bones[src].matrix_local.inverted()@reflect@b.bone.matrix_local
  error=max(abs(b.matrix[i][j]-expected[i][j]) for i in range(4) for j in range(4))
  maxerror=max(error,maxerror)
  assert error<2e-5,(t,b.name,error)
second=consume(addon.ui.mirror.steps(bpy.context,obj,flipped,'COPY',.25))
for t in times:
 bpy.context.scene.frame_set(int(t),subframe=t%1)
 for b in obj.pose.bones:
  assert max(abs(b.matrix[i][j]-source[t][b.name][i][j]) for i in range(4) for j in range(4))<3e-5,(t,b.name)
print('MIRROR_REST_SPACE_PASS rotated_hips asymmetric_roll parent_hierarchy IK_controls mixed_rotation_modes cycles double_flip source_preserved cancel',maxerror)
track=obj.animation_data.nla_tracks.new()
strip=track.strips.new('MirrorNLAUser',20,flipped); strip.mute=True
name=flipped.name
consume(addon.ui.mirror.steps(bpy.context,obj,flipped,'IN_PLACE',.25))
assert strip.action==obj.animation_data.action and strip.action.name==name
print('MIRROR_IN_PLACE_PASS preserves_name NLA_user_remap')
