"""Run only in an isolated --factory-startup --enable-event-simulate GUI process."""
import bpy, sys, os, importlib, time, traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'addons'))
assert not bpy.app.background and not bpy.data.filepath
addon=importlib.import_module(os.environ.get('BCK_TEST_MODULE','Faidlix_BatchCleanKey'))
if not hasattr(bpy.types.WindowManager,'faidlix_batch_clean_key'): addon.register()
bpy.context.preferences.view.show_splash=False
bpy.context.preferences.filepaths.use_auto_save_temporary_files=False
arm=bpy.data.armatures.new('ComposeUIFixture')
obj=bpy.data.objects.new('ComposeUIFixture',arm)
bpy.context.collection.objects.link(obj)
for o in bpy.context.selected_objects: o.select_set(False)
obj.select_set(True); bpy.context.view_layer.objects.active=obj
bpy.ops.object.mode_set(mode='EDIT')
for i,name in enumerate(('Root','Arm.L','Hand.L','Arm.R','Hand.R')):
 b=arm.edit_bones.new(name); b.head,b.tail=(i*.4,0,0),(i*.4,0,1)
 if i: b.parent=arm.edit_bones['Root']
bpy.ops.object.mode_set(mode='POSE')
for b in obj.pose.bones: b.select=b.name=='Arm.L'; b.rotation_mode='XYZ'
actions=[]
for n in range(2):
 a=bpy.data.actions.new('Main_Walk' if n==0 else 'Lower_Wave')
 slot=a.slots.new('OBJECT',obj.name)
 bag=a.layers.new('Layer').strips.new(type='KEYFRAME').channelbag(slot,ensure=True)
 for b in obj.pose.bones:
  c=bag.fcurves.new(b.path_from_id()+'.rotation_euler',index=1)
  for f,v in ((1,0),(15,1+n),(30,0)):
   p=c.keyframe_points.insert(f,v); p.interpolation='LINEAR'
 actions.append(a)
obj.animation_data_create().action=actions[0]; obj.animation_data.action_slot=actions[0].slots[0]
window=bpy.context.window
area=next(a for a in window.screen.areas if a.type=='VIEW_3D')
region=next(r for r in area.regions if r.type=='WINDOW')
scene=bpy.context.scene
original=(scene.frame_current,scene.frame_start,scene.frame_end,obj.animation_data.action.name)
before=repr([[(c.data_path,addon.core.snapshot(c)) for c in addon.core.action_curves(a)] for a in actions])
OUT=ROOT/'validation'; OUT.mkdir(exist_ok=True)
stage=0; started=time.monotonic()
def event(s,kind,value='PRESS',x=0,y=0):
 w=s.preview_window; a=next(a for a in w.screen.areas if a.type=='VIEW_3D'); r=next(r for r in a.regions if r.type=='WINDOW')
 scale=addon.compose_ui.ui_scale()
 w.event_simulate(type=kind,value=value,x=int(r.x+x*scale),y=int(r.y+y*scale))
def click(s,x,y):
 event(s,'LEFTMOUSE',x=x,y=y); event(s,'LEFTMOUSE','RELEASE',x=x,y=y)
def test():
 global stage
 try:
  assert time.monotonic()-started<90,'GUI timeout'
  with bpy.context.temp_override(window=window,area=area,region=region):
   s=addon.compose_ui.SESSION
   if stage==0:
    bpy.ops.ed.undo_push(message='Fixture')
    assert bpy.ops.faidlix_batch_clean_key.combine('INVOKE_DEFAULT')=={'FINISHED'}
    stage=1
   elif stage==1:
    assert s and s.preview_window!=window and len(bpy.context.window_manager.windows)==2
    a=next(a for a in s.preview_window.screen.areas if a.type=='VIEW_3D'); r=next(r for r in a.regions if r.type=='WINDOW')
    with bpy.context.temp_override(window=s.preview_window,area=a,region=r):
     bpy.ops.screen.screenshot(filepath=str(OUT/'compose-editor.png'))
    scale=addon.compose_ui.ui_scale()
    h=min(390,max(260,r.height/scale*.52)); right=max(380,r.width/scale-280); x0,x1=155,right-20
    y=h-245+15; x=x0+(x1-x0)*.4
    event(s,'LEFTMOUSE',x=x,y=y)
    event(s,'MOUSEMOVE','NOTHING',x=x+60,y=y)
    event(s,'LEFTMOUSE','RELEASE',x=x+60,y=y)
    stage=2
   elif stage==2:
    assert s.tracks[1][0].start>1,'Block drag did not move'
    x0,x1,low,span=s.mapping
    clip=s.tracks[1][0]
    x=x0+(clip.end-low)/span*(x1-x0)-2
    a=next(a for a in s.preview_window.screen.areas if a.type=='VIEW_3D'); r=next(r for r in a.regions if r.type=='WINDOW')
    y=min(390,max(260,r.height/addon.compose_ui.ui_scale()*.52))-245+15
    event(s,'LEFTMOUSE',x=x,y=y)
    event(s,'MOUSEMOVE','NOTHING',x=x-200,y=y)
    event(s,'LEFTMOUSE','RELEASE',x=x-200,y=y)
    stage=2.5
   elif stage==2.5:
    assert s.tracks[1][0].duration<29,'Trim handle'
    click(s,180,53) # duplicate
    stage=3
   elif stage==3:
    assert len(s.tracks[1])==2,'Duplicate button'
    click(s,40,53) # combined playback
    stage=4
   elif stage==4:
    assert s.play=='COMBINED' and s.frame>1
    assert (scene.frame_current,scene.frame_start,scene.frame_end,obj.animation_data.action.name)==original
    with bpy.context.temp_override(window=s.preview_window):
     bpy.ops.faidlix_batch_clean_key.combine_settings('INVOKE_DEFAULT')
    stage=4.2
   elif stage==4.2:
    assert s.popup
    with bpy.context.temp_override(window=s.preview_window):
     bpy.ops.screen.screenshot(filepath=str(OUT/'compose-settings.png'))
    event(s,'RET'); event(s,'RET','RELEASE'); stage=4.4
   elif stage==4.4:
    assert not s.popup,'Settings confirm'
    event(s,'ESC'); stage=5
   elif stage==5:
    assert addon.compose_ui.SESSION is None and len(bpy.context.window_manager.windows)==1
    assert not any(a.name.startswith('__BCK_ComposePreview') for a in bpy.data.scenes)
    assert before==repr([[(c.data_path,addon.core.snapshot(c)) for c in addon.core.action_curves(a)] for a in actions])
    bpy.ops.faidlix_batch_clean_key.combine('INVOKE_DEFAULT'); stage=6
   elif stage==6:
    a=next(a for a in s.preview_window.screen.areas if a.type=='VIEW_3D'); r=next(r for r in a.regions if r.type=='WINDOW')
    h=min(390,max(260,r.height/addon.compose_ui.ui_scale()*.52))
    s.name='GUI_Combined'; s.step=.01
    click(s,370,h-55); stage=7
   elif stage==7:
    assert s and s.worker,'Processing must show progress'
    assert 0 < s.progress < 1
    event(s,'ESC'); stage=7.2
   elif stage==7.2:
    assert s and not s.worker and not bpy.data.actions.get('GUI_Combined'),'Esc baking cancellation'
    s.step=1
    a=next(a for a in s.preview_window.screen.areas if a.type=='VIEW_3D'); r=next(r for r in a.regions if r.type=='WINDOW')
    h=min(390,max(260,r.height/addon.compose_ui.ui_scale()*.52))
    click(s,370,h-55); stage=7.4
   elif stage==7.4:
    if s: return .2
    assert obj.animation_data.action.name=='GUI_Combined'
    assert addon.core.actual_range(obj.animation_data.action)==(1,30)
    bpy.ops.ed.undo(); stage=8
   elif stage==8:
    target=bpy.data.objects['ComposeUIFixture']
    assert target.animation_data.action.name=='Main_Walk','Undo action assignment'
    assert not bpy.data.actions.get('GUI_Combined'),'Undo creation'
    bpy.ops.ed.redo(); stage=9
   elif stage==9:
    assert bpy.data.objects['ComposeUIFixture'].animation_data.action.name=='GUI_Combined'
    (OUT/'compose-gui-result.txt').write_text('COMPOSE_GUI_PASS window drag trim duplicate settings playback cancel progress escape_bake undo redo',encoding='utf-8')
    bpy.ops.wm.quit_blender(); return None
  return .5
 except Exception:
  (OUT/'compose-gui-result.txt').write_text(traceback.format_exc(),encoding='utf-8')
  if addon.compose_ui.SESSION: addon.compose_ui.SESSION.close()
  bpy.ops.wm.quit_blender(); return None
bpy.app.timers.register(test,first_interval=2)
