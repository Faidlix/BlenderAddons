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
 if t=='R':bpy.context.window.event_simulate(type='MOUSEMOVE',value='NOTHING',x=region.x+region.width//2,y=region.y+region.height//2)
 for v in ('PRESS','RELEASE'):
  bpy.context.window.event_simulate(type=t,value=v,**({'unicode':{'NINE':'9','ZERO':'0'}.get(t,'')} if v=='PRESS' else {}),x=region.x+region.width//2,y=region.y+region.height//2)
def choose(value,phase='BOTH'):
 owner=a.adjust_ui.IK_CHOICE
 assert owner is not None,'IK dialog must remain open until explicit choice'
 left,bottom,right,top=a.adjust_hud.ik_bounds(region,owner)[value]
 window=bpy.context.window; x=region.x+int((left+right)/2); y=region.y+int((bottom+top)/2)
 if phase not in {'CLICK','RELEASE'}:window.event_simulate(type='MOUSEMOVE',value='NOTHING',x=x,y=y)
 if phase=='MOVE':return
 for v in (('RELEASE',) if phase=='RELEASE' else ('PRESS','RELEASE')):window.event_simulate(type='LEFTMOUSE',value=v,x=x,y=y)

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
    assert not a.adjust_ui.IK_POLICY and a.adjust_ui.IK_CHOICE
    # The opening key release, mouse departure and Enter must never choose/dismiss.
    bpy.context.window.event_simulate(type='MOUSEMOVE',value='NOTHING',x=100,y=200)
    event('RET'); stage=201
   elif stage==201:
    assert not a.adjust_ui.IK_POLICY and a.adjust_ui.IK_CHOICE
    stage=202;return 1.0
   elif stage==202:
    assert not a.adjust_ui.IK_POLICY and a.adjust_ui.IK_CHOICE
    bpy.ops.screen.screenshot(filepath=str(OUT/'adjust-ik-v162.png')); choose('AUTO'); stage=3
   elif stage==3:
    assert a.adjust_ui.IK_CHOICE is None and a.adjust_ui.IK_POLICY and set(a.adjust_ui.IK_POLICY.values())=={'AUTO'}
    event('R'); stage=4
   elif stage==4: event('Z'); stage=5
   elif stage==5: event('NINE'); event('ZERO'); stage=6
   elif stage==6: event('RET'); stage=7
   elif stage==7:
    if s.running or not s.last_result.startswith('已多影格同步調整'): return .1
    ob=bpy.data.objects['Adjust']; current=a.adjust.bag_for(ob.animation_data.action,ob)
    for name in ('IKControl','PoleControl'):
     curves=[c for c in current.fcurves if name in c.data_path]
     assert curves and all({p.co.x for p in c.keyframe_points}<={1,11} for c in curves),name
     assert ob.pose.bones[name].select
    a.adjust_ui.IK_POLICY.clear()
    for bone in ob.pose.bones: bone.select=bone.name in {'Root','Hand'}
    event('R');stage=71
   elif stage==71:
    assert not a.adjust_ui.IK_POLICY
    bpy.ops.screen.screenshot(filepath=str(OUT/'adjust-ik-selected-v162.png'));choose('SELECTED','MOVE');stage=711
   elif stage==711:
    choose('SELECTED','CLICK');stage=72
   elif stage==72:
    bpy.ops.screen.screenshot(filepath=str(OUT/'adjust-ik-after-click-v162.png'))
    assert a.adjust_ui.IK_CHOICE is None and set(a.adjust_ui.IK_POLICY.values())=={'SELECTED'}
    event('R');stage=73
   elif stage==73:
    assert any(op.bl_idname=='TRANSFORM_OT_rotate' for op in bpy.context.window.modal_operators),'selection popup must close after click'
    event('ESC');stage=74
   elif stage==74:
    a.adjust_ui.IK_POLICY.clear();event('R');stage=75
   elif stage==75:
    assert not a.adjust_ui.IK_POLICY;event('ESC');stage=76
   elif stage==76:
    assert not a.adjust_ui.IK_POLICY
    assert bpy.ops.faidlix_batch_clean_key.adjust_ik(signature='unset')=={'CANCELLED'}
    assert 'unset' not in a.adjust_ui.IK_POLICY
    # Mouse-driven opening: holding then releasing over AUTO must not choose it.
    bpy.context.window.event_simulate(type='MOUSEMOVE',value='NOTHING',x=region.x+region.width//2,y=region.y+region.height//2)
    bpy.context.window.event_simulate(type='LEFTMOUSE',value='PRESS',x=region.x+region.width//2,y=region.y+region.height//2);stage=77
   elif stage==77:
    assert a.adjust_ui.IK_CHOICE and a.adjust_ui.IK_CHOICE.wait_release
    choose('AUTO','MOVE');stage=78
   elif stage==78:
    choose('AUTO','RELEASE');stage=79
   elif stage==79:
    assert a.adjust_ui.IK_CHOICE and not a.adjust_ui.IK_POLICY
    choose('AUTO');stage=80
   elif stage==80:
    assert a.adjust_ui.IK_CHOICE is None and set(a.adjust_ui.IK_POLICY.values())=={'AUTO'}
    s.adjust_enabled=False; s.adjust_toolbar_visible=False;stage=8
   elif stage==8:
    assert a.adjust_ui.WATCH is None
    (OUT/'adjust-ik-gui-result.txt').write_text('ADJUST_IK_GUI_PASS stable_mouse_departure Enter_ignored keyboard_and_held_mouse_opener_release_ignored explicit_AUTO SELECTED no_default cancel_no_choice dialog_closed control_pole same_frame_keys',encoding='utf-8')
    bpy.ops.wm.quit_blender(); return None
  return .4
 except Exception:
  (OUT/'adjust-ik-gui-result.txt').write_text(traceback.format_exc(),encoding='utf-8'); bpy.ops.wm.quit_blender(); return None
bpy.app.timers.register(tick,first_interval=2)
