"""Run Blender --background --factory-startup --python this_file.py.
Test multi-bone shared anchors, sparse channels, constant subframes and untouched keys.
BCK_TEST_MODULE optionally names an installed extension.
"""
import bpy,sys,os,importlib,math
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
a=importlib.import_module(os.environ.get('BCK_TEST_MODULE','Faidlix_BatchCleanKey'))
if not hasattr(bpy.types.WindowManager,'faidlix_batch_clean_key'):a.register()
if bpy.context.object and bpy.context.object.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
obj=bpy.data.objects.new('HoldRig',bpy.data.armatures.new('HoldRig'));bpy.context.collection.objects.link(obj)
for o in bpy.context.selected_objects:o.select_set(False)
obj.select_set(True);bpy.context.view_layer.objects.active=obj
bpy.ops.object.mode_set(mode='EDIT')
for i,n in enumerate(('A','B','Other')):
 b=obj.data.edit_bones.new(n);b.head=(i,0,0);b.tail=(i,1,0)
bpy.ops.object.mode_set(mode='POSE')
for b in obj.pose.bones:b.select=b.name!='Other';b.rotation_mode='XYZ'
obj.pose.bones['B'].rotation_mode='QUATERNION'

def fixture(name):
 act=bpy.data.actions.new(name);slot=act.slots.new('OBJECT',obj.name)
 bag=act.layers.new('L').strips.new(type='KEYFRAME').channelbag(slot,ensure=True)
 obj.animation_data_create().action=act;obj.animation_data.action_slot=slot
 for bone,prop,i,values,selected in (
  ('A','location',0,[(0,8),(1,2),(3,7),(5,9),(7,12)],{1,3,5}),
  ('A','rotation_euler',2,[(1,.2),(3,1),(5,2)],{1,3,5}),
  ('A','scale',0,[(1,1),(3,2),(5,3)],{1,3,5}),
  ('B','location',1,[(1,11),(3,15),(5,19)],{3,5}),
  ('B','rotation_quaternion',0,[(1,1),(3,.5),(5,.7)],{3,5}),
  ('B','rotation_quaternion',3,[(1,0),(3,.866),(5,.714)],{3,5}),
  ('Other','location',2,[(1,5),(3,9),(5,8)],{1,3,5})):
  c=bag.fcurves.new(obj.pose.bones[bone].path_from_id(prop),index=i)
  for frame,value in values:
   p=c.keyframe_points.insert(frame,value);p.interpolation='BEZIER';p.select_control_point=frame in selected
  c.update()
  for p in c.keyframe_points:
   p.handle_left_type=p.handle_right_type='FREE'
   p.handle_left=(p.co.x-.3,p.co.y+4);p.handle_right=(p.co.x+.3,p.co.y-3)
 return act,bag
for anchor,ref in (('FIRST',1),('LAST',5)):
 act,bag=fixture('Hold'+anchor)
 before={}
 for bone,frames in (('A',(1,3,5)),('B',(3,5))):
  b=obj.pose.bones[bone];rot='rotation_euler' if bone=='A' else 'rotation_quaternion'
  for prop in ('location',rot):
   for i,d in enumerate(getattr(b,prop)):
    c=bag.fcurves.find(b.path_from_id(prop),index=i)
    before[bone,prop,i]=c.evaluate(ref) if c else d
 preserved={ (c.data_path,c.array_index):a.core.snapshot(c) for c in bag.fcurves if 'Other' in c.data_path or c.data_path.endswith('.scale') }
 assert bpy.ops.faidlix_batch_clean_key.pose_hold(anchor=anchor)=={'FINISHED'}
 for bone,frames in (('A',(1,3,5)),('B',(3,5))):
  b=obj.pose.bones[bone];rot='rotation_euler' if bone=='A' else 'rotation_quaternion'
  for prop in ('location',rot):
   for i in range(len(getattr(b,prop))):
    c=bag.fcurves.find(b.path_from_id(prop),index=i);v=before[bone,prop,i]
    for step in range(41):
     f=frames[0]+(frames[-1]-frames[0])*step/40
     assert math.isclose(c.evaluate(f),v,abs_tol=1e-5),(anchor,bone,prop,i,f,c.evaluate(f),v)
    assert all(p.co.x in {0,1,3,5,7} for p in c.keyframe_points)
 for (path,i),snapshot in preserved.items():assert a.core.snapshot(bag.fcurves.find(path,index=i))==snapshot
 c=bag.fcurves.find(obj.pose.bones['A'].path_from_id('location'),index=0)
 assert c.keyframe_points[0].co.y==8 and c.keyframe_points[-1].co.y==12
act,bag=fixture('HoldLocked');bag.fcurves[0].lock=True
old=a.core.snapshot(bag.fcurves[0]);held,skipped,ref=a.pose_hold.hold(bpy.context,'FIRST')
assert held==['B'] and skipped==['A'] and a.core.snapshot(bag.fcurves[0])==old
for c in bag.fcurves:
 for p in c.keyframe_points:p.select_control_point=False
try:a.pose_hold.hold(bpy.context,'FIRST');raise AssertionError('empty selection accepted')
except ValueError:pass
print('POSE_HOLD_PASS multi_bone shared_first_last sparse_channels constant_subframes no_new_frames scale_unselected_preserved locked empty')
