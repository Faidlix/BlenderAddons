"""Verify each native choice closes after one click across all supported editors.
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
stage=0;case_index=0;calls=[]
cases=(('VIEW_3D','rotation_align','PREVIOUS',0),('DOPESHEET','rotation_align','NEXT',1),('TIMELINE','pose_hold','FIRST',0),('GRAPH_EDITOR','pose_hold','LAST',1))
for module,fn in ((a.rotation_align,'align'),(a.pose_hold,'hold')):
 original=getattr(module,fn)
 def wrapper(*args,_original=original,_fn=fn,**kwargs):
  result=_original(*args,**kwargs);calls.append((_fn,args[1]));return result
 setattr(module,fn,wrapper)
out=ROOT/'validation/choice-dismiss-gui-result.txt'
def test():
 global stage,case_index,region
 try:
  mode,op,choice,row=cases[case_index]
  if stage==0:
   area.type=mode if mode in ('VIEW_3D','GRAPH_EDITOR') else 'DOPESHEET_EDITOR'
   if mode in ('DOPESHEET','TIMELINE'):area.ui_type=mode
   region=next(r for r in area.regions if r.type=='WINDOW')
  with bpy.context.temp_override(area=area,region=region):
   x=area.x+area.width//2;y=area.y+area.height//2
   if stage==0:
    bpy.context.view_layer.objects.active=obj
    obj.select_set(True);obj.pose.bones['Bone'].select=True
    curve=next(c for c in a.core.action_curves(bpy.data.actions['AlignGUI']) if c.data_path.endswith('rotation_euler') and c.array_index==2)
    for p,v in zip(curve.keyframe_points,(10,380,390,40)):
     p.co.y=math.radians(v);p.select_control_point=p.co.x in (2,3)
    curve.update()
    bpy.context.window.event_simulate(type='MOUSEMOVE',value='NOTHING',x=x,y=y)
   elif stage==1:
    assert getattr(bpy.ops.faidlix_batch_clean_key,op)('INVOKE_DEFAULT')=={'INTERFACE'}
   elif stage==2:
    assert len(calls)==case_index
    bpy.ops.screen.screenshot(filepath=str(ROOT/f'validation/choice-before-{case_index}.png'))
    bpy.context.window.event_simulate(type='MOUSEMOVE',value='NOTHING',x=x-100,y=y+(60 if row==0 else -30))
   elif stage==3:
    for val in ('PRESS','RELEASE'):bpy.context.window.event_simulate(type='LEFTMOUSE',value=val,x=x-100,y=y+(60 if row==0 else -30))
   elif stage==4:
    assert len(calls)==case_index+1,(case_index,calls)
    assert calls[-1][1]==choice,(choice,calls)
    bpy.ops.screen.screenshot(filepath=str(ROOT/f'validation/choice-after-{case_index}.png'))
    for val in ('PRESS','RELEASE'):bpy.context.window.event_simulate(type='LEFTMOUSE',value=val,x=x-100,y=y+(60 if row==0 else -30))
   elif stage==5:
    assert len(calls)==case_index+1,('second click executed again',calls)
    case_index+=1;stage=0
    if case_index==len(cases):
     out.write_text('CHOICE_DISMISS_GUI_PASS both_operators all_choices all_editors no_preselect click_once second_click_no_repeat',encoding='utf-8')
     bpy.ops.wm.quit_blender();return None
    return .5
  stage+=1;return .6
 except Exception:
  out.write_text(traceback.format_exc(),encoding='utf-8');bpy.ops.wm.quit_blender();return None
bpy.app.timers.register(test,first_interval=2)



