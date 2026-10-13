import bpy,runpy,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];OUT=ROOT/'validation'
f=runpy.run_path(str(Path(__file__).with_name('test_adjust.py')),run_name='__main__')
a,obj,action,bag=f['a'],f['obj'],f['action'],f['bag']
for c in bag.fcurves:
 for m in list(c.modifiers):c.modifiers.remove(m)
 for p in c.keyframe_points:p.select_control_point=p.co.x in {1,11}
s=bpy.context.window_manager.faidlix_batch_clean_key;s.target_armature=obj;s.adjust_mode='PATH'
bpy.context.scene.frame_set(1);bpy.context.preferences.view.show_splash=False
area=next(x for x in bpy.context.screen.areas if x.type=='VIEW_3D');region=next(x for x in area.regions if x.type=='WINDOW')
def digest(act):return repr([(c.data_path,c.array_index,a.core.snapshot(c)) for c in a.core.action_curves(act)])
source_before=digest(action);source_name=action.name
other=action.copy();other.name='SwitchToThis';other_name=other.name
started=time.monotonic();stage=-1
def event(t):
 for value in ('PRESS','RELEASE'):
  args=dict(type=t,value=value,x=region.x+region.width//2,y=region.y+region.height//2)
  if value=='PRESS': args['unicode']={'NINE':'9','ZERO':'0'}.get(t,'')
  bpy.context.window.event_simulate(**args)
def tick():
 global stage,other_before
 try:
  assert time.monotonic()-started<45,(stage,s.last_result)
  with bpy.context.temp_override(area=area,region=region):
   if stage==-1:
    bpy.context.window.event_simulate(type='MOUSEMOVE',value='NOTHING',x=region.x+region.width//2,y=region.y+region.height//2);stage=0
   elif stage==0:
    bpy.ops.ed.undo_push(message='Switch fixture');bpy.ops.faidlix_batch_clean_key.adjust_toggle();stage=1
   elif stage==1:
    assert bpy.ops.faidlix_batch_clean_key.switch(action_name=other_name)=={'FINISHED'};stage=2
   elif stage==2:
    assert a.adjust_ui.WATCH and s.adjust_enabled and s.adjust_toolbar_visible
    assert a.adjust_ui.WATCH.action_name==other_name and a.adjust_ui.WATCH.request is None
    assert digest(bpy.data.actions[source_name])==source_before
    ob=bpy.data.objects['Adjust']
    for b in ob.pose.bones:b.select=b.name=='Root'
    for c in a.adjust.bag_for(ob.animation_data.action,ob).fcurves:
     for p in c.keyframe_points:p.select_control_point='Root' in c.data_path and p.co.x in {1,11}
    other_before=digest(ob.animation_data.action);bpy.ops.ed.undo_push(message='Action list switch');event('R');stage=3
   elif stage==3:event('Z');stage=4
   elif stage==4:event('NINE');event('ZERO');stage=5
   elif stage==5:event('RET');stage=6
   elif stage==6:
    if s.running or not s.last_result.startswith('已多影格同步調整'):return .1
    assert digest(bpy.data.actions[source_name])==source_before,'previous Action must not be edited'
    assert digest(bpy.data.actions[other_name])!=other_before
    assert a.adjust_ui.WATCH and s.adjust_enabled
    bpy.ops.faidlix_batch_clean_key.switch(action_name=source_name);stage=7
   elif stage==7:
    assert a.adjust_ui.WATCH.action_name==source_name and s.adjust_enabled
    a.adjust_ui.adjust_hud.click(bpy.context,'toggle')
    bpy.ops.faidlix_batch_clean_key.switch(action_name=other_name);stage=8
   elif stage==8:
    assert a.adjust_ui.WATCH and s.adjust_toolbar_visible and not s.adjust_enabled
    bpy.ops.faidlix_batch_clean_key.adjust_close();stage=9
   elif stage==9:
    assert a.adjust_ui.WATCH is None and not s.adjust_toolbar_visible
    # The compact copy dialog opens with a single destination field.
    bpy.ops.faidlix_batch_clean_key.duplicate('INVOKE_DEFAULT',action_name=other_name);stage=10
   elif stage==10:
    bpy.ops.screen.screenshot(filepath=str(OUT/'duplicate-dialog-v160.png'));event('ESC');stage=11
   elif stage==11:
    (OUT/'adjust-switch-gui-result.txt').write_text('ADJUST_SWITCH_GUI_PASS active_and_paused_persist source_Action_unchanged current_Action_only duplicate_dialog_compact',encoding='utf-8')
    bpy.ops.wm.quit_blender();return None
  return .4
 except Exception:
  (OUT/'adjust-switch-gui-result.txt').write_text(traceback.format_exc(),encoding='utf-8');bpy.ops.wm.quit_blender();return None
bpy.app.timers.register(tick,first_interval=2)
