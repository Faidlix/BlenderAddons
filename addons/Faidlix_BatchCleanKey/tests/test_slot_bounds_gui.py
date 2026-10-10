import bpy,os,importlib,runpy,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
fixture=runpy.run_path(str(Path(__file__).with_name('test_reverse_rigs.py')),run_name='__main__')
addon=fixture['addon']; obj=fixture['a']; action=fixture['action']; bag=fixture['ba']; foreign=fixture['bb'].fcurves[0]
before=addon.core.snapshot(foreign)
for c in bag.fcurves:
 c.keyframe_points.clear(); c.keyframe_points.insert(0,0)
bag.fcurves[0].keyframe_points.insert(1,1)
state=bpy.context.window_manager.faidlix_batch_clean_key; state.target_armature=obj
addon.core.assign_action(bpy.context,obj,action)
bpy.context.scene.frame_start=0; bpy.context.scene.frame_end=30
bpy.context.preferences.view.show_splash=False
area=next(a for a in bpy.context.screen.areas if a.type=='VIEW_3D'); area.spaces.active.show_region_ui=True
region=next(r for r in area.regions if r.type=='WINDOW'); sidebar=next(r for r in area.regions if r.type=='UI')
stage=0; started=time.monotonic()
def tick():
 global stage
 try:
  assert time.monotonic()-started<40
  with bpy.context.temp_override(area=area,region=region):
   if stage==0:
    with bpy.context.temp_override(area=area,region=sidebar): sidebar.active_panel_category='Faidlix'
    bpy.ops.ed.undo_push(message='Two slot 0-1 versus 0-30 fixture')
    assert bpy.ops.faidlix_batch_clean_key.switch(action_name=action.name)=={'FINISHED'}
    # Timer-driven direct execution needs an explicit native undo checkpoint.
    bpy.ops.ed.undo_push(message='Switched Action slot bounds')
    stage=1
   elif stage==1:
    assert (bpy.context.scene.frame_start,bpy.context.scene.frame_end)==(0,1)
    assert all({p.co.x for p in c.keyframe_points}=={0,1} for c in bag.fcurves)
    assert addon.core.snapshot(foreign)==before
    bpy.ops.screen.screenshot(filepath=str(ROOT/'validation/v142-slot-bounds.png'))
    bpy.ops.ed.undo(); stage=2
   elif stage==2:
    assert bpy.context.scene.frame_end==30
    bpy.ops.ed.redo(); stage=3
   elif stage==3:
    assert bpy.context.scene.frame_end==1
    current=bpy.data.actions['ReverseShared']; rig=bpy.data.objects['ReverseRigA']
    assert addon.core.actual_range(current,rig)==(0,1)
    assert addon.core.actual_range(current)==(0,30)
    (ROOT/'validation/slot-bounds-gui-result.txt').write_text('SLOT_BOUNDS_GUI_PASS 0_1_pad foreign_0_30_unchanged Undo Redo',encoding='utf-8')
    bpy.ops.wm.quit_blender(); return None
  return .5
 except Exception:
  (ROOT/'validation/slot-bounds-gui-result.txt').write_text(traceback.format_exc(),encoding='utf-8')
  bpy.ops.wm.quit_blender(); return None
bpy.app.timers.register(tick,first_interval=2)
