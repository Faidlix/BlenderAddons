import bpy,sys,os,importlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
a=importlib.import_module(os.environ.get('BCK_TEST_MODULE','Faidlix_BatchCleanKey'))
if not hasattr(bpy.types.WindowManager,'faidlix_batch_clean_key'):a.register()
if bpy.context.object and bpy.context.object.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
arm=bpy.data.armatures.new('NeighborRig');obj=bpy.data.objects.new('NeighborRig',arm);bpy.context.collection.objects.link(obj)
for ob in bpy.context.selected_objects:ob.select_set(False)
obj.select_set(True);bpy.context.view_layer.objects.active=obj
bpy.ops.object.mode_set(mode='EDIT');bone=arm.edit_bones.new('UniqueNeighborBone');bone.head=(0,0,0);bone.tail=(0,1,0)
bpy.ops.object.mode_set(mode='POSE')
s=bpy.context.window_manager.faidlix_batch_clean_key;s.target_armature=obj
actions=[]
for name in ('Neighbor_A','Neighbor_B','Neighbor_C'):
 act=bpy.data.actions.new(name);sl=act.slots.new('OBJECT',obj.name);bag=act.layers.new('Layer').strips.new(type='KEYFRAME').channelbag(sl,ensure=True)
 c=bag.fcurves.new('pose.bones["UniqueNeighborBone"].location',index=0);c.keyframe_points.insert(1,0);c.keyframe_points.insert(11,1)
 actions.append(act)
a.core.assign_action(bpy.context,obj,actions[1]);a.ui.refresh(bpy.context)
assert bpy.ops.faidlix_batch_clean_key.delete_action(action_name='Neighbor_B')=={'FINISHED'}
assert obj.animation_data.action==actions[0] and s.browser_index==0
a.ui.refresh(bpy.context);assert s.browser_index==0
assert bpy.ops.faidlix_batch_clean_key.duplicate(action_name='Neighbor_A',destination='CURRENT')=={'FINISHED'}
copy=obj.animation_data.action;assert copy.name.startswith('Neighbor_A_Copy') and s.browser[s.browser_index].action==copy
assert bpy.ops.faidlix_batch_clean_key.delete_action(action_name=copy.name)=={'FINISHED'}
assert obj.animation_data.action==actions[0]
assert bpy.ops.faidlix_batch_clean_key.delete_action(action_name='Neighbor_A')=={'FINISHED'}
assert obj.animation_data.action==actions[2] and s.browser_index==0
assert bpy.ops.faidlix_batch_clean_key.delete_action(action_name='Neighbor_C')=={'FINISHED'}
assert not obj.animation_data.action and s.browser_index==-1 and not s.browser
assert bpy.ops.faidlix_batch_clean_key.duplicate.get_rna_type().properties['destination'].name=='複製 Action 到'
print('ACTION_NEIGHBORS_PASS previous first_next empty duplicate_selected refresh_index_stable')
