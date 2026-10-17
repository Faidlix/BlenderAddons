"""Isolated Blender GUI test for Pose rotation-align dismiss-on-click menu, cancellation and Undo/Redo.
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
stage=0;out=ROOT/'validation/rotation-align-gui-result.txt'
def value():return next(a.core.action_curves(bpy.data.actions['AlignGUI'])).evaluate(2)
def test():
 global stage
 try:
  with bpy.context.temp_override(area=area,region=region):
   if stage==0:
    bpy.context.window.cursor_warp(area.x+area.width//2,area.y+area.height//2)
    bpy.ops.ed.undo_push(message='Before align')
    assert bpy.ops.faidlix_batch_clean_key.rotation_align('INVOKE_DEFAULT')=={'INTERFACE'}
   elif stage==1:
    assert math.isclose(value(),math.radians(380),abs_tol=1e-5)
    bpy.ops.screen.screenshot(filepath=str(ROOT/'validation/rotation-align-popup.png'))
    for val in ('PRESS','RELEASE'):bpy.context.window.event_simulate(type='ESC',value=val)
   elif stage==2:
    assert math.isclose(value(),math.radians(380),abs_tol=1e-5)
    bpy.context.window.event_simulate(type='MOUSEMOVE',value='NOTHING',x=area.x+area.width//2,y=area.y+area.height//2)
    stage=22;return .7
   elif stage==22:
    bpy.ops.faidlix_batch_clean_key.rotation_align('INVOKE_DEFAULT')
    stage=20;return .7
   elif stage==20:
    x=area.x+area.width//2-100;y=area.y+area.height//2+60
    bpy.context.window.event_simulate(type='MOUSEMOVE',value='NOTHING',x=x,y=y)
    stage=21;return .7
   elif stage==21:
    x=area.x+area.width//2-100;y=area.y+area.height//2+60
    bpy.ops.screen.screenshot(filepath=str(ROOT/'validation/rotation-align-hover.png'))
    for val in ('PRESS','RELEASE'):bpy.context.window.event_simulate(type='LEFTMOUSE',value=val,x=x,y=y)
    stage=3;return .7
   elif stage==3:
    assert math.isclose(value(),math.radians(20),abs_tol=1e-5),value()
    bpy.ops.ed.undo()
   elif stage==4:
    assert math.isclose(value(),math.radians(380),abs_tol=1e-5)
    bpy.ops.ed.redo()
   elif stage==5:
    assert math.isclose(value(),math.radians(20),abs_tol=1e-5)
    out.write_text('ROTATION_ALIGN_GUI_PASS popup_no_preselect escape_unchanged execute undo redo',encoding='utf-8')
    bpy.ops.wm.quit_blender();return None
  stage+=1;return .7
 except Exception:
  out.write_text(traceback.format_exc(),encoding='utf-8');bpy.ops.wm.quit_blender();return None
bpy.app.timers.register(test,first_interval=2)


