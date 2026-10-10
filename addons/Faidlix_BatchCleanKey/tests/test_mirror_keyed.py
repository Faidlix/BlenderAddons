"""Sparse channels must stay sparse after a mirrored Action swap."""
import bpy, importlib, os, sys
from types import SimpleNamespace
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
addon=importlib.import_module(os.environ.get('BCK_TEST_MODULE','Faidlix_BatchCleanKey'))
if not hasattr(bpy.types.WindowManager,'faidlix_batch_clean_key'): addon.register()
if bpy.context.object and bpy.context.object.mode!='OBJECT': bpy.ops.object.mode_set(mode='OBJECT')
arm=bpy.data.armatures.new('SparseMirror'); obj=bpy.data.objects.new('SparseMirror',arm)
bpy.context.collection.objects.link(obj)
for o in bpy.context.selected_objects: o.select_set(False)
obj.select_set(True); bpy.context.view_layer.objects.active=obj
bpy.ops.object.mode_set(mode='EDIT')
for name,x in [('Bone.L',1),('Bone.R',-1),('Static',0)]:
    b=arm.edit_bones.new(name); b.head=(x,0,0); b.tail=(x,1,0)
bpy.ops.object.mode_set(mode='POSE')
for b in obj.pose.bones:
    b.rotation_mode='XYZ'; b.location=(.2,.3,.4); b.rotation_euler=(.1,.2,.3); b.scale=(1.2,1.3,1.4)
a=bpy.data.actions.new('SparseMirror'); slot=a.slots.new('OBJECT',obj.name)
bag=a.layers.new('Layer').strips.new(type='KEYFRAME').channelbag(slot,ensure=True)
source_times={}
for name,prop,index,value,times in [('Bone.L','location',0,.7,(1,4.5)),('Bone.L','rotation_euler',1,.5,(1,3,7)),
                             ('Bone.R','scale',2,1.8,(1,9))]:
    c=bag.fcurves.new(obj.pose.bones[name].path_from_id()+'.'+prop,index=index)
    for j,frame in enumerate(times): c.keyframe_points.insert(frame,value+.1*j)
    source_times[obj.pose.bones[bpy.utils.flip_name(name)].path_from_id()+'.'+prop,index]=times
empty=bag.fcurves.new(obj.pose.bones['Static'].path_from_id()+'.location',index=2)
empty.modifiers.new('CYCLES')
addon.core.assign_action(bpy.context,obj,a)
def digest(action):
    return repr([(c.data_path,c.array_index,addon.core.snapshot(c)) for c in addon.core.action_curves(action)])
before=digest(a)
def consume(g):
    while True:
        try: next(g)
        except StopIteration as done: return done.value
g=addon.ui.mirror.steps(bpy.context,obj,a,'COPY',1,True); next(g); g.close()
assert digest(a)==before
result=consume(addon.ui.mirror.steps(bpy.context,obj,a,'COPY',1,True))
flipped=bpy.data.actions[result['flip_action']]
expected={(obj.pose.bones['Bone.R'].path_from_id()+'.location',0),
          (obj.pose.bones['Bone.R'].path_from_id()+'.rotation_euler',1),
          (obj.pose.bones['Bone.L'].path_from_id()+'.scale',2),
          (obj.pose.bones['Static'].path_from_id()+'.location',2)}
actual={(c.data_path,c.array_index) for c in addon.core.action_curves(flipped)}
assert actual==expected,(actual,expected)
def check_times(action):
    for c in addon.core.action_curves(action):
        key=(c.data_path,c.array_index)
        if key not in source_times: continue
        assert tuple(p.co.x for p in c.keyframe_points)==source_times[key],(key,[p.co.x for p in c.keyframe_points])
        assert all(p.interpolation=='BEZIER' and p.handle_left_type=='AUTO_CLAMPED' and p.handle_right_type=='AUTO_CLAMPED' for p in c.keyframe_points)
check_times(flipped)
# Hidden interval cannot affect original per-curve times, including subframes.
check_times(bpy.data.actions[consume(addon.ui.mirror.steps(bpy.context,obj,a,'COPY',100,True))['flip_action']])
assert digest(a)==before
bpy.context.scene.frame_set(1)
left,right=obj.pose.bones['Bone.L'],obj.pose.bones['Bone.R']
assert abs(right.location.x+.7)<1e-5
assert abs(right.location.y-.3)<1e-5 and abs(right.location.z-.4)<1e-5
assert abs(left.scale.z-1.8)<1e-5 and abs(left.scale.x-1.2)<1e-5
assert abs(right.rotation_euler.x-.1)<1e-5 and abs(right.rotation_euler.z-.3)<1e-5
assert not bpy.ops.faidlix_batch_clean_key.flip.get_rna_type().properties['keyed_only'].default
# Operator property must be propagated through the synchronous/modal job factory.
assert bpy.ops.faidlix_batch_clean_key.flip(action_name=a.name,keyed_only=True)=={'FINISHED'}
assert bpy.context.window_manager.faidlix_batch_clean_key.flip_keyed_only
assert {(c.data_path,c.array_index) for c in addon.core.action_curves(obj.animation_data.action)}==expected
check_times(obj.animation_data.action)
track=obj.animation_data.nla_tracks.new()
strip=track.strips.new('SparseNLA',10,a); strip.mute=True
name=a.name
consume(addon.ui.mirror.steps(bpy.context,obj,a,'IN_PLACE',1,True))
assert strip.action==obj.animation_data.action and strip.action.name==name
assert {(c.data_path,c.array_index) for c in addon.core.action_curves(strip.action)}==expected
check_times(strip.action)
# Check both layouts, so the hidden interval cannot be accidentally drawn again.
class Layout:
    def __init__(self,log,row=False): self.log,self.is_row=log,row
    def row(self,**kwargs): return Layout(self.log,True)
    def prop(self,owner,name,**kwargs): self.log.append((name,self.is_row,kwargs))
    def label(self,**kwargs): pass
for enabled in (False,True):
    log=[]
    addon.ui.BCK_OT_Flip.draw(SimpleNamespace(layout=Layout(log),action_name=name,keyed_only=enabled,kind='MIRROR'),bpy.context)
    button=next(item for item in log if item[0]=='keyed_only')
    assert button[1] and button[2].get('toggle')
    interval=[item for item in log if item[0]=='sample_step']
    assert bool(interval)==(not enabled)
    if interval: assert interval[0][1] and log.index(button)<log.index(interval[0])
print('MIRROR_KEYED_PASS per_curve_times subframes no_resampling Bezier sparse_components static_values empty_curves source_preserved cancel operator_option NLA')
