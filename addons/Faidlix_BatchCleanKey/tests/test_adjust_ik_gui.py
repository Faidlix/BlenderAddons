import bpy,runpy,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
f=runpy.run_path(str(Path(__file__).with_name('test_adjust.py')),run_name='__main__')
a=f['a']; obj=f['obj']; action=f['action']; bag=f['bag']
ik=obj.pose.bones['Hand'].constraints.new('IK'); ik.target=obj; ik.subtarget='IKControl'; ik.pole_target=obj; ik.pole_subtarget='PoleControl'; ik.chain_count=2
for c in bag.fcurves:
 for m in list(c.modifiers): c.modifiers.remove(m)
 for p in c.keyframe_points: p.select_control_point=p.co.x in {1,11}
bpy.context.scene.frame_set(1); bpy.context.preferences.view.show_splash=False
s=bpy.context.window_manager.faidlix_batch_clean_key; s.target_armature=obj; s.adjust_mode='PATH'
area=next(x for x in bpy.context.screen.areas if x.type=='VIEW_3D'); region=next(x for x in area.regions if x.type=='WINDOW')
started=time.monotonic(); stage=-1; OUT=ROOT/'validation'
def event(t):
 for v in ('PRESS','RELEASE'):
  bpy.context.window.event_simulate(type=t,value=v,**({'unicode':{'NINE':'9','ZERO':'0'}.get(t,'')} if v=='PRESS' else {}),x=region.x+region.width//2,y=region.y+region.height//2)
def tick():
 global stage
 try:
  assert time.monotonic()-started<40,repr((stage,s.last_result))
  with bpy.context.temp_override(area=area,region=region):
   if stage==-1:
    bpy.context.window.event_simulate(type='MOUSEMOVE',value='NOTHING',x=region.x+region.width//2,y=region.y+region.height//2); stage=0
   elif stage==0:
    bpy.ops.ed.undo_push(message='IK fixture'); bpy.ops.faidlix_batch_clean_key.adjust_toggle(); stage=1
   elif stage==1: event('R'); stage=2
   elif stage==2:
    bpy.ops.screen.screenshot(filepath=str(OUT/'adjust-ik-v150.png')); event('RET'); stage=3
   elif stage==3:
    assert a.adjust_ui.IK_POLICY and set(a.adjust_ui.IK_POLICY.values())=={'AUTO'}
    event('R'); stage=4
   elif stage==4: event('Z'); stage=5
   elif stage==5: event('NINE'); event('ZERO'); stage=6
   elif stage==6: event('RET'); stage=7
   elif stage==7:
    if s.running or not s.last_result.startswith('已一起調整'): return .1
    ob=bpy.data.objects['Adjust']; current=a.adjust.bag_for(ob.animation_data.action,ob)
    for name in ('IKControl','PoleControl'):
     curves=[c for c in current.fcurves if name in c.data_path]
     assert curves and all({p.co.x for p in c.keyframe_points}<={1,11} for c in curves),name
     assert ob.pose.bones[name].select
    s.adjust_enabled=False; s.adjust_toolbar_visible=False; stage=8
   elif stage==8:
    assert a.adjust_ui.WATCH is None
    (OUT/'adjust-ik-gui-result.txt').write_text('ADJUST_IK_GUI_PASS native_prompt auto_join control_pole same_frame_keys',encoding='utf-8')
    bpy.ops.wm.quit_blender(); return None
  return .4
 except Exception:
  (OUT/'adjust-ik-gui-result.txt').write_text(traceback.format_exc(),encoding='utf-8'); bpy.ops.wm.quit_blender(); return None
bpy.app.timers.register(tick,first_interval=2)
