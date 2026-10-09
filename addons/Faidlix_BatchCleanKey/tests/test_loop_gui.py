import bpy,sys,os,importlib,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'addons'))
assert not bpy.app.background and not bpy.data.filepath
addon=importlib.import_module(os.environ.get('BCK_TEST_MODULE','Faidlix_BatchCleanKey'))
if not hasattr(bpy.types.WindowManager,'faidlix_batch_clean_key'): addon.register()
bpy.context.preferences.view.show_splash=False
bpy.context.preferences.filepaths.use_auto_save_temporary_files=False
arm=bpy.data.armatures.new('LoopGUI')
obj=bpy.data.objects.new('LoopGUI',arm)
bpy.context.collection.objects.link(obj)
for o in bpy.context.selected_objects: o.select_set(False)
obj.select_set(True); bpy.context.view_layer.objects.active=obj
bpy.ops.object.mode_set(mode='EDIT')
for i in range(5):
 b=arm.edit_bones.new('LoopBone'+str(i)); b.head,b.tail=(i,0,0),(i,0,1)
bpy.ops.object.mode_set(mode='POSE')
action=bpy.data.actions.new('LoopBlocked')
slot=action.slots.new('OBJECT',obj.name)
bag=action.layers.new('Layer').strips.new(type='KEYFRAME').channelbag(slot,ensure=True)
for bone in obj.pose.bones:
 c=bag.fcurves.new(bone.path_from_id()+'.location',index=0)
 for f,v in ((1,0),(500,2),(1000,3)):
  c.keyframe_points.insert(f,v)
 c.lock=True
 c.modifiers.new('NOISE')
obj.animation_data_create().action=action; obj.animation_data.action_slot=slot
def digest():
 return repr([(c.lock,c.mute,[m.type for m in c.modifiers],addon.core.snapshot(c)) for c in addon.core.action_curves(action)])
before=digest()
area=next(a for a in bpy.context.screen.areas if a.type=='VIEW_3D')
region=next(r for r in area.regions if r.type=='WINDOW')
OUT=ROOT/'validation'; OUT.mkdir(exist_ok=True)
stage=0; started=time.monotonic()
def test():
 global stage
 try:
  assert time.monotonic()-started<60
  with bpy.context.temp_override(area=area,region=region):
   state=bpy.context.window_manager.faidlix_batch_clean_key
   if stage==0:
    bpy.ops.ed.undo_push(message='Loop fixture')
    assert bpy.ops.faidlix_batch_clean_key.loop('INVOKE_DEFAULT',action_name=action.name,sample_step=.01)=={'RUNNING_MODAL'}
    stage=1
   elif stage==1:
    bpy.ops.screen.screenshot(filepath=str(OUT/'loop-bake-dialog.png'))
    bpy.context.window.event_simulate(type='RET',value='PRESS')
    bpy.context.window.event_simulate(type='RET',value='RELEASE')
    stage=2
   elif stage==2:
    if not state.running:
     assert time.monotonic()-started<10,repr((state.pending,state.loop_job,state.last_result))
     return .05
    assert state.loop_job
    if state.progress>.03:
     bpy.context.window.event_simulate(type='ESC',value='PRESS')
     bpy.context.window.event_simulate(type='ESC',value='RELEASE')
     stage=3
   elif stage==3:
    if state.running: return .05
    assert before==digest() and not bpy.data.actions.get('LoopBlocked_Loop')
    assert obj.animation_data.action==action and not state.loop_job
    bpy.ops.faidlix_batch_clean_key.loop('INVOKE_DEFAULT',action_name=action.name,sample_step=1)
    stage=4
   elif stage==4:
    bpy.context.window.event_simulate(type='RET',value='PRESS')
    bpy.context.window.event_simulate(type='RET',value='RELEASE')
    stage=5
   elif stage==5:
    if state.pending or state.running: return .05
    copy=bpy.data.actions.get('LoopBlocked_Loop')
    assert copy and obj.animation_data.action==copy,state.last_result
    assert before==digest()
    curves,start,end=addon.core.loop_curves(copy,obj)
    assert (start,end)==(1,1000) and all(abs(c.evaluate(start)-c.evaluate(end))<1e-6 for c in curves)
    bpy.ops.ed.undo(); stage=6
   elif stage==6:
    assert bpy.data.objects['LoopGUI'].animation_data.action.name=='LoopBlocked'
    assert not bpy.data.actions.get('LoopBlocked_Loop')
    bpy.ops.ed.redo(); stage=7
   elif stage==7:
    assert bpy.data.objects['LoopGUI'].animation_data.action.name=='LoopBlocked_Loop'
    (OUT/'loop-gui-result.txt').write_text('LOOP_GUI_PASS automatic_bake_popup progress escape source_preserved complete undo redo',encoding='utf-8')
    bpy.ops.wm.quit_blender(); return None
  return .05 if stage>=2 else .5
 except Exception:
  (OUT/'loop-gui-result.txt').write_text(traceback.format_exc(),encoding='utf-8')
  bpy.ops.wm.quit_blender(); return None
bpy.app.timers.register(test,first_interval=2)
