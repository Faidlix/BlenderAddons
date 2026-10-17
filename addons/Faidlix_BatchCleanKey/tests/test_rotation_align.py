"""Blender --background --factory-startup --python this_file.py.
Verify common-reference alignment, pose equivalence, sparse quaternion and skipped cases.
BCK_TEST_MODULE selects a freshly installed extension for release verification.
"""
import bpy,math,importlib,os,sys
from pathlib import Path
from mathutils import Euler,Quaternion
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
a=importlib.import_module(os.environ.get('BCK_TEST_MODULE','Faidlix_BatchCleanKey'))
if not hasattr(bpy.types.WindowManager,'faidlix_batch_clean_key'):a.register()
if bpy.context.object and bpy.context.object.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
obj=bpy.data.objects.new('AlignRig',bpy.data.armatures.new('AlignRig'));bpy.context.collection.objects.link(obj)
for o in bpy.context.selected_objects:o.select_set(False)
obj.select_set(True);bpy.context.view_layer.objects.active=obj
bpy.ops.object.mode_set(mode='EDIT')
for i,name in enumerate(('EulerA','EulerB','Quat','Untouched')):
 b=obj.data.edit_bones.new(name);b.head=(i,0,0);b.tail=(i,1,0)
bpy.ops.object.mode_set(mode='POSE')
for b in obj.pose.bones:b.select=b.name!='Untouched';b.rotation_mode='XYZ'
obj.pose.bones['Quat'].rotation_mode='QUATERNION'
act=bpy.data.actions.new('AlignTest');slot=act.slots.new('OBJECT',obj.name)
bag=act.layers.new('Layer').strips.new(type='KEYFRAME').channelbag(slot,ensure=True)
obj.animation_data_create().action=act;obj.animation_data.action_slot=slot

def curve(bone,prop,index,values,selected=()):
 c=bag.fcurves.new(obj.pose.bones[bone].path_from_id(prop),index=index)
 for f,v in values:
  p=c.keyframe_points.insert(f,v);p.select_control_point=f in selected
  p.interpolation='BEZIER';p.handle_left_type=p.handle_right_type='FREE'
 c.update()
 return c
r=math.radians
ca=curve('EulerA','rotation_euler',2,[(1,r(10)),(2,r(380)),(3,r(390)),(4,r(400))],(2,3))
cb=curve('EulerB','rotation_euler',2,[(1,r(0)),(2,r(720)),(3,r(740)),(4,r(20))],(3,))
loc=curve('EulerA','location',0,[(1,4),(2,5),(3,7)],(2,3))
u=curve('Untouched','rotation_euler',2,[(1,0),(2,9)],(2,))
q=Quaternion((0,0,1),r(35))
qc=[curve('Quat','rotation_quaternion',i,[(1,q[i]),(2,-q[i]),(3,-q[i]),(4,q[i])],(2,3)) for i in range(4)]
savedloc=a.core.snapshot(loc);savedu=a.core.snapshot(u)
before={f:Euler((0,0,ca.evaluate(f)),'XYZ').to_quaternion() for f in (2,3)}
assert bpy.ops.faidlix_batch_clean_key.rotation_align(direction='PREVIOUS')=={'FINISHED'}
assert math.isclose(ca.evaluate(2),r(20),abs_tol=1e-5) and math.isclose(ca.evaluate(3),r(30),abs_tol=1e-5)
# Shared boundary is frame 2, so B at frame 3 must reference 1, not unselected 2.
assert math.isclose(cb.evaluate(3),r(20),abs_tol=1e-5)
assert math.isclose(cb.evaluate(2),r(720),abs_tol=1e-5)
assert math.isclose(ca.evaluate(4),r(400),abs_tol=1e-5)
for f,original in before.items():assert abs(original.dot(Euler((0,0,ca.evaluate(f)),'XYZ').to_quaternion()))>1-1e-6
for f in (2,3):assert Quaternion([c.evaluate(f) for c in qc]).dot(q)>1-1e-6
assert a.core.snapshot(loc)==savedloc and a.core.snapshot(u)==savedu
assert bpy.ops.faidlix_batch_clean_key.rotation_align(direction='NEXT')=={'FINISHED'}
assert math.isclose(ca.evaluate(2),r(380),abs_tol=1e-5) and math.isclose(ca.evaluate(3),r(390),abs_tol=1e-5)
# Sparse quaternion: missing channels are added only at the selected original time.
for c in bag.fcurves:
 for p in c.keyframe_points:p.select_control_point=False
p=qc[0].keyframe_points[1];p.co.y=-q[0];p.select_control_point=True
for c in qc[1:]:
 for p in list(c.keyframe_points):
  if p.co.x==2:c.keyframe_points.remove(p)
 c.update()
vals=[c.evaluate(2) for c in qc]
a.rotation_align.align(bpy.context,'PREVIOUS')
assert all(any(p.co.x==2 for p in c.keyframe_points) for c in qc)
assert all(math.isclose(c.evaluate(2),-v,abs_tol=1e-6) for c,v in zip(qc,vals))
# Missing reference and locked channels do not mutate.
for c in bag.fcurves:
 for p in c.keyframe_points:p.select_control_point=p.co.x==1
snapshot=repr([a.core.snapshot(c) for c in bag.fcurves])
changed,skipped=a.rotation_align.align(bpy.context,'PREVIOUS');assert changed==0 and skipped
assert repr([a.core.snapshot(c) for c in bag.fcurves])==snapshot
for c in bag.fcurves:
 for p in c.keyframe_points:p.select_control_point=False
ca.lock=True;bpy.context.scene.frame_set(2)
old=a.core.snapshot(ca);a.rotation_align.align(bpy.context,'PREVIOUS');assert a.core.snapshot(ca)==old
print('ROTATION_ALIGN_PASS common_range previous next pose_equivalent unselected_unchanged sparse_quaternion missing_reference locked current_frame')
