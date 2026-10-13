import bpy,runpy,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
f=runpy.run_path(str(Path(__file__).with_name('test_adjust.py')),run_name='__main__')
a=f['a']; obj=f['obj']; bag=f['bag']
for c in bag.fcurves:
 for m in list(c.modifiers): c.modifiers.remove(m)
 for p in c.keyframe_points: p.select_control_point=p.co.x in {1,11}
bpy.context.scene.frame_set(1); bpy.context.preferences.view.show_splash=False
s=bpy.context.window_manager.faidlix_batch_clean_key; s.target_armature=obj; s.adjust_mode='PATH'
area=next(x for x in bpy.context.screen.areas if x.type=='VIEW_3D'); region=next(x for x in area.regions if x.type=='WINDOW')
started=time.monotonic(); stage=-1; OUT=ROOT/'validation'
def event(t):
 bpy.context.window.event_simulate(type=t,value='PRESS',unicode={'THREE':'3','TWO':'2'}.get(t,''),x=region.x+region.width//2,y=region.y+region.height//2)
 bpy.context.window.event_simulate(type=t,value='RELEASE',x=region.x+region.width//2,y=region.y+region.height//2)
def current():
 ob=bpy.data.objects['Adjust']; return a.adjust.bag_for(ob.animation_data.action,ob)
def tick():
 global stage
 try:
  assert time.monotonic()-started<45,repr((stage,s.last_result))
  with bpy.context.temp_override(area=area,region=region):
   if stage==-1:
    bpy.context.window.event_simulate(type='MOUSEMOVE',value='NOTHING',x=region.x+region.width//2,y=region.y+region.height//2); stage=0
   elif stage==0:
    bpy.ops.ed.undo_push(message='G S fixture'); bpy.ops.faidlix_batch_clean_key.adjust_toggle(); stage=1
   elif stage==1: event('G'); stage=2
   elif stage==2: event('X'); stage=3
   elif stage==3: event('THREE'); stage=4
   elif stage==4: event('RET'); stage=5
   elif stage==5:
    if s.running or not s.last_result.startswith('已一起調整'): return .1
    bg=current(); assert abs(bg.fcurves.find('pose.bones["Root"].location',index=0).evaluate(11)-3)<1e-4
    assert s.adjust_enabled; s.last_result=''; event('S'); stage=6
   elif stage==6: event('TWO'); stage=7
   elif stage==7: event('RET'); stage=8
   elif stage==8:
    if s.running or not s.last_result.startswith('已一起調整'): return .1
    bg=current()
    assert abs(bg.fcurves.find('pose.bones["Root"].location',index=0).evaluate(11)-6)<1e-4
    assert abs(bg.fcurves.find('pose.bones["Root"].location',index=1).evaluate(11)-20)<1e-4
    assert next(p.co.y for p in bg.fcurves.find('pose.bones["Root"].location',index=0).keyframe_points if p.co.x==6)==5
    s.adjust_enabled=False; stage=9
   elif stage==9:
    assert a.adjust_ui.WATCH is None
    (OUT/'adjust-move-scale-gui-result.txt').write_text('ADJUST_MOVE_SCALE_GUI_PASS native_G_X_3 S_2 persistent selected_frames parent_once unselected_key',encoding='utf-8')
    bpy.ops.wm.quit_blender(); return None
  return .4
 except Exception:
  (OUT/'adjust-move-scale-gui-result.txt').write_text(traceback.format_exc(),encoding='utf-8'); bpy.ops.wm.quit_blender(); return None
bpy.app.timers.register(tick,first_interval=2)
