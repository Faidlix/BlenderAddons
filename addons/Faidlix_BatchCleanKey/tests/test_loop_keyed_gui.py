import bpy,sys,os,importlib,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'addons'))
addon=importlib.import_module(os.environ.get('BCK_TEST_MODULE','Faidlix_BatchCleanKey'))
if not hasattr(bpy.types.WindowManager,'faidlix_batch_clean_key'): addon.register()
bpy.context.preferences.view.show_splash=False
arm=bpy.data.armatures.new('KeyedLoop'); obj=bpy.data.objects.new('KeyedLoop',arm)
bpy.context.collection.objects.link(obj)
for o in bpy.context.selected_objects: o.select_set(False)
obj.select_set(True); bpy.context.view_layer.objects.active=obj
bpy.ops.object.mode_set(mode='EDIT'); b=arm.edit_bones.new('Bone'); b.head=(0,0,0); b.tail=(0,0,1)
bpy.ops.object.mode_set(mode='POSE')
action=bpy.data.actions.new('SparseCycle'); slot=action.slots.new('OBJECT',obj.name)
bag=action.layers.new('Layer').strips.new(type='KEYFRAME').channelbag(slot,ensure=True)
c=bag.fcurves.new('pose.bones["Bone"].location',index=0)
for f,v in ((1,0),(6,2),(30,3)): c.keyframe_points.insert(f,v)
c.modifiers.new('CYCLES'); obj.animation_data_create().action=action; obj.animation_data.action_slot=slot
before=addon.core.snapshot(c)
area=next(a for a in bpy.context.screen.areas if a.type=='VIEW_3D'); region=next(r for r in area.regions if r.type=='WINDOW')
OUT=ROOT/'validation'; stage=0; started=time.monotonic()
def event(kind):
 bpy.context.window.event_simulate(type=kind,value='PRESS'); bpy.context.window.event_simulate(type=kind,value='RELEASE')
def tick():
 global stage
 try:
  assert time.monotonic()-started<45
  with bpy.context.temp_override(area=area,region=region):
   state=bpy.context.window_manager.faidlix_batch_clean_key
   if stage==0:
    bpy.ops.ed.undo_push(message='Sparse loop fixture')
    bpy.ops.faidlix_batch_clean_key.loop('INVOKE_DEFAULT',action_name=action.name); stage=1
   elif stage==1:
    bpy.ops.screen.screenshot(filepath=str(OUT/'v141-keyed-loop.png')); event('ESC'); stage=2
   elif stage==2:
    assert not bpy.data.actions.get('SparseCycle_Loop')
    bpy.ops.faidlix_batch_clean_key.loop('INVOKE_DEFAULT',action_name=action.name); stage=3
   elif stage==3: event('RET'); stage=4
   elif stage==4:
    if state.pending or state.running: return .05
    copy=bpy.data.actions['SparseCycle_Loop']; out=list(addon.core.action_curves(copy))
    assert len(out)==1 and [p.co.x for p in out[0].keyframe_points]==[1,6,30]
    assert not out[0].modifiers and abs(out[0].evaluate(1)-out[0].evaluate(30))<1e-6
    assert addon.core.snapshot(c)==before and len(c.modifiers)==1
    bpy.ops.ed.undo(); stage=5
   elif stage==5:
    assert not bpy.data.actions.get('SparseCycle_Loop')
    bpy.ops.ed.redo(); stage=6
   elif stage==6:
    assert bpy.data.objects['KeyedLoop'].animation_data.action.name=='SparseCycle_Loop'
    (OUT/'keyed-loop-gui-result.txt').write_text('KEYED_LOOP_GUI_PASS native_popup hidden_interval Cycles sparse_keys Cancel Undo Redo',encoding='utf-8')
    bpy.ops.wm.quit_blender(); return None
  return .5
 except Exception:
  (OUT/'keyed-loop-gui-result.txt').write_text(traceback.format_exc(),encoding='utf-8')
  bpy.ops.wm.quit_blender(); return None
bpy.app.timers.register(tick,first_interval=2)
