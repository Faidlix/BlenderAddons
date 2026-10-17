"""Native Dope Sheet/Timeline amplitude drag, cancel and Undo/Redo regression.
Run isolated Blender --factory-startup --enable-event-simulate --python this_file.py.
BCK_TEST_MODULE selects the installed package; writes validation/amplitude-result.txt.
"""
import bpy,os,sys,importlib,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'addons'))
a=importlib.import_module(os.environ.get('BCK_TEST_MODULE','Faidlix_BatchCleanKey'))
if not hasattr(bpy.types.WindowManager,'faidlix_batch_clean_key'):a.register()
bpy.context.preferences.view.show_splash=False
obj=bpy.context.object
obj.animation_data_create();act=bpy.data.actions.new('AmplitudeFixture');slot=act.slots.new('OBJECT',obj.name)
obj.animation_data.action=act;obj.animation_data.action_slot=slot
bag=act.layers.new('Layer').strips.new(type='KEYFRAME').channelbag(slot,ensure=True)
for axis,values in enumerate(((1,3,9),(10,14,20),(4,8,12))):
 c=bag.fcurves.new('location',index=axis)
 for frame,val in zip((1,10,20),values):
  p=c.keyframe_points.insert(frame,val);p.select_control_point=frame!=20;p.handle_left_type=p.handle_right_type='FREE'
  p.handle_left=(frame-.3,val-.5);p.handle_right=(frame+.3,val+.5)
 if axis==2:c.lock=True
 c.modifiers.new('CYCLES')
area=next(ar for ar in bpy.context.screen.areas if ar.type=='DOPESHEET_EDITOR');area.ui_type='DOPESHEET'
region=next(r for r in area.regions if r.type=='WINDOW')
def curves():return list(a.core.action_curves(bpy.data.actions['AmplitudeFixture']))
def digest():return repr([(c.array_index,a.core.snapshot(c)) for c in curves()])
before=digest();stage=0;began=time.monotonic();out=ROOT/'validation/amplitude-result.txt'
def mouse(kind,value,x):bpy.context.window.event_simulate(type=kind,value=value,x=x,y=region.y+region.height//2)
def tick():
 global stage
 try:
  assert time.monotonic()-began<50,(stage,bool(a.amplitude.ACTIVE))
  with bpy.context.temp_override(area=area,region=region):
   x=region.x+region.width//2
   if stage==0:
    mouse('MOUSEMOVE','NOTHING',x);bpy.ops.ed.undo_push(message='Amplitude fixture')
   elif stage==1:
    rows=a.amplitude.capture(bpy.context);assert len(rows)==2,[(c.data_path,c.array_index) for c in getattr(bpy.context,'editable_fcurves',[]) or []]
    assert bpy.ops.faidlix_batch_clean_key.amplitude('INVOKE_DEFAULT')=={'RUNNING_MODAL'}
   elif stage==2:mouse('MOUSEMOVE','NOTHING',x+200)
   elif stage==3:
    cs=curves();assert [round(p.co.y,4) for p in cs[0].keyframe_points]==[0,4,9]
    assert [round(p.co.y,4) for p in cs[1].keyframe_points]==[8,16,20]
    assert [p.co.x for p in cs[0].keyframe_points]==[1,10,20]
    assert abs(cs[0].keyframe_points[0].handle_left.y+1)<1e-5
    assert [p.co.y for p in cs[2].keyframe_points]==[4,8,12]
    mouse('RIGHTMOUSE','PRESS',x+200);mouse('RIGHTMOUSE','RELEASE',x+200)
   elif stage==4:
    assert digest()==before and a.amplitude.ACTIVE is None
    area.ui_type='TIMELINE';mouse('MOUSEMOVE','NOTHING',x)
   elif stage==5:
    assert len(a.amplitude.capture(bpy.context))==2
    assert bpy.ops.faidlix_batch_clean_key.amplitude('INVOKE_DEFAULT')=={'RUNNING_MODAL'}
   elif stage==6:mouse('MOUSEMOVE','NOTHING',x-100)
   elif stage==7:
    assert [round(p.co.y,4) for p in curves()[0].keyframe_points]==[1.5,2.5,9]
    mouse('LEFTMOUSE','PRESS',x-100);mouse('LEFTMOUSE','RELEASE',x-100)
   elif stage==8:
    assert a.amplitude.ACTIVE is None
    bpy.ops.ed.undo()
   elif stage==9:
    assert digest()==before,'undo'
    bpy.ops.ed.redo()
   elif stage==10:
    assert [round(p.co.y,4) for p in curves()[0].keyframe_points]==[1.5,2.5,9]
    assert all([m.type for m in c.modifiers]==['CYCLES'] for c in curves())
    for c in curves():
     for p in c.keyframe_points:p.handle_left_type=p.handle_right_type='AUTO_CLAMPED'
     c.update()
    auto_before=digest();rows=a.amplitude.capture(bpy.context)
    a.amplitude.apply(rows,1.5);a.amplitude.apply(rows,1,restore=True)
    assert digest()==auto_before,'automatic handles cancel'
    for c in curves():
     for p in c.keyframe_points:p.select_control_point=p.co.x==1
    assert not bpy.ops.faidlix_batch_clean_key.amplitude.poll()
    out.write_text('AMPLITUDE_GUI_PASS dopesheet timeline mean_per_curve drag_right_left handles cancel_exact undo_redo frames_locked_cycles_preserved minimum_two',encoding='utf-8')
    bpy.ops.wm.quit_blender();return None
  stage+=1;return .4
 except Exception:
  out.write_text(traceback.format_exc(),encoding='utf-8');bpy.ops.wm.quit_blender();return None
bpy.app.timers.register(tick,first_interval=2)
