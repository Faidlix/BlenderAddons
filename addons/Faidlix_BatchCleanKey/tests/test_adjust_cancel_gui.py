import bpy,runpy,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
f=runpy.run_path(str(Path(__file__).with_name('test_adjust.py')),run_name='__main__')
a=f['a']; obj=f['obj']; bag=f['bag']
for c in bag.fcurves:
 for m in list(c.modifiers): c.modifiers.remove(m)
curve=bag.fcurves.find('pose.bones["Root"].location',index=0)
curve.keyframe_points.clear(); curve.keyframe_points.add(4000)
for i,p in enumerate(curve.keyframe_points): p.co=(i+1,i); p.select_control_point=True
curve.update(); bpy.context.scene.frame_set(1)
def digest():
 ob=bpy.data.objects['Adjust']; current=a.adjust.bag_for(ob.animation_data.action,ob)
 return repr([(c.data_path,c.array_index,a.core.snapshot(c)) for c in current.fcurves])
before=digest(); bpy.context.preferences.view.show_splash=False
s=bpy.context.window_manager.faidlix_batch_clean_key; s.target_armature=obj; s.adjust_mode='PATH'
area=next(x for x in bpy.context.screen.areas if x.type=='VIEW_3D'); region=next(x for x in area.regions if x.type=='WINDOW')
started=time.monotonic(); stage=-1; OUT=ROOT/'validation'
def event(t):
 bpy.context.window.event_simulate(type=t,value='PRESS',unicode={'THREE':'3'}.get(t,''),x=region.x+region.width//2,y=region.y+region.height//2)
 bpy.context.window.event_simulate(type=t,value='RELEASE',x=region.x+region.width//2,y=region.y+region.height//2)
def tick():
 global stage
 try:
  assert time.monotonic()-started<45,repr((stage,s.last_result))
  with bpy.context.temp_override(area=area,region=region):
   if stage==-1:
    bpy.context.window.event_simulate(type='MOUSEMOVE',value='NOTHING',x=region.x+region.width//2,y=region.y+region.height//2); stage=0
   elif stage==0:
    bpy.ops.ed.undo_push(message='Progress cancel fixture'); bpy.ops.faidlix_batch_clean_key.adjust_toggle(); stage=1
   elif stage==1: event('G'); stage=2
   elif stage==2: event('X'); stage=3
   elif stage==3: event('THREE'); stage=4
   elif stage==4: event('RET'); stage=5
   elif stage==5:
    if s.running and s.progress>.01:
     bpy.ops.screen.screenshot(filepath=str(OUT/'adjust-progress-v150.png')); event('ESC'); stage=6
    return .02
   elif stage==6:
    if s.running: return .02
    assert s.last_result.startswith('已取消'),s.last_result
    assert digest()==before
    assert s.adjust_enabled
    s.adjust_enabled=False; stage=7
   elif stage==7:
    assert a.adjust_ui.WATCH is None
    (OUT/'adjust-cancel-gui-result.txt').write_text('ADJUST_CANCEL_GUI_PASS native_G progress Esc all_source_keys_preserved mode_continues',encoding='utf-8')
    bpy.ops.wm.quit_blender(); return None
  return .4
 except Exception:
  (OUT/'adjust-cancel-gui-result.txt').write_text(traceback.format_exc(),encoding='utf-8'); bpy.ops.wm.quit_blender(); return None
bpy.app.timers.register(tick,first_interval=2)
