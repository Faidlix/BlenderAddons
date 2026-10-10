import bpy,runpy,importlib,os,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
runpy.run_path(str(Path(__file__).with_name('test_mirror.py')),run_name='__main__')
addon=importlib.import_module(os.environ.get('BCK_TEST_MODULE','Faidlix_BatchCleanKey'))
bpy.context.preferences.view.show_splash=False
obj=bpy.context.object; source=bpy.data.actions['RestAwareMirror']
other=bpy.data.objects.new('SecondaryRig',obj.data.copy()); bpy.context.collection.objects.link(other)
bpy.context.view_layer.update()
a=bpy.data.actions.new('SecondaryAction'); a.slots.new('OBJECT',other.name)
addon.core.assign_action(bpy.context,other,a); addon.core.assign_action(bpy.context,obj,source)
state=bpy.context.window_manager.faidlix_batch_clean_key; state.target_armature=obj; addon.ui.refresh(bpy.context)
area=next(a for a in bpy.context.screen.areas if a.type=='VIEW_3D'); area.spaces.active.show_region_ui=True
region=next(r for r in area.regions if r.type=='WINDOW'); sidebar=next(r for r in area.regions if r.type=='UI')
area.tag_redraw()
OUT=ROOT/'validation'; stage=-1; count=len(bpy.data.actions); start=time.monotonic()
def event(kind):
 bpy.context.window.event_simulate(type=kind,value='PRESS'); bpy.context.window.event_simulate(type=kind,value='RELEASE')
def tick():
 global stage
 try:
  assert time.monotonic()-start<45
  with bpy.context.temp_override(area=area,region=region):
   state=bpy.context.window_manager.faidlix_batch_clean_key
   if stage==-1:
    with bpy.context.temp_override(area=area,region=sidebar): sidebar.active_panel_category='Faidlix'
    area.tag_redraw(); stage=0
   elif stage==0:
    assert a not in [i.action for i in state.browser]
    bpy.ops.screen.screenshot(filepath=str(OUT/'v140-rig-browser.png'))
    bpy.ops.faidlix_batch_clean_key.duplicate('INVOKE_DEFAULT',action_name=source.name); stage=1
   elif stage==1:
    bpy.ops.screen.screenshot(filepath=str(OUT/'v140-copy-dialog.png')); event('ESC'); stage=2
   elif stage==2:
    assert len(bpy.data.actions)==count
    state.target_armature=other; addon.ui.refresh(bpy.context); stage=3
   elif stage==3:
    assert len(state.browser)==1 and state.browser[0].action==a
    bpy.ops.screen.screenshot(filepath=str(OUT/'v140-secondary-browser.png'))
    bpy.ops.faidlix_batch_clean_key.duplicate('INVOKE_DEFAULT',action_name=a.name); stage=4
   elif stage==4: event('RET'); stage=5
   elif stage==5:
    addon.ui.refresh(bpy.context)
    assert len(state.browser)==2 and other.animation_data.action.name=='SecondaryAction_Copy'
    assert obj.animation_data.action==source
    (OUT/'rig-browser-gui-result.txt').write_text('RIG_BROWSER_GUI_PASS two_rigs filtered_count copy_dialog cancel confirm',encoding='utf-8')
    bpy.ops.wm.quit_blender(); return None
  return .5
 except Exception:
  (OUT/'rig-browser-gui-result.txt').write_text(traceback.format_exc(),encoding='utf-8'); bpy.ops.wm.quit_blender(); return None
bpy.app.timers.register(tick,first_interval=2)
