import bpy,runpy,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
f=runpy.run_path(str(Path(__file__).with_name('test_adjust.py')),run_name='__main__')
a=f['a']; obj=f['obj']; bag=f['bag']
for c in bag.fcurves:
 for m in list(c.modifiers): c.modifiers.remove(m)
 for p in c.keyframe_points: p.select_control_point=p.co.x in {1,11}
bpy.context.scene.frame_set(1); bpy.context.preferences.view.show_splash=False
s=bpy.context.window_manager.faidlix_batch_clean_key; s.target_armature=obj
area=next(x for x in bpy.context.screen.areas if x.type=='VIEW_3D'); region=next(x for x in area.regions if x.type=='WINDOW')
started=time.monotonic(); stage=-1; OUT=ROOT/'validation'
def click(name):
 x,y,r,t=a.adjust_ui.adjust_hud.bounds(region,s)[name]
 for value in ('PRESS','RELEASE'):
  bpy.context.window.event_simulate(type='LEFTMOUSE',value=value,x=region.x+int((x+r)/2),y=region.y+int((y+t)/2))
def event(kind):
 bpy.context.window.event_simulate(type=kind,value='PRESS',unicode={'THREE':'3'}.get(kind,''),x=region.x+region.width//2,y=region.y+region.height//2)
 bpy.context.window.event_simulate(type=kind,value='RELEASE',x=region.x+region.width//2,y=region.y+region.height//2)
def digest():
 ob=bpy.data.objects['Adjust']; return repr([(c.data_path,c.array_index,a.core.snapshot(c)) for c in a.adjust.bag_for(ob.animation_data.action,ob).fcurves])
before=digest()
def tick():
 global stage
 try:
  assert time.monotonic()-started<40,repr((stage,s.adjust_enabled,s.adjust_toolbar_visible))
  with bpy.context.temp_override(area=area,region=region):
   if stage==-1:
    bpy.context.window.event_simulate(type='MOUSEMOVE',value='NOTHING',x=region.x+region.width//2,y=region.y+region.height//2); stage=0
   elif stage==0:
    bpy.ops.ed.undo_push(message='HUD fixture'); bpy.ops.faidlix_batch_clean_key.adjust_toggle(); stage=1
   elif stage==1:
    assert s.adjust_toolbar_visible and s.adjust_enabled
    bpy.ops.screen.screenshot(filepath=str(OUT/'adjust-hud-v151.png')); click('toggle'); stage=2
   elif stage==2:
    assert s.adjust_toolbar_visible and not s.adjust_enabled and a.adjust_ui.WATCH
    bpy.context.scene.tool_settings.use_keyframe_insert_auto=False
    event('G'); stage=3
   elif stage==3: event('X'); stage=4
   elif stage==4: event('THREE'); stage=5
   elif stage==5: event('RET'); stage=6
   elif stage==6:
    assert digest()==before,'paused mode must not edit animation keys'
    click('PATH'); stage=7
   elif stage==7:
    assert s.adjust_mode=='PATH'; click('KEEP_PATH'); stage=8
   elif stage==8:
    assert s.adjust_mode=='KEEP_PATH' and 'settings' in a.adjust_ui.adjust_hud.bounds(region,s)
    bpy.ops.screen.screenshot(filepath=str(OUT/'adjust-hud-paused-v151.png')); click('toggle'); stage=9
   elif stage==9:
    assert s.adjust_enabled and s.adjust_toolbar_visible
    click('close'); stage=10
   elif stage==10:
    assert not s.adjust_enabled and not s.adjust_toolbar_visible and a.adjust_ui.WATCH is None
    assert digest()==before
    (OUT/'adjust-hud-gui-result.txt').write_text('ADJUST_HUD_GUI_PASS physical_toggle pause_normal_G no_key_changes inline_modes close_X',encoding='utf-8')
    bpy.ops.wm.quit_blender(); return None
  return .4
 except Exception:
  (OUT/'adjust-hud-gui-result.txt').write_text(traceback.format_exc(),encoding='utf-8'); bpy.ops.wm.quit_blender(); return None
bpy.app.timers.register(tick,first_interval=2)
