"""Native regression: mirrored bilateral IK with Cycles, empty history, failure cleanup/restart.
Run isolated Blender --factory-startup --enable-event-simulate --python this_file.py.
BCK_TEST_MODULE selects the installed extension; writes validation/adjust-recovery-result.txt.
"""
import bpy,sys,os,importlib,time,traceback
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'addons'))
a=importlib.import_module(os.environ.get('BCK_TEST_MODULE','Faidlix_BatchCleanKey'))
if not hasattr(bpy.types.WindowManager,'faidlix_batch_clean_key'):a.register()
bpy.context.preferences.view.show_splash=False
obj=bpy.data.objects.new('RecoveryIK',bpy.data.armatures.new('RecoveryIK'));bpy.context.collection.objects.link(obj)
for o in bpy.context.selected_objects:o.select_set(False)
obj.select_set(True);bpy.context.view_layer.objects.active=obj
bpy.ops.object.mode_set(mode='EDIT')
for side,x in (('L',1),('R',-1)):
 for name,z in (('IK.',1),('Leg.',0)):
  b=obj.data.edit_bones.new(name+side);b.head=(x,0,z);b.tail=(x,0,z+1)
bpy.ops.object.mode_set(mode='POSE')
for side in ('L','R'):
 c=obj.pose.bones['Leg.'+side].constraints.new('IK');c.target=obj;c.subtarget='IK.'+side;c.chain_count=1
for b in obj.pose.bones:b.select=b.name.startswith('IK.');b.rotation_mode='XYZ'
obj.data.bones.active=obj.data.bones['IK.L']
act=bpy.data.actions.new('RecoveryLoop');sl=act.slots.new('OBJECT',obj.name)
bag=act.layers.new('Layer').strips.new(type='KEYFRAME').channelbag(sl,ensure=True)
for side in ('L','R'):
 for axis in range(3):
  c=bag.fcurves.new('pose.bones["IK.'+side+'"].location',index=axis)
  for f in (1,6,11):
   p=c.keyframe_points.insert(f,0);p.select_control_point=f in (1,11)
  c.modifiers.new('CYCLES')
obj.animation_data_create().action=act;obj.animation_data.action_slot=sl
bpy.context.scene.frame_set(1);obj.pose.use_mirror_x=True
bpy.context.scene.tool_settings.use_keyframe_insert_auto=True
s=bpy.context.window_manager.faidlix_batch_clean_key;s.target_armature=obj;s.adjust_mode='PATH'
area=next(ar for ar in bpy.context.screen.areas if ar.type=='VIEW_3D');region=next(r for r in area.regions if r.type=='WINDOW')
class Proxy:
 def __init__(self,source,**overrides):self.source=source;self.overrides=overrides
 def __getattr__(self,name):return self.overrides[name] if name in self.overrides else getattr(self.source,name)
def event(t):
 for v in ('PRESS','RELEASE'):bpy.context.window.event_simulate(type=t,value=v,x=region.x+region.width//2,y=region.y+region.height//2,**({'unicode':'1'} if t=='ONE' and v=='PRESS' else {}))
def digest():return repr([(c.data_path,c.array_index,a.core.snapshot(c)) for c in a.core.action_curves(bpy.data.actions['RecoveryLoop'])])
before=digest();stage=0;started=time.monotonic();original_hover=a.adjust_hud.hover
out=ROOT/'validation/adjust-recovery-result.txt'
def tick():
 global stage
 try:
  assert time.monotonic()-started<55,(stage,s.last_result)
  with bpy.context.temp_override(area=area,region=region):
   if stage==0:
    bpy.context.window.event_simulate(type='MOUSEMOVE',value='NOTHING',x=region.x+region.width//2,y=region.y+region.height//2)
    bpy.ops.ed.undo_push(message='Recovery fixture')
    assert bpy.ops.faidlix_batch_clean_key.adjust_toggle()=={'RUNNING_MODAL'}
   elif stage==1:
    w=a.adjust_ui.WATCH;w.request={'sentinel':True};w.operator_pointer=123;w.started=time.monotonic();w.auto=True
    bpy.context.scene.tool_settings.use_keyframe_insert_auto=False
    ctx=Proxy(bpy.context,window_manager=Proxy(bpy.context.window_manager,operators=[]))
    assert w.modal(ctx,SimpleNamespace(type='TIMER',value='NOTHING'))=={'PASS_THROUGH'}
    assert w.request is None and s.adjust_enabled and bpy.context.scene.tool_settings.use_keyframe_insert_auto
    assert digest()==before
    # Inject an unexpected observer failure through a real native event.
    def fail(*args):raise RuntimeError('INJECTED_OBSERVER_FAILURE')
    a.adjust_hud.hover=fail;w.auto=True;bpy.context.scene.tool_settings.use_keyframe_insert_auto=False
    bpy.context.window.event_simulate(type='MOUSEMOVE',value='NOTHING',x=region.x+region.width//2+1,y=region.y+region.height//2)
   elif stage==2:
    a.adjust_hud.hover=original_hover
    assert a.adjust_ui.WATCH is None and not s.adjust_enabled and not s.adjust_toolbar_visible
    assert bpy.context.scene.tool_settings.use_keyframe_insert_auto and digest()==before
    assert bpy.ops.faidlix_batch_clean_key.adjust_toggle()=={'RUNNING_MODAL'}
   elif stage==3:event('G')
   elif stage==4:event('Z')
   elif stage==5:event('ONE')
   elif stage==6:event('RET')
   elif stage==7:
    if s.running or not s.last_result.startswith('已多影格同步調整'):return .1
    ob=bpy.data.objects['RecoveryIK'];bg=a.adjust.bag_for(ob.animation_data.action,ob)
    assert ob.pose.use_mirror_x
    for side in ('L','R'):
     c=bg.fcurves.find('pose.bones["IK.'+side+'"].location',index=1)
     assert {p.co.x for p in c.keyframe_points}=={1,6,11}
     assert abs(c.evaluate(1)-1)<1e-4 and abs(c.evaluate(11)-1)<1e-4,(side,[(tuple(p.co)) for p in c.keyframe_points],s.last_result)
     assert next(p.co.y for p in c.keyframe_points if p.co.x==6)==0
     assert any(m.type=='CYCLES' for m in c.modifiers)
    assert s.adjust_enabled and bpy.context.scene.tool_settings.use_keyframe_insert_auto
    s.adjust_toolbar_visible=False
   elif stage==8:
    assert a.adjust_ui.WATCH is None
    out.write_text('ADJUST_RECOVERY_PASS empty_history no_key_changes failure_cleanup auto_key_restore restart native_mirror_bilateral_IK_cycles same_frames',encoding='utf-8')
    bpy.ops.wm.quit_blender();return None
  stage+=1;return .4
 except Exception:
  a.adjust_hud.hover=original_hover;out.write_text(traceback.format_exc(),encoding='utf-8');bpy.ops.wm.quit_blender();return None
bpy.app.timers.register(tick,first_interval=2)
