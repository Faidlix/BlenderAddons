"""Isolated GUI test of animation-editor context menus and both Pose key operators.
Run --factory-startup --enable-event-simulate --python this_file.py; BCK_TEST_MODULE selects installation.
"""
import bpy,sys,os,importlib,time,traceback,math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'addons'))
a=importlib.import_module(os.environ.get('BCK_TEST_MODULE','Faidlix_BatchCleanKey'))
if not hasattr(bpy.types.WindowManager,'faidlix_batch_clean_key'):a.register()
bpy.context.preferences.view.show_splash=False
assert not bpy.data.filepath and not bpy.app.background
obj=bpy.data.objects.new('AlignGUI',bpy.data.armatures.new('AlignGUI'));bpy.context.collection.objects.link(obj)
for o in bpy.context.selected_objects:o.select_set(False)
obj.select_set(True);bpy.context.view_layer.objects.active=obj
bpy.ops.object.mode_set(mode='EDIT');b=obj.data.edit_bones.new('Bone');b.head=(0,0,0);b.tail=(0,0,1)
bpy.ops.object.mode_set(mode='POSE');obj.pose.bones['Bone'].rotation_mode='XYZ';obj.pose.bones['Bone'].select=True
act=bpy.data.actions.new('AlignGUI');slot=act.slots.new('OBJECT',obj.name)
bag=act.layers.new('Layer').strips.new(type='KEYFRAME').channelbag(slot,ensure=True)
c=bag.fcurves.new('pose.bones["Bone"].rotation_euler',index=2)
for f,v in ((1,10),(2,380),(3,390),(4,40)):
 p=c.keyframe_points.insert(f,math.radians(v));p.select_control_point=f in (2,3)
obj.animation_data_create().action=act;obj.animation_data.action_slot=slot
area=next(ar for ar in bpy.context.screen.areas if ar.type=='VIEW_3D');region=next(r for r in area.regions if r.type=='WINDOW')
stage=0;mode_index=0
modes=('DOPESHEET','TIMELINE','GRAPH_EDITOR')
out=ROOT/'validation/editor-context-gui-result.txt'
def curve():return next(c for c in a.core.action_curves(bpy.data.actions['AlignGUI']) if c.data_path.endswith('rotation_euler') and c.array_index==2)
def test():
 global stage,mode_index,region
 try:
  mode=modes[mode_index]
  if stage==0:
   area.type='GRAPH_EDITOR' if mode=='GRAPH_EDITOR' else 'DOPESHEET_EDITOR'
   if mode!='GRAPH_EDITOR':area.ui_type=mode
   region=next(r for r in area.regions if r.type=='WINDOW')
  with bpy.context.temp_override(area=area,region=region):
   if stage==0:
    assert a.core.selected_bones(bpy.context)==['Bone'],(mode,bpy.context.mode)
    assert bpy.ops.faidlix_batch_clean_key.rotation_align.poll()
    assert bpy.ops.faidlix_batch_clean_key.pose_hold.poll()
    c=curve()
    for p,v in zip(c.keyframe_points,(10,380,390,40)):
     p.co.y=math.radians(v);p.select_control_point=p.co.x in (2,3)
    c.update()
    name='GRAPH_MT_context_menu' if mode=='GRAPH_EDITOR' else 'DOPESHEET_MT_context_menu'
    assert bpy.ops.wm.call_menu(name=name)=={'INTERFACE'}
   elif stage==1:
    bpy.ops.screen.screenshot(filepath=str(ROOT/f'validation/editor-context-{mode}.png'))
    for value in ('PRESS','RELEASE'):bpy.context.window.event_simulate(type='ESC',value=value)
   elif stage==2:
    assert bpy.ops.faidlix_batch_clean_key.rotation_align(direction='PREVIOUS')=={'FINISHED'}
    assert math.isclose(curve().evaluate(2),math.radians(20),abs_tol=1e-5),mode
    assert math.isclose(curve().evaluate(3),math.radians(30),abs_tol=1e-5),mode
    assert bpy.ops.faidlix_batch_clean_key.pose_hold(anchor='FIRST')=={'FINISHED'}
    assert math.isclose(curve().evaluate(2.5),math.radians(20),abs_tol=1e-5),mode
    assert bpy.ops.faidlix_batch_clean_key.rotation_align('INVOKE_DEFAULT')=={'INTERFACE'}
   elif stage==3:
    for value in ('PRESS','RELEASE'):bpy.context.window.event_simulate(type='ESC',value=value)
   elif stage==4:
    assert bpy.ops.faidlix_batch_clean_key.pose_hold('INVOKE_DEFAULT')=={'INTERFACE'}
   elif stage==5:
    for value in ('PRESS','RELEASE'):bpy.context.window.event_simulate(type='ESC',value=value)
   elif stage==6:
    mode_index+=1;stage=0
    if mode_index==len(modes):
     # Registration cycles must not accumulate duplicate menu callbacks.
     for module in (a.rotation_align,a.pose_hold):
      module.unregister();module.register()
      for target in module.MENUS:assert target._dyn_ui_initialize().count(module.menu)==1
     out.write_text('EDITOR_CONTEXT_GUI_PASS dopesheet timeline graph both_execute both_popup selected_pose_bones registration',encoding='utf-8')
     bpy.ops.wm.quit_blender();return None
    return .4
  stage+=1;return .4
 except Exception:
  out.write_text(traceback.format_exc(),encoding='utf-8');bpy.ops.wm.quit_blender();return None
bpy.app.timers.register(test,first_interval=2)
