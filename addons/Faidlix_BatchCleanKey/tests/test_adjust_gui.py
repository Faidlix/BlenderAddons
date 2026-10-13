import bpy,runpy,time,traceback,importlib,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
f=runpy.run_path(str(Path(__file__).with_name('test_adjust.py')),run_name='__main__')
a=f['a']; obj=f['obj']; action=f['action']; bag=f['bag']
for c in bag.fcurves:
 for m in list(c.modifiers): c.modifiers.remove(m)
 for p in c.keyframe_points: p.select_control_point=p.co.x in {1,11}
bpy.context.scene.frame_set(1)
bpy.context.scene.tool_settings.use_keyframe_insert_auto=True
s=bpy.context.window_manager.faidlix_batch_clean_key; s.target_armature=obj; s.adjust_mode='PATH'
bpy.context.preferences.view.show_splash=False
area=next(x for x in bpy.context.screen.areas if x.type=='VIEW_3D'); region=next(x for x in area.regions if x.type=='WINDOW')
area.spaces.active.show_region_ui=True
before=repr([(c.data_path,c.array_index,a.core.snapshot(c)) for c in bag.fcurves])
started=time.monotonic(); stage=-1
OUT=ROOT/'validation'
def event(t):
 bpy.context.window.event_simulate(type=t,value='PRESS',unicode={'NINE':'9','ZERO':'0'}.get(t,''),x=region.x+region.width//2,y=region.y+region.height//2); bpy.context.window.event_simulate(type=t,value='RELEASE',x=region.x+region.width//2,y=region.y+region.height//2)
def tick():
 global stage
 try:
  assert time.monotonic()-started<55,repr((stage,s.last_result,s.running,s.adjust_enabled,[o.bl_idname for o in bpy.context.window.modal_operators]))
  with bpy.context.temp_override(area=area,region=region):
   with (OUT/'adjust-event-debug.txt').open('a',encoding='utf-8') as log:
    log.write(repr((stage,[o.bl_idname for o in bpy.context.window.modal_operators],[(o.bl_idname,o.as_pointer()) for o in bpy.context.window_manager.operators],bool(a.adjust_ui.WATCH.request) if a.adjust_ui.WATCH else None))+chr(10))
   if stage==-1:
    bpy.context.window.event_simulate(type='MOUSEMOVE',value='NOTHING',x=region.x+region.width//2,y=region.y+region.height//2); stage=0
   elif stage==0:
    bpy.ops.ed.undo_push(message='Together fixture')
    assert bpy.ops.faidlix_batch_clean_key.adjust_toggle()=={'RUNNING_MODAL'}
    stage=1
   elif stage==1: event('R'); stage=2
   elif stage==2: event('Z'); stage=3
   elif stage==3: event('NINE'); event('ZERO'); stage=4
   elif stage==4: event('RET'); stage=5
   elif stage==5:
    if s.running or not s.last_result.startswith('已一起調整'): return .1
    ob=bpy.data.objects['Adjust']; act=ob.animation_data.action; curves=list(a.core.action_curves(act))
    x=next(c for c in curves if c.data_path=='pose.bones["Root"].location' and c.array_index==0)
    assert abs(x.evaluate(11)+10)<1e-4,(x.evaluate(11),s.last_result)
    assert bpy.context.scene.tool_settings.use_keyframe_insert_auto
    bpy.ops.screen.screenshot(filepath=str(OUT/'adjust-mode-v150.png'))
    event('Z') if False else None
    bpy.ops.ed.undo(); stage=6
   elif stage==6:
    ob=bpy.data.objects['Adjust']; act=ob.animation_data.action; current=a.adjust.bag_for(act,ob)
    after=repr([(c.data_path,c.array_index,a.core.snapshot(c)) for c in current.fcurves])
    (OUT/'adjust-undo-before.txt').write_text(before,encoding='utf-8'); (OUT/'adjust-undo-after.txt').write_text(after,encoding='utf-8')
    assert after==before,'Undo must restore original keys'
    bpy.ops.ed.redo(); stage=7
   elif stage==7:
    ob=bpy.data.objects['Adjust']; current=a.adjust.bag_for(ob.animation_data.action,ob)
    assert abs(current.fcurves.find('pose.bones["Root"].location',index=0).evaluate(11)+10)<1e-4
    assert s.adjust_enabled
    s.adjust_mode='PATH'
    for b in ob.pose.bones: b.select=b.name=='Hand'
    for c in current.fcurves:
     for p in c.keyframe_points: p.select_control_point='Hand' in c.data_path and p.co.x==11
    bpy.context.scene.frame_set(11)
    s.last_result=''; stage=8
   elif stage==8: event('R'); stage=9
   elif stage==9: event('X'); stage=10
   elif stage==10:
    bpy.context.window.event_simulate(type='FOUR',value='PRESS',unicode='4',x=region.x+region.width//2,y=region.y+region.height//2)
    bpy.context.window.event_simulate(type='FIVE',value='PRESS',unicode='5',x=region.x+region.width//2,y=region.y+region.height//2); stage=11
   elif stage==11: event('RET'); stage=12
   elif stage==12:
    if s.running or not s.last_result.startswith('已一起調整'): return .1
    ob=bpy.data.objects['Adjust']; current=a.adjust.bag_for(ob.animation_data.action,ob)
    assert bpy.context.scene.frame_current==11 and s.adjust_mode=='PATH'
    hand_x=current.fcurves.find('pose.bones["Hand"].rotation_euler',index=0)
    assert hand_x and {p.co.x for p in hand_x.keyframe_points}=={11}
    assert abs(current.fcurves.find('pose.bones["Root"].location',index=0).evaluate(11)+10)<1e-4
    s.last_result=''; event('R'); stage=13
   elif stage==13: event('ESC'); stage=14
   elif stage==14:
    assert not s.running and not s.last_result.startswith('已一起調整')
    s.adjust_enabled=False; s.adjust_toolbar_visible=False; stage=15
   elif stage==15:
    assert a.adjust_ui.WATCH is None
    (OUT/'adjust-gui-result.txt').write_text('ADJUST_GUI_PASS native_R_Z_90 persistent immediate_commit same_frame_keys Undo Redo reselect_Hand_frame11 native_Esc auto_key_restored',encoding='utf-8')
    bpy.ops.wm.quit_blender(); return None
  return .4
 except Exception:
  (OUT/'adjust-gui-result.txt').write_text(traceback.format_exc(),encoding='utf-8')
  bpy.ops.wm.quit_blender(); return None
bpy.app.timers.register(tick,first_interval=2)
