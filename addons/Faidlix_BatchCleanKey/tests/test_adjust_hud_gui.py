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
def hover(name):
 x,y,r,t=a.adjust_ui.adjust_hud.bounds(region,s)[name]
 bpy.context.window.event_simulate(type='MOUSEMOVE',value='NOTHING',x=region.x+int((x+r)/2),y=region.y+int((y+t)/2))

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
    rects=a.adjust_ui.adjust_hud.bounds(region,s)
    assert 'LOCAL' not in rects and rects['toggle'][1]==rects['close'][1]
    assert rects['PATH'][3]<rects['toggle'][1]
    assert rects['PATH'][0]==rects['toggle'][0] and rects['KEEP_PATH'][2]==rects['toggle'][2]
    bpy.ops.screen.screenshot(filepath=str(OUT/'adjust-hud-v160.png')); click('toggle'); stage=2
   elif stage==2:
    assert s.adjust_toolbar_visible and not s.adjust_enabled and a.adjust_ui.WATCH
    assert set(a.adjust_ui.adjust_hud.bounds(region,s))=={'toggle','close'}
    bpy.ops.screen.screenshot(filepath=str(OUT/'adjust-hud-paused-v160.png'))
    bpy.context.scene.tool_settings.use_keyframe_insert_auto=False
    event('G'); stage=3
   elif stage==3: event('X'); stage=4
   elif stage==4: event('THREE'); stage=5
   elif stage==5: event('RET'); stage=6
   elif stage==6:
    assert digest()==before,'paused mode must not edit animation keys'
    click('toggle'); stage=7
   elif stage==7:
    assert s.adjust_enabled
    click('KEEP_PATH'); stage=8
   elif stage==8:
    assert s.adjust_mode=='KEEP_PATH' and 'settings' in a.adjust_ui.adjust_hud.bounds(region,s)
    rects=a.adjust_ui.adjust_hud.bounds(region,s)
    assert rects['settings'][0]==rects['toggle'][0] and rects['settings'][2]==rects['toggle'][2]
    assert rects['settings'][3]<rects['PATH'][1]
    s.adjust_root='Root'; click('settings'); stage=9
   elif stage==9:
    assert s.adjust_enabled and s.adjust_toolbar_visible
    for ch in 'Hand':
     kind={'H':'H','a':'A','n':'N','d':'D'}[ch]
     bpy.context.window.event_simulate(type=kind,value='PRESS',unicode=ch,x=region.x+region.width//2,y=region.y+region.height//2)
     bpy.context.window.event_simulate(type=kind,value='RELEASE',x=region.x+region.width//2,y=region.y+region.height//2)
    stage=91
   elif stage==91: event('RET'); stage=92
   elif stage==92:
    assert s.adjust_root=='Hand',s.adjust_root
    bpy.ops.screen.screenshot(filepath=str(OUT/'adjust-hud-root-v160.png')); hover('PATH'); stage=93
   elif stage==93: stage=94; return .8
   elif stage==94:
    assert a.adjust_ui.adjust_hud.tooltip(a.adjust_ui.WATCH,a.adjust_ui.adjust_hud.bounds(region,s))==a.adjust_ui.adjust_hud.TIPS['PATH'],repr((getattr(a.adjust_ui.WATCH,'hover_name',None),time.monotonic()-getattr(a.adjust_ui.WATCH,'hover_since',0)))
    bpy.ops.screen.screenshot(filepath=str(OUT/'adjust-hud-tip-path-v160.png')); hover('KEEP_PATH'); stage=95
   elif stage==95: stage=96; return .8
   elif stage==96:
    assert a.adjust_ui.WATCH.hover_name=='KEEP_PATH'
    bpy.ops.screen.screenshot(filepath=str(OUT/'adjust-hud-tip-keep-v160.png')); hover('settings'); stage=97
   elif stage==97: stage=98; return .8
   elif stage==98:
    assert a.adjust_ui.adjust_hud.tooltip(a.adjust_ui.WATCH,a.adjust_ui.adjust_hud.bounds(region,s))==a.adjust_ui.adjust_hud.TIPS['settings']
    bpy.ops.screen.screenshot(filepath=str(OUT/'adjust-hud-tip-root-v160.png')); click('close'); stage=10
   elif stage==10:
    assert not s.adjust_enabled and not s.adjust_toolbar_visible and a.adjust_ui.WATCH is None
    assert digest()==before
    (OUT/'adjust-hud-gui-result.txt').write_text('ADJUST_HUD_GUI_PASS physical_toggle pause_normal_G no_key_changes three_rows color_toggle no_LOCAL paused_compact direct_root_search_immediate hover_tips close_label',encoding='utf-8')
    bpy.ops.wm.quit_blender(); return None
  return .4
 except Exception:
  (OUT/'adjust-hud-gui-result.txt').write_text(traceback.format_exc(),encoding='utf-8'); bpy.ops.wm.quit_blender(); return None
bpy.app.timers.register(tick,first_interval=2)
