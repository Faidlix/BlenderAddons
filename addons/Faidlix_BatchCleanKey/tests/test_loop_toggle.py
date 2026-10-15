"""Run with Blender --background --factory-startup --python this_file.py.
Checks sparse looping, Vector crossings, interior horizontal extrema, cancellation and copy state.
"""
import bpy,sys,importlib,os,math,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
a=importlib.import_module(os.environ.get('BCK_TEST_MODULE','Faidlix_BatchCleanKey'))
if not hasattr(bpy.types.WindowManager,'faidlix_batch_clean_key'):a.register()
if bpy.context.object and bpy.context.object.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
arm=bpy.data.armatures.new('LoopRig');obj=bpy.data.objects.new('LoopRig',arm);bpy.context.collection.objects.link(obj)
for o in bpy.context.selected_objects:o.select_set(False)
obj.select_set(True);bpy.context.view_layer.objects.active=obj
bpy.ops.object.mode_set(mode='EDIT')
for i,n in enumerate(('Animated','Static')):
 b=arm.edit_bones.new(n);b.head=(i,0,0);b.tail=(i,1,0)
bpy.ops.object.mode_set(mode='OBJECT')
action=bpy.data.actions.new('LoopToggle');slot=action.slots.new('OBJECT',obj.name);foreign=action.slots.new('OBJECT','Foreign')
strip=action.layers.new('Layer').strips.new(type='KEYFRAME');bag=strip.channelbag(slot,ensure=True)
foreign_curve=strip.channelbag(foreign,ensure=True).fcurves.new('location',index=0);foreign_curve.keyframe_points.insert(40,8)
for i,points in enumerate((((0,0),(5,1),(15,-1),(20,0)),((0,1),(5,0),(15,0),(20,1)),((0,0),(4,2),(15,-1),(20,0)))):
 c=bag.fcurves.new('pose.bones["Animated"].location',index=i)
 for f,v in points:
  p=c.keyframe_points.insert(f,v);p.interpolation='LINEAR'
short=bag.fcurves.new('pose.bones["Animated"].scale',index=0)
for f,v in ((5,1),(10,2)):short.keyframe_points.insert(f,v)
short.modifiers.new('CYCLES');short.lock=True;short.mute=True
bag.fcurves.new('pose.bones["Animated"].scale',index=1)
obj.animation_data_create().action=action;obj.animation_data.action_slot=slot
s=bpy.context.window_manager.faidlix_batch_clean_key;s.target_armature=obj
def digest(act):return repr([(c.data_path,c.array_index,a.core.snapshot(c),[m.type for m in c.modifiers]) for c in a.core.action_curves(act)])
original=digest(action);g=a.ui.looping.toggle_steps(bpy.context,obj,action,True);next(g);g.close()
assert digest(action)==original and obj.animation_data.action==action
assert not any(x.name.startswith('__ActionEditorLoop__') for x in bpy.data.actions)
assert bpy.ops.faidlix_batch_clean_key.loop(action_name='LoopToggle')=={'FINISHED'}
action=bpy.data.actions['LoopToggle'];bag=a.ui.looping._bag(action,obj)
assert a.ui.looping.enabled(action) and action.use_cyclic
assert len(bag.fcurves)==5 and not any('Static' in c.data_path for c in bag.fcurves)
assert a.core.snapshot(action.layers[0].strips[0].channelbag(next(s for s in action.slots if s.identifier=='OBForeign')).fcurves[0])[0]['co']==(40,8)
for c in bag.fcurves:
 if not c.keyframe_points:assert not c.modifiers;continue
 assert c.keyframe_points[0].co.x==0 and c.keyframe_points[-1].co.x==20
 assert c.keyframe_points[0].co.y==c.keyframe_points[-1].co.y
 assert len(c.keyframe_points)==4
 if c.keyframe_points[0].handle_right_type!='VECTOR':
  assert math.isclose(a.ui.looping._slope(c.keyframe_points[0],'right'),a.ui.looping._slope(c.keyframe_points[-1],'left'),abs_tol=1e-6)
 assert [m.type for m in c.modifiers]==['CYCLES']
assert bag.fcurves[0].keyframe_points[0].handle_right_type=='VECTOR'
assert abs(a.ui.looping._slope(bag.fcurves[1].keyframe_points[0],'right'))<1e-6
assert bag.fcurves[2].keyframe_points[0].handle_right_type=='VECTOR'
for curve in (bag.fcurves[0],bag.fcurves[2]):
 for point in list(curve.keyframe_points)[1:-1]:
  assert abs(a.ui.looping._slope(point,'left'))<1e-6
  assert abs(a.ui.looping._slope(point,'right'))<1e-6
assert bag.fcurves[3].lock and bag.fcurves[3].mute
assert bpy.ops.faidlix_batch_clean_key.duplicate(action_name='LoopToggle',destination='CURRENT')=={'FINISHED'}
copy=obj.animation_data.action;copy_name=copy.name;assert a.ui.looping.enabled(copy)
keys={ (c.data_path,c.array_index):[(tuple(p.co),tuple(p.handle_left),tuple(p.handle_right)) for p in c.keyframe_points] for c in bag.fcurves }
assert bpy.ops.faidlix_batch_clean_key.loop(action_name='LoopToggle')=={'FINISHED'}
action=bpy.data.actions['LoopToggle'];assert not a.ui.looping.enabled(action) and not action.use_cyclic
for c in a.ui.looping._bag(action,obj).fcurves:
 assert not any(m.type=='CYCLES' for m in c.modifiers)
 assert [(tuple(p.co),tuple(p.handle_left),tuple(p.handle_right)) for p in c.keyframe_points]==keys[c.data_path,c.array_index]
assert a.ui.looping.enabled(bpy.data.actions[copy_name])
assert bpy.ops.faidlix_batch_clean_key.duplicate(action_name='LoopToggle',destination='CURRENT')=={'FINISHED'}
assert not a.ui.looping.enabled(obj.animation_data.action)
print('LOOP_TOGGLE_PASS sparse_only extrema_vector_asymmetric foreign_slot cancel copy_on_off off_keeps_geometry')

modified=bpy.data.actions.new('LoopModifiers');modified.use_fake_user=True
ms=modified.slots.new('OBJECT',obj.name);mb=modified.layers.new('Layer').strips.new(type='KEYFRAME').channelbag(ms,ensure=True)
nc=mb.fcurves.new('pose.bones["Animated"].location',index=0)
for frame,value in ((1,0),(5,2),(11,0)):nc.keyframe_points.insert(frame,value)
nc.modifiers.new('NOISE');nc.modifiers.new('CYCLES')
sc=mb.fcurves.new('pose.bones["Animated"].location',index=1)
sc.keyframe_points.insert(1,1);sc.keyframe_points.insert(11,3);sc.convert_to_samples(1,11)
expected={c.array_index:{float(p.co.x):c.evaluate(p.co.x) for p in (c.sampled_points if c.sampled_points else c.keyframe_points)} for c in mb.fcurves}
for _ in a.ui.looping.toggle_steps(bpy.context,obj,modified,True):pass
modified=bpy.data.actions['LoopModifiers']
for curve in a.ui.looping._bag(modified,obj).fcurves:
 assert not curve.sampled_points and [m.type for m in curve.modifiers]==['CYCLES']
 assert {float(p.co.x) for p in curve.keyframe_points}==set(expected[curve.array_index])|{1,11}
 for p in curve.keyframe_points:
  if p.co.x not in {1,11}:assert math.isclose(p.co.y,expected[curve.array_index][p.co.x],abs_tol=1e-5)
with tempfile.TemporaryDirectory(prefix='loop_persist_') as folder:
 path=str(Path(folder)/'loops.blend')
 bpy.data.libraries.write(path,{action,bpy.data.actions[copy_name],modified})
 with bpy.data.libraries.load(path) as (source,target):target.actions=source.actions
 assert sorted(bool(x.get('_faidlix_action_loop')) for x in target.actions)==[False,True,True]
 for x in target.actions:bpy.data.actions.remove(x)
print('LOOP_MODIFIER_PERSIST_PASS own_key_times sampled no_full_bake save_reload')
