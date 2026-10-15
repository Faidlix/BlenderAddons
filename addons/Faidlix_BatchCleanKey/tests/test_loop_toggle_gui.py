"""Verify direct loop toggle, Vector seams, Pose activation and Undo in an isolated GUI Blender.
Run blender --factory-startup --enable-event-simulate --python this_file.py;
BCK_TEST_MODULE may name a freshly installed package instead of the source.
"""
import bpy,sys,os,importlib,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'addons'))
assert not bpy.app.background and not bpy.data.filepath
a=importlib.import_module(os.environ.get('BCK_TEST_MODULE','Faidlix_BatchCleanKey'))
if not hasattr(bpy.types.WindowManager,'faidlix_batch_clean_key'):a.register()
bpy.context.preferences.view.show_splash=False
bpy.context.preferences.filepaths.use_auto_save_temporary_files=False
arm=bpy.data.armatures.new('PoseLoop');obj=bpy.data.objects.new('PoseLoop',arm);bpy.context.collection.objects.link(obj)
for o in bpy.context.selected_objects:o.select_set(False)
obj.select_set(True);bpy.context.view_layer.objects.active=obj
bpy.ops.object.mode_set(mode='EDIT');bone=arm.edit_bones.new('Bone');bone.head=(0,0,0);bone.tail=(0,0,1)
bpy.ops.object.mode_set(mode='OBJECT')
act=bpy.data.actions.new('LoopGUI');sl=act.slots.new('OBJECT',obj.name);bag=act.layers.new('Layer').strips.new(type='KEYFRAME').channelbag(sl,ensure=True)
c=bag.fcurves.new('pose.bones["Bone"].location',index=0)
for f,v in ((0,0),(5,1),(15,-1),(20,0)):c.keyframe_points.insert(f,v)
act.use_fake_user=True
s=bpy.context.window_manager.faidlix_batch_clean_key;s.target_armature=obj
area=next(ar for ar in bpy.context.screen.areas if ar.type=='VIEW_3D');region=next(r for r in area.regions if r.type=='WINDOW')
area.spaces.active.show_region_ui=True
stage=0;started=time.monotonic();out=ROOT/'validation/loop-toggle-gui-result.txt'
def test():
 global stage
 try:
  assert time.monotonic()-started<45,(stage,s.last_result)
  with bpy.context.temp_override(area=area,region=region):
   if stage==0:
    assert bpy.ops.faidlix_batch_clean_key.switch(action_name='LoopGUI')=={'FINISHED'}
    assert obj.mode=='POSE' and bpy.context.object==obj
    assert a.ui.BCK_PT_View3D.bl_label=='Action Editor'
    bpy.ops.ed.undo_push(message='Before loop')
    assert bpy.ops.faidlix_batch_clean_key.loop('INVOKE_DEFAULT',action_name='LoopGUI')=={'FINISHED'}
    stage=1
   elif stage==1:
    if s.pending or s.running:return .1
    assert a.ui.looping.enabled(bpy.data.actions['LoopGUI']),s.last_result
    curve=a.ui.looping._bag(bpy.data.actions['LoopGUI'],obj).fcurves[0]
    assert curve.keyframe_points[0].handle_right_type=='VECTOR'
    assert curve.keyframe_points[-1].handle_left_type=='VECTOR'
    assert a.ui.looping._slope(curve.keyframe_points[0],'right')>0
    assert a.ui.looping._slope(curve.keyframe_points[-1],'left')>0
    bpy.ops.wm.call_panel(name='BCK_PT_view3d',keep_open=True);stage=10
   elif stage==10:
    bpy.ops.screen.screenshot(filepath=str(ROOT/'validation/action-editor-loop-on.png'))
    for value in ('PRESS','RELEASE'):bpy.context.window.event_simulate(type='ESC',value=value)
    stage=11
   elif stage==11:
    bpy.ops.ed.undo();stage=2
   elif stage==2:
    assert not a.ui.looping.enabled(bpy.data.actions['LoopGUI'])
    bpy.ops.ed.redo();stage=3
   elif stage==3:
    assert a.ui.looping.enabled(bpy.data.actions['LoopGUI'])
    assert bpy.ops.faidlix_batch_clean_key.loop('INVOKE_DEFAULT',action_name='LoopGUI')=={'FINISHED'}
    stage=4
   elif stage==4:
    if s.pending or s.running:return .1
    act=bpy.data.actions['LoopGUI'];assert not a.ui.looping.enabled(act),s.last_result
    assert not any(m.type=='CYCLES' for c in a.core.action_curves(act) for m in c.modifiers)
    bpy.ops.screen.screenshot(filepath=str(ROOT/'validation/action-editor-loop-off.png'))
    out.write_text('LOOP_TOGGLE_GUI_PASS direct_no_popup pose_mode on off undo redo',encoding='utf-8')
    bpy.ops.wm.quit_blender();return None
  return .5
 except Exception:
  out.write_text(traceback.format_exc(),encoding='utf-8');bpy.ops.wm.quit_blender();return None
bpy.app.timers.register(test,first_interval=2)
