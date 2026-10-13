import bpy,sys,os,json,importlib,math
from pathlib import Path
from mathutils import Matrix
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'addons'))
a=importlib.import_module(os.environ.get('BCK_TEST_MODULE','Faidlix_BatchCleanKey'))
if not hasattr(bpy.types.WindowManager,'faidlix_batch_clean_key'): a.register()
if bpy.context.object and bpy.context.object.mode!='OBJECT': bpy.ops.object.mode_set(mode='OBJECT')
arm=bpy.data.armatures.new('SparseParent'); obj=bpy.data.objects.new('SparseParent',arm); bpy.context.collection.objects.link(obj)
for o in bpy.context.selected_objects: o.select_set(False)
obj.select_set(True); bpy.context.view_layer.objects.active=obj
bpy.ops.object.mode_set(mode='EDIT')
r=arm.edit_bones.new('Hips'); r.head=(0,0,0); r.tail=(0,1,0)
s=arm.edit_bones.new('Skirt'); s.head=(1,0,0); s.tail=(1,1,0); s.parent=r
bpy.ops.object.mode_set(mode='POSE')
for b in obj.pose.bones: b.select=True; b.rotation_mode='QUATERNION'
act=bpy.data.actions.new('SparseParentAction'); slot=act.slots.new('OBJECT',obj.name); bag=act.layers.new('Layer').strips.new(type='KEYFRAME').channelbag(slot,ensure=True)
for name,frames in [('Hips',(0,10,30,40,60)),('Skirt',(0,15,25,30,45,60))]:
 for i in range(4):
  c=bag.fcurves.new(obj.pose.bones[name].path_from_id('rotation_quaternion'),index=i)
  for f in frames:
   p=c.keyframe_points.insert(f,1 if i==0 else 0); p.select_control_point=True
obj.animation_data_create().action=act; obj.animation_data.action_slot=slot
bpy.context.scene.frame_set(45); bpy.context.scene.tool_settings.transform_pivot_point='MEDIAN_POINT'
req=a.adjust.capture(bpy.context,obj)
pivot=a.adjust.center({n:Matrix(m) for n,m in req['before'].items()},req['selected'],req['pivot'],req['active'],req['cursor'])
d=Matrix.Translation(pivot)@Matrix.Rotation(math.pi/4,4,'Z')@Matrix.Translation(-pivot)
g=a.adjust.steps(req,{n:d for n in req['selected']},'LOCAL')
while True:
 try: next(g)
 except StopIteration as end: plans=end.value; break
assert not any(n=='Skirt' for n,p,i in plans),plans
assert all(set(v)<={0,10,30,40,60} for (n,p,i),v in plans.items() if n=='Hips')
a.adjust.commit(req,plans); bpy.context.scene.frame_set(45)
assert obj.pose.bones['Skirt'].location.length<2e-6
assert not any('Skirt' in c.data_path and c.data_path.endswith('.location') for c in bag.fcurves)
print('ADJUST_SPARSE_PARENT_PASS no_child_translation no_extra_parent_frames')
# Optional real rig regression data exported read-only from the user's scene.
path=ROOT/'validation/skirt-source-v150.json'
if path.exists():
 data=json.loads(path.read_text(encoding='utf-8'))
 bpy.ops.object.mode_set(mode='OBJECT'); obj.select_set(False)
 arm=bpy.data.armatures.new('ActualSkirt'); obj=bpy.data.objects.new('ActualSkirt',arm); bpy.context.collection.objects.link(obj)
 obj.select_set(True); bpy.context.view_layer.objects.active=obj; bpy.ops.object.mode_set(mode='EDIT')
 for entry in data['bones']:
  b=arm.edit_bones.new(entry['name']); b.matrix=Matrix(entry['matrix']); b.length=entry['length']
 for entry in data['bones']:
  b=arm.edit_bones[entry['name']]
  if entry['parent']: b.parent=arm.edit_bones[entry['parent']]
  b.use_connect=entry['connected']
 bpy.ops.object.mode_set(mode='POSE'); obj.matrix_world=Matrix(data['world'])
 for entry in data['bones']:
  b=arm.bones[entry['name']]; b.inherit_scale=entry['inherit_scale']; b.use_inherit_rotation=entry['use_inherit_rotation']; b.use_local_location=entry['use_local_location']
  pb=obj.pose.bones[entry['name']]; pb.rotation_mode=entry['mode']; pb.select=True
  for prop,value in entry['defaults'].items(): setattr(pb,prop,value)
 act=bpy.data.actions.new('ActualSkirtAction'); slot=act.slots.new('OBJECT',obj.name); bag=act.layers.new('Layer').strips.new(type='KEYFRAME').channelbag(slot,ensure=True)
 for curve in data['actions']['Crouch_Walk']:
  c=bag.fcurves.new(curve['path'],index=curve['index']); a.core.write_points(c,curve['points'])
  for p in c.keyframe_points: p.select_control_point=True
 obj.animation_data_create().action=act; obj.animation_data.action_slot=slot; bpy.context.scene.frame_set(45)
 req=a.adjust.capture(bpy.context,obj)
 p0=a.adjust.center({n:Matrix(m) for n,m in req['before'].items()},req['selected'],req['pivot'],req['active'],req['cursor'])
 d=Matrix.Translation(p0)@Matrix.Rotation(math.pi/4,4,'Z')@Matrix.Translation(-p0)
 g=a.adjust.steps(req,{n:d for n in req['selected']},'LOCAL')
 while True:
  try: next(g)
  except StopIteration as end: plans=end.value; break
 bad={k:v for k,v in plans.items() if 'Skirt' in k[0] and k[1] in {'location','scale'}}
 assert not bad,bad
 print('ACTUAL_SKIRT_DATA_PASS 81_bones sparse_hips no_skirt_location_scale_changes')
