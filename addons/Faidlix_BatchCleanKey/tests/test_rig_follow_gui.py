"""Native GUI rig-selection regression. Run isolated Blender --enable-event-simulate --python this_file.py.
BCK_TEST_MODULE can select an installed extension; output goes to validation/rig-follow-gui-result.txt.
"""
import bpy,sys,os,importlib,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'addons'))
assert not bpy.app.background and not bpy.data.filepath
a=importlib.import_module(os.environ.get('BCK_TEST_MODULE','Faidlix_BatchCleanKey'))
if not hasattr(bpy.types.WindowManager,'faidlix_batch_clean_key'):a.register()
bpy.context.preferences.view.show_splash=False
bpy.context.preferences.filepaths.use_auto_save_temporary_files=False
rigs=[]
for i in range(2):
 arm=bpy.data.armatures.new('FollowRig'+str(i));obj=bpy.data.objects.new(arm.name,arm);bpy.context.collection.objects.link(obj)
 for ob in bpy.context.selected_objects:ob.select_set(False)
 obj.select_set(True);bpy.context.view_layer.objects.active=obj
 bpy.ops.object.mode_set(mode='EDIT');bone=arm.edit_bones.new('UniqueBone'+str(i));bone.head=(0,0,0);bone.tail=(0,0,1)
 bpy.ops.object.mode_set(mode='OBJECT')
 act=bpy.data.actions.new('FollowAction'+str(i));slot=act.slots.new('OBJECT',obj.name)
 c=act.layers.new('Layer').strips.new(type='KEYFRAME').channelbag(slot,ensure=True).fcurves.new('pose.bones["UniqueBone'+str(i)+'"].location',index=0)
 c.keyframe_points.insert(1,i);c.keyframe_points.insert(11,i+1)
 obj.animation_data_create().action=act;obj.animation_data.action_slot=slot;rigs.append(obj)
area=next(ar for ar in bpy.context.screen.areas if ar.type=='VIEW_3D');region=next(r for r in area.regions if r.type=='WINDOW')
s=bpy.context.window_manager.faidlix_batch_clean_key
stage=0;started=time.monotonic();out=ROOT/'validation/rig-follow-gui-result.txt'
def choose(obj):
 if bpy.context.object and bpy.context.object.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
 for ob in bpy.context.selected_objects:ob.select_set(False)
 obj.select_set(True);bpy.context.view_layer.objects.active=obj
def check(i):
 assert s.target_armature==rigs[i] and s.armature==rigs[i]
 assert bpy.context.object==rigs[i] and rigs[i].mode=='POSE'
 assert [x.action.name for x in s.browser]==['FollowAction'+str(i)]
def test():
 global stage
 try:
  assert time.monotonic()-started<30,stage
  with bpy.context.temp_override(area=area,region=region):
   if stage==0:choose(rigs[0]);stage=1
   elif stage==1:
    check(0);choose(rigs[1]);stage=2
   elif stage==2:
    check(1);s.target_armature=rigs[0];check(0);stage=3
   elif stage==3:
    check(0)
    # Mimic the eyedropper callback from an editor without a 3D area.
    properties=next(ar for ar in bpy.context.screen.areas if ar.type=='PROPERTIES')
    with bpy.context.temp_override(area=properties):s.target_armature=rigs[1]
    check(1);choose(bpy.data.objects['Cube']);stage=4
   elif stage==4:
    assert s.target_armature==rigs[1] and bpy.context.object.name=='Cube'
    choose(rigs[1]);stage=5
   elif stage==5:
    check(1);bpy.ops.wm.call_panel(name='BCK_PT_view3d',keep_open=True);stage=6
   elif stage==6:
    bpy.ops.screen.screenshot(filepath=str(ROOT/'validation/rig-follow-v171.png'))
    out.write_text('RIG_FOLLOW_GUI_PASS selection picker eyedropper_context Pose list isolation mesh_preserved return_to_same_rig',encoding='utf-8')
    bpy.ops.wm.quit_blender();return None
  return .7
 except Exception:
  out.write_text(traceback.format_exc(),encoding='utf-8');bpy.ops.wm.quit_blender();return None
bpy.app.timers.register(test,first_interval=2)
