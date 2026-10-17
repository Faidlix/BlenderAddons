"""Native flip choices: cancel outside/Esc, copy-only mirror/reverse and dismissal.
Run --factory-startup --enable-event-simulate --python this_file.py; BCK_TEST_MODULE selects installation.
"""
import bpy,sys,os,importlib,time,traceback,math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'addons'))
a=importlib.import_module(os.environ.get('BCK_TEST_MODULE','Faidlix_BatchCleanKey'))
if not hasattr(bpy.types.WindowManager,'faidlix_batch_clean_key'):a.register()
bpy.context.preferences.view.show_splash=False
assert not bpy.data.filepath and not bpy.app.background
obj=bpy.data.objects.new('FlipGUI',bpy.data.armatures.new('FlipGUI'));bpy.context.collection.objects.link(obj)
for o in bpy.context.selected_objects:o.select_set(False)
obj.select_set(True);bpy.context.view_layer.objects.active=obj
bpy.ops.object.mode_set(mode='EDIT');b=obj.data.edit_bones.new('Bone');b.head=(0,0,0);b.tail=(0,0,1)
bpy.ops.object.mode_set(mode='POSE');obj.pose.bones['Bone'].rotation_mode='XYZ';obj.pose.bones['Bone'].select=True
act=bpy.data.actions.new('FlipGUI');slot=act.slots.new('OBJECT',obj.name)
bag=act.layers.new('Layer').strips.new(type='KEYFRAME').channelbag(slot,ensure=True)
c=bag.fcurves.new('pose.bones["Bone"].rotation_euler',index=2)
for f,v in ((1,10),(2,380),(3,390),(4,40)):
 p=c.keyframe_points.insert(f,math.radians(v));p.select_control_point=f in (2,3)
obj.animation_data_create().action=act;obj.animation_data.action_slot=slot
area=next(ar for ar in bpy.context.screen.areas if ar.type=='VIEW_3D');region=next(r for r in area.regions if r.type=='WINDOW')
state=bpy.context.window_manager.faidlix_batch_clean_key
state.target_armature=obj
original=repr([(c.data_path,c.array_index,a.core.snapshot(c)) for c in a.core.action_curves(act)])
initial=len(bpy.data.actions);stage=0;started=time.monotonic()
out=ROOT/'validation/flip-menu-gui-result.txt'
def digest():return repr([(c.data_path,c.array_index,a.core.snapshot(c)) for c in a.core.action_curves(bpy.data.actions['FlipGUI'])])
def test():
 global stage
 try:
  assert time.monotonic()-started<65,(stage,state.last_result)
  with bpy.context.temp_override(area=area,region=region):
   x=area.x+area.width//2;y=area.y+area.height//2
   if stage in (0,4,8,14):
    bpy.context.window.event_simulate(type='MOUSEMOVE',value='NOTHING',x=x,y=y)
   elif stage in (1,5,9,15):
    assert bpy.ops.faidlix_batch_clean_key.flip('INVOKE_DEFAULT',action_name='FlipGUI',mode='IN_PLACE',sample_step=99,keyed_only=True)=={'INTERFACE'}
   elif stage==2:
    assert len(bpy.data.actions)==initial and digest()==original
    bpy.ops.screen.screenshot(filepath=str(ROOT/'validation/flip-simple-menu.png'))
    for value in ('PRESS','RELEASE'):bpy.context.window.event_simulate(type='ESC',value=value)
   elif stage==3:
    assert len(bpy.data.actions)==initial and digest()==original
   elif stage==6:
    for value in ('PRESS','RELEASE'):bpy.context.window.event_simulate(type='LEFTMOUSE',value=value,x=x+500,y=y+200)
   elif stage==7:
    assert len(bpy.data.actions)==initial and digest()==original
   elif stage in (10,16):
    bpy.context.window.event_simulate(type='MOUSEMOVE',value='NOTHING',x=x-100,y=y+(60 if stage==10 else -30))
   elif stage in (11,17):
    for value in ('PRESS','RELEASE'):bpy.context.window.event_simulate(type='LEFTMOUSE',value=value,x=x-100,y=y+(60 if stage==11 else -30))
   elif stage in (12,18):
    if state.pending or state.running:return .15
    assert digest()==original,state.last_result
    count=1 if stage==12 else 2
    assert len(bpy.data.actions)==initial+count,(stage,state.last_result)
    assert state.flip_mode=='COPY' and state.flip_step==1 and not state.flip_keyed_only
    result=obj.animation_data.action
    assert result!=bpy.data.actions['FlipGUI']
    assert result.name.startswith('FlipGUI_Flipped' if stage==12 else 'FlipGUI_Reversed'),result.name
    assert all(p.interpolation=='BEZIER' for c in a.core.action_curves(result) for p in c.keyframe_points)
    if stage==18:
     curve=next(c for c in a.core.action_curves(result) if c.data_path.endswith('rotation_euler') and c.array_index==2)
     assert math.isclose(curve.evaluate(1),math.radians(40),abs_tol=1e-5)
    bpy.ops.screen.screenshot(filepath=str(ROOT/f'validation/flip-finished-{count}.png'))
   elif stage==13:
    for value in ('PRESS','RELEASE'):bpy.context.window.event_simulate(type='LEFTMOUSE',value=value,x=x-100,y=y+60)
   elif stage==19:
    assert len(bpy.data.actions)==initial+2
    out.write_text('FLIP_MENU_GUI_PASS only_two_choices esc_cancel outside_cancel mirror_copy reverse_copy source_unchanged defaults_explicit bezier dismiss',encoding='utf-8')
    bpy.ops.wm.quit_blender();return None
  stage+=1;return .5
 except Exception:
  out.write_text(traceback.format_exc(),encoding='utf-8');bpy.ops.wm.quit_blender();return None
bpy.app.timers.register(test,first_interval=2)
