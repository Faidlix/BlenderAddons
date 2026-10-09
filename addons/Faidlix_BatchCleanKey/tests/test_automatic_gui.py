import bpy,sys,os,importlib,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'addons'))
assert not bpy.app.background and not bpy.data.filepath
addon=importlib.import_module(os.environ.get('BCK_TEST_MODULE','Faidlix_BatchCleanKey'))
if not hasattr(bpy.types.WindowManager,'faidlix_batch_clean_key'): addon.register()
bpy.context.preferences.view.show_splash=False
bpy.context.preferences.filepaths.use_auto_save_temporary_files=False
arm=bpy.data.armatures.new('AutoGUI')
obj=bpy.data.objects.new('AutoGUI',arm)
bpy.context.collection.objects.link(obj)
for o in bpy.context.selected_objects: o.select_set(False)
obj.select_set(True); bpy.context.view_layer.objects.active=obj
bpy.ops.object.mode_set(mode='EDIT')
for i in range(5):
 b=arm.edit_bones.new('AutoGUIBone'+str(i)); b.head,b.tail=(i,0,0),(i,0,1)
bpy.ops.object.mode_set(mode='POSE')
actions=[]
for n in range(2):
 action=bpy.data.actions.new('AutoGUIAction'+str(n))
 slot=action.slots.new('OBJECT',obj.name)
 bag=action.layers.new('Layer').strips.new(type='KEYFRAME').channelbag(slot,ensure=True)
 for bone in obj.pose.bones:
  bone.rotation_mode='QUATERNION'; bone.select=True
  for i,value in enumerate((1,0,0,0)):
   c=bag.fcurves.new(bone.path_from_id()+'.rotation_quaternion',index=i)
   c.keyframe_points.add(2000)
   for f,p in enumerate(c.keyframe_points,1): p.co=f,value
   c.update()
   c.lock=True; c.modifiers.new('CYCLES')
 actions.append(action)
addon.core.assign_action(bpy.context,obj,actions[0])
def digest():
 return repr([(a.name,[(c.data_path,c.lock,c.mute,[m.type for m in c.modifiers],addon.core.snapshot(c)) for c in addon.core.action_curves(a)]) for a in bpy.data.actions if not a.name.startswith('__BCK_Auto__')])
before=digest()
area=next(a for a in bpy.context.screen.areas if a.type=='VIEW_3D')
region=next(r for r in area.regions if r.type=='WINDOW')
OUT=ROOT/'validation'; OUT.mkdir(exist_ok=True)
stage=0; started=time.monotonic()
def escape():
 bpy.context.window.event_simulate(type='ESC',value='PRESS')
 bpy.context.window.event_simulate(type='ESC',value='RELEASE')
def start(step):
 state=bpy.context.window_manager.faidlix_batch_clean_key
 state.rotation_target='XYZ'; state.sample_step=step
 for b in obj.pose.bones: b.select=False
 for item in state.actions: item.selected=False
 assert bpy.ops.faidlix_batch_clean_key.rotation('INVOKE_DEFAULT')=={'FINISHED'}
def test():
 global stage
 try:
  assert time.monotonic()-started<90
  with bpy.context.temp_override(area=area,region=region):
   state=bpy.context.window_manager.faidlix_batch_clean_key
   if stage==0:
    bpy.ops.ed.undo_push(message='Auto fixture'); start(1); stage=1
   elif stage==1:
    if not state.running: return .05
    if state.progress>.03:
     bpy.ops.screen.screenshot(filepath=str(OUT/'automatic-progress.png'))
     escape(); stage=2
   elif stage==2:
    if state.running: return .05
    assert digest()==before and all(b.rotation_mode=='QUATERNION' for b in obj.pose.bones)
    assert not any(a.name.startswith('__BCK_Auto__') for a in bpy.data.actions)
    start(1); stage=3
   elif stage==3:
    if state.running or state.pending: return .05
    assert all(b.rotation_mode=='XYZ' for b in bpy.data.objects['AutoGUI'].pose.bones),state.last_result
    assert all(not c.modifiers and not c.lock for a in bpy.data.actions if a.name.startswith('AutoGUIAction') for c in addon.core.action_curves(a))
    bpy.ops.ed.undo(); stage=4
   elif stage==4:
    assert bpy.data.objects['AutoGUI'].pose.bones[0].rotation_mode=='QUATERNION'
    assert digest()==before
    bpy.ops.ed.redo(); stage=5
   elif stage==5:
    assert bpy.data.objects['AutoGUI'].pose.bones[0].rotation_mode=='XYZ'
    (OUT/'automatic-gui-result.txt').write_text('AUTOMATIC_GUI_PASS inline_no_popup no_selection all_actions all_bones bake_cycles progress_escape complete undo redo',encoding='utf-8')
    bpy.ops.wm.quit_blender(); return None
  return .05 if stage in (1,2,3) else .5
 except Exception:
  (OUT/'automatic-gui-result.txt').write_text(traceback.format_exc(),encoding='utf-8')
  bpy.ops.wm.quit_blender(); return None
bpy.app.timers.register(test,first_interval=2)
