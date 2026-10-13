import bpy, runpy, math
from pathlib import Path
from mathutils import Matrix, Quaternion, Euler, Vector
fixture=runpy.run_path(str(Path(__file__).with_name('test_adjust.py')),run_name='__main__')
a,obj,consume=fixture['a'],fixture['obj'],fixture['consume']
for b in obj.pose.bones: b.select=b.name=='Root'
for mode in ('XYZ','ZYX','QUATERNION','AXIS_ANGLE'):
 act=bpy.data.actions.new('Dual_'+mode); slot=act.slots.new('OBJECT',obj.name)
 bag=act.layers.new('Layer').strips.new(type='KEYFRAME').channelbag(slot,ensure=True)
 euler_order=mode if mode in {'XYZ','ZYX'} else 'XYZ'
 original=Euler((.15,.2,.3),euler_order).to_quaternion()
 values={'rotation_euler':(.15,.2,.3),'rotation_quaternion':tuple(original),'rotation_axis_angle':(original.angle,*original.axis)}
 expected_prop={'QUATERNION':'rotation_quaternion','AXIS_ANGLE':'rotation_axis_angle'}.get(mode,'rotation_euler')
 stale=Euler((.9,.8,.7),'XYZ').to_quaternion()
 stale_values={'rotation_euler':(.9,.8,.7),'rotation_quaternion':tuple(stale),'rotation_axis_angle':(stale.angle,*stale.axis)}
 for prop,vs in values.items():
  if prop!=expected_prop: vs=stale_values[prop]
  for i,v in enumerate(vs):
   c=bag.fcurves.new('pose.bones["Root"].'+prop,index=i)
   for frame in (1,6,11):
    p=c.keyframe_points.insert(frame,v);p.select_control_point=frame!=6;p.interpolation='BEZIER'
 obj.animation_data.action=act;obj.animation_data.action_slot=slot
 obj.pose.bones['Root'].rotation_mode=mode;obj.pose.bones['Root'].location=(0,0,0);obj.pose.bones['Root'].scale=(1,1,1)
 bpy.context.scene.frame_set(1)
 before={ (c.data_path,c.array_index):next(p.co.y for p in c.keyframe_points if p.co.x==6) for c in bag.fcurves }
 request=a.adjust.capture(bpy.context,obj)
 delta=Matrix.Rotation(math.pi/2,4,'Z')
 plans=consume(a.adjust.steps(request,{'Root':delta},'PATH','Root'))
 assert all(set(v)<={1,11} for v in plans.values())
 a.adjust.commit(request,plans)
 for frame in (1,11):
  def component(prop,size):return [bag.fcurves.find('pose.bones["Root"].'+prop,index=i).evaluate(frame) for i in range(size)]
  q=Quaternion(component('rotation_quaternion',4)).normalized()
  e=Euler(component('rotation_euler',3),euler_order).to_quaternion()
  aa=component('rotation_axis_angle',4); axis=Vector(aa[1:]); axial=Quaternion(axis,aa[0])
  expected=delta.to_quaternion()@original
  assert q.rotation_difference(expected).angle<1e-3
  assert e.rotation_difference(expected).angle<1e-3
  assert axial.rotation_difference(expected).angle<1e-3
 for c in bag.fcurves:
  assert {p.co.x for p in c.keyframe_points}=={1,6,11}
  assert next(p.co.y for p in c.keyframe_points if p.co.x==6)==before[c.data_path,c.array_index]
  assert all(p.interpolation=='BEZIER' for p in c.keyframe_points)
 assert obj.pose.bones['Root'].rotation_mode==mode
 # Cancelling a partially written dual-channel edit restores every representation.
 snapshots=repr([(c.data_path,c.array_index,a.core.snapshot(c)) for c in bag.fcurves])
 req=a.adjust.capture(bpy.context,obj); plan=consume(a.adjust.steps(req,{'Root':delta},'PATH','Root'))
 writer=a.adjust.commit_steps(req,plan);next(writer);writer.close()
 assert snapshots==repr([(c.data_path,c.array_index,a.core.snapshot(c)) for c in bag.fcurves])
print('ADJUST_DUAL_PASS active_mode_authoritative Euler_Quaternion_AxisAngle same_times Bezier unselected_preserved rollback')
