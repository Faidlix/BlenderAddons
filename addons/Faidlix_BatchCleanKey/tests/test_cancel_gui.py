import bpy, sys, time, traceback, hashlib, os, importlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'addons'))
assert not bpy.app.background and not bpy.data.filepath, 'Use a separate factory-startup GUI Blender'
addon=importlib.import_module(os.environ.get('BCK_TEST_MODULE','Faidlix_BatchCleanKey'))
if not hasattr(bpy.types.WindowManager,'faidlix_batch_clean_key'): addon.register()
bpy.context.preferences.view.show_splash=False
bpy.context.preferences.filepaths.use_auto_save_temporary_files=False
arm=bpy.data.armatures.new('CancelFixture')
obj=bpy.data.objects.new('CancelFixture',arm)
bpy.context.collection.objects.link(obj)
for o in bpy.context.selected_objects: o.select_set(False)
obj.select_set(True)
bpy.context.view_layer.objects.active=obj
bpy.ops.object.mode_set(mode='EDIT')
for i in range(12):
 b=arm.edit_bones.new(f'Bone{i:02d}')
 b.head,b.tail=(i,0,0),(i,0,1)
bpy.ops.object.mode_set(mode='POSE')
for b in obj.pose.bones: b.select=True
for n in range(12):
 a=bpy.data.actions.new(f'Animation{n:02d}')
 s=a.slots.new('OBJECT',obj.name)
 bag=a.layers.new('Layer').strips.new(type='KEYFRAME').channelbag(s,ensure=True)
 for b in obj.pose.bones:
  for i,value in enumerate([1,0,0,0]):
   c=bag.fcurves.new(b.path_from_id()+'.rotation_quaternion',index=i)
   for f in [1,100]: c.keyframe_points.insert(f,value)
 obj.animation_data_create().action=a
 obj.animation_data.action_slot=s
area=next(a for a in bpy.context.screen.areas if a.type=='VIEW_3D')
region=next(r for r in area.regions if r.type=='WINDOW')
OUT=ROOT/'validation'
OUT.mkdir(exist_ok=True)
stage=0
started=0
esc_at=0
def digest():
 return hashlib.sha256(repr([(a.name,[(c.data_path,c.array_index,addon.core.snapshot(c))
  for c in addon.core.action_curves(a)]) for a in bpy.data.actions]).encode()).hexdigest()
before=digest()
def test():
 global stage,started,esc_at
 try:
  with bpy.context.temp_override(area=area,region=region):
   state=bpy.context.window_manager.faidlix_batch_clean_key
   (OUT/'cancel-large-stage.txt').write_text(str((stage,state.running,state.progress)),encoding='utf-8')
   if stage==0:
    bpy.ops.faidlix_batch_clean_key.rotation('INVOKE_DEFAULT')
    stage=1
   elif stage==1:
    for item in state.actions: item.selected=True
    state.rotation_target='XYZ'
    state.sample_step=.1
    bpy.context.window.event_simulate(type='RET',value='PRESS')
    bpy.context.window.event_simulate(type='RET',value='RELEASE')
    started=time.monotonic()
    stage=2
   elif stage==2:
    assert time.monotonic()-started<float(os.environ.get('CANCEL_TIMEOUT','180')),'Processing did not reach cancellation threshold'
    if state.running and ((state.progress>=.99 and '寫回中' in state.progress_text) if os.environ.get('CANCEL_PHASE')=='COMMIT' else state.progress>=.75):
     bpy.ops.screen.screenshot(filepath=str(OUT/'cancel-large-progress.png'))
     if os.environ.get('CANCEL_INPUT')=='CLICK':
      width=min(560,max(240,region.width-60))
      x=int(region.x+(region.width-width)/2+width-40)
      y=int(region.y+max(20,region.height-115)+55)
      bpy.context.window.event_simulate(type='LEFTMOUSE',value='PRESS',x=x,y=y)
      bpy.context.window.event_simulate(type='LEFTMOUSE',value='RELEASE',x=x,y=y)
     else:
      bpy.context.window.event_simulate(type='ESC',value='PRESS')
      bpy.context.window.event_simulate(type='ESC',value='RELEASE')
     esc_at=time.monotonic()
     stage=3
   elif stage==3:
    elapsed=time.monotonic()-esc_at
    assert elapsed<2,'Esc did not cancel within 2 seconds'
    if not state.running:
     assert state.last_result=='已取消，原動畫保留',state.last_result
     assert before==digest(),'Original curves changed'
     assert all(b.rotation_mode=='QUATERNION' for b in obj.pose.bones)
     assert not any(a.name.startswith('__BatchCleanKey_Work__') for a in bpy.data.actions)
     bpy.ops.screen.screenshot(filepath=str(OUT/'cancel-large-after.png'))
     (OUT/'cancel-large-result.txt').write_text('LARGE_POPUP_CANCEL_PASS '+os.environ.get('CANCEL_PHASE','STAGING')+' '+os.environ.get('CANCEL_INPUT','ESC')+' '+str(elapsed),encoding='utf-8')
     bpy.ops.wm.quit_blender()
     return None
  return .05 if stage>=2 else .5
 except Exception:
  (OUT/'cancel-large-result.txt').write_text(traceback.format_exc(),encoding='utf-8')
  bpy.ops.wm.quit_blender()
  return None
bpy.app.timers.register(test,first_interval=2)
