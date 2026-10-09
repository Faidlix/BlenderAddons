import bpy,runpy,time,traceback,os,importlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
assert not bpy.app.background and not bpy.data.filepath
runpy.run_path(str(Path(__file__).with_name('test_mirror.py')),run_name='__main__')
addon=importlib.import_module(os.environ.get('BCK_TEST_MODULE','Faidlix_BatchCleanKey'))
bpy.context.preferences.view.show_splash=False
bpy.context.preferences.filepaths.use_auto_save_temporary_files=False
obj=bpy.context.object; source=bpy.data.actions['RestAwareMirror']
addon.core.assign_action(bpy.context,obj,source)
c=next(c for c in addon.core.action_curves(source) if c.data_path.endswith('.location'))
c.keyframe_points.insert(500,c.evaluate(5))
def digest():
 a=bpy.data.actions['RestAwareMirror']
 return repr([(c.data_path,c.array_index,[m.type for m in c.modifiers],addon.core.snapshot(c)) for c in addon.core.action_curves(a)])
before=digest(); count=len(bpy.data.actions)
area=next(a for a in bpy.context.screen.areas if a.type=='VIEW_3D')
region=next(r for r in area.regions if r.type=='WINDOW')
area.spaces.active.show_region_ui=True
region_ui=next(r for r in area.regions if r.type=='UI')
OUT=ROOT/'validation'; stage=0; started=time.monotonic()
keyed_only=os.environ.get('BCK_TEST_KEYED_MODE')=='1'
def event(kind):
 bpy.context.window.event_simulate(type=kind,value='PRESS')
 bpy.context.window.event_simulate(type=kind,value='RELEASE')
def test():
 global stage
 try:
  assert time.monotonic()-started<90
  with bpy.context.temp_override(area=area,region=region):
   state=bpy.context.window_manager.faidlix_batch_clean_key
   if stage==0:
    bpy.ops.ed.undo_push(message='Mirror fixture')
    bpy.ops.screen.screenshot(filepath=str(OUT/'v131-sidebar.png'))
    bpy.ops.faidlix_batch_clean_key.flip('INVOKE_DEFAULT',action_name='RestAwareMirror',sample_step=1,keyed_only=keyed_only)
    stage=1
   elif stage==1:
    bpy.ops.screen.screenshot(filepath=str(OUT/'mirror-keyed-dialog.png'))
    event('RET'); stage=2
   elif stage==2:
    if not state.running: return .02
    event('ESC'); stage=3
   elif stage==3:
    if state.running or state.pending: return .02
    assert digest()==before and len(bpy.data.actions)==count,state.last_result
    bpy.ops.faidlix_batch_clean_key.flip('INVOKE_DEFAULT',action_name='RestAwareMirror',sample_step=1,keyed_only=keyed_only)
    stage=4
   elif stage==4: event('RET'); stage=5
   elif stage==5:
    if state.running or state.pending: return .02
    assert len(bpy.data.actions)==count+1 and digest()==before,state.last_result
    assert bpy.context.object.animation_data.action.name.startswith('RestAwareMirror_Flipped')
    bpy.ops.ed.undo(); stage=6
   elif stage==6:
    assert len(bpy.data.actions)==count and digest()==before
    bpy.ops.ed.redo(); stage=7
   elif stage==7:
    assert len(bpy.data.actions)==count+1 and digest()==before
    (OUT/'mirror-gui-result.txt').write_text('MIRROR_GUI_PASS native_dialog modal_progress Escape source_preserved Undo Redo',encoding='utf-8')
    bpy.ops.wm.quit_blender(); return None
  return .02 if stage in (2,3,5) else .5
 except Exception:
  (OUT/'mirror-gui-result.txt').write_text(traceback.format_exc(),encoding='utf-8')
  bpy.ops.wm.quit_blender(); return None
bpy.app.timers.register(test,first_interval=2)
