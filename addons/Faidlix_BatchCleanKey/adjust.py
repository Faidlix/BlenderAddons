"""Selected-key pose offsets. Planning is read-only; committing is transactional."""
import json, math, re
import bpy
from mathutils import Matrix, Vector, Quaternion, Euler
from . import core
TRS=('location','rotation_euler','rotation_quaternion','rotation_axis_angle','scale')
PATTERN=re.compile(r'^pose\.bones\[("(?:\\.|[^"\\])*")\]\.(location|rotation_euler|rotation_quaternion|rotation_axis_angle|scale)$')

def has_values(curve):
 return bool(curve.keyframe_points or curve.sampled_points or any(not m.mute and m.type!='CYCLES' for m in curve.modifiers))

def bag_for(action,obj):
 slot=core.slot_for(action,obj)
 bags=[s.channelbag(slot) for l in action.layers for s in l.strips if slot and s.type=='KEYFRAME' and s.channelbag(slot)]
 if len(bags)!=1: raise ValueError('一起調整需要明確的單層 Action Slot')
 return bags[0]

def capture(context,obj):
 action=obj.animation_data.action if obj.animation_data else None
 if not action or not obj.is_editable or not action.is_editable: raise ValueError('請使用可編輯骨架與目前 Action')
 bag=bag_for(action,obj); names={b.name for b in obj.pose.bones if b.select}
 times={n:set() for n in names}
 for c in bag.fcurves:
  m=core.BONE_PREFIX.match(c.data_path)
  name=json.loads(m[1][len('pose.bones['):-1]) if m else None
  if name in names:
   times[name].update(float(p.co.x) for p in c.keyframe_points if p.select_control_point)
 times={n:sorted(t) for n,t in times.items() if t}
 if not times: raise ValueError('請同時選取骨頭與它們的 Key')
 return {'object':obj.name,'action':action.name,'slot':core.slot_for(action,obj).identifier,
         'times':times,'selected':sorted(names),'defaults':{b.name:{p:tuple(getattr(b,p)) for p in TRS} for b in obj.pose.bones},
         'modes':{b.name:b.rotation_mode for b in obj.pose.bones},
         'before':{b.name:tuple(tuple(r) for r in obj.matrix_world@b.matrix) for b in obj.pose.bones},
         'world':tuple(tuple(r) for r in obj.matrix_world),
         'key_selection':[(c.data_path,c.array_index,c.select,[(float(p.co.x),p.select_control_point,p.select_left_handle,p.select_right_handle) for p in c.keyframe_points]) for c in bag.fcurves],
         'range':(context.scene.frame_start,context.scene.frame_end),
         'frame':context.scene.frame_current_final,'pivot':context.scene.tool_settings.transform_pivot_point,
         'cursor':tuple(context.scene.cursor.location),'active':obj.data.bones.active.name if obj.data.bones.active else None}

def missing_ik(obj,names):
 needed=set()
 for b in obj.pose.bones:
  for c in b.constraints:
   if c.type=='IK' and not c.mute and c.influence>0:
    # Include IKs whose chain intersects the selected hierarchy.
    chain=[b]+list(b.parent_recursive[:max(0,c.chain_count-1)]) if c.chain_count else [b]+list(b.parent_recursive)
    if not any(p.name in names for p in chain): continue
    for target,sub in ((c.target,c.subtarget),(c.pole_target,c.pole_subtarget)):
     if target==obj and sub and sub not in names: needed.add(sub)
 return sorted(needed)

def center(pose,names,pivot,active,cursor):
 if pivot=='CURSOR': return Vector(cursor)
 if pivot=='ACTIVE_ELEMENT' and active in pose: return pose[active].translation.copy()
 points=[pose[n].translation for n in names]
 if pivot=='BOUNDING_BOX_CENTER': return Vector(tuple((min(p[i] for p in points)+max(p[i] for p in points))/2 for i in range(3)))
 return sum(points,Vector())/len(points)

def native_deltas(request,obj):
 before={n:Matrix(m) for n,m in request['before'].items()}
 return {n:obj.matrix_world@obj.pose.bones[n].matrix@before[n].inverted_safe() for n in request.get('selected',request['times'])}

def steps(request,deltas,mode='LOCAL',root='',added=()):
 obj=bpy.data.objects.get(request['object']); action=bpy.data.actions.get(request['action'])
 if not obj or not action or not obj.animation_data or obj.animation_data.action!=action:
  raise ValueError('骨架或 Action 已切換，取消一起調整')
 if core.slot_for(action,obj).identifier!=request['slot']: raise ValueError('Action Slot 已切換')
 bag=bag_for(action,obj)
 times={n:set(fs) for n,fs in request['times'].items()}; all_times=set().union(*times.values())
 for n in added: times[n]=set(all_times)
 if mode=='KEEP_PATH' and root not in obj.pose.bones: raise ValueError('請指定保留路徑的主控骨')
 if obj.animation_data.use_nla and any(not t.mute and any(not st.mute and st.action and any(st.frame_start<=f<=st.frame_end for f in all_times) for st in t.strips) for t in obj.animation_data.nla_tracks):
  raise ValueError('目前影格含啟用的 NLA 疊加，請先停用疊加再調整 Action')
 if any(c.data_path in TRS and has_values(c) for c in bag.fcurves):
  raise ValueError('骨架物件本身含變換動畫，請先以主控骨承載位移')
 if obj.parent and (obj.parent.animation_data or obj.parent.constraints):
  raise ValueError('骨架物件的父物件含動畫／約束，無法安全使用固定骨架空間')
 names=set(times); bones=sorted(obj.data.bones,key=lambda b:len(b.parent_recursive))
 curves={}; order=request['modes']; defaults=request['defaults']
 for c in bag.fcurves:
  m=PATTERN.match(c.data_path)
  if m:
   k=(json.loads(m[1]),m[2],c.array_index)
   if k in curves: raise ValueError('重複變換通道，無法安全調整')
   curves[k]=c
 dependencies=names|{p.name for n in names for p in obj.pose.bones[n].parent_recursive}
 for n in dependencies:
  if obj.animation_data.drivers and any(c.data_path.startswith(obj.pose.bones[n].path_from_id()) for c in obj.animation_data.drivers):
   raise ValueError(n+'：父子變換依賴 Driver，無法安全調整')
  for constraint in obj.pose.bones[n].constraints:
   if not constraint.mute and constraint.influence>0 and constraint.type!='IK':
    raise ValueError(n+'：父子變換依賴 '+constraint.type+' 約束，無法安全換算')
 for n in names:
  for c in core.target_curves(action,obj,[n]):
   if any(m.type!='CYCLES' for m in c.modifiers) or c.sampled_points or c.lock or c.mute: raise ValueError(n+'：含修飾器、取樣、鎖定或停用曲線，請先處理')
  if obj.animation_data.drivers and any(c.data_path.startswith(obj.pose.bones[n].path_from_id()) for c in obj.animation_data.drivers):
   raise ValueError(n+'：Driver 無法安全調整')
  for c in obj.pose.bones[n].constraints:
   if not c.mute and c.influence>0 and c.type!='IK': raise ValueError(n+'：'+c.type+' 約束無法安全換算，取消此次調整')
  rot={p for (bn,p,i),c in curves.items() if bn==n and p.startswith('rotation_') and has_values(c)}
  if len(rot)>1: raise ValueError(n+'：多種旋轉通道，請先統一旋轉座標')
  expected={'QUATERNION':'rotation_quaternion','AXIS_ANGLE':'rotation_axis_angle'}.get(order[n],'rotation_euler')
  if rot and expected not in rot: raise ValueError(n+'：旋轉模式與 Key 不一致，請先統一旋轉座標')
 # Native pose matrices provide a common world delta for whole-character operations.
 base_names=sorted(request['times'],key=lambda n:len(obj.data.bones[n].parent_recursive))
 ik_chain=set()
 for pb in obj.pose.bones:
  for constraint in pb.constraints:
   if constraint.type=='IK' and not constraint.mute and constraint.influence>0:
    chain=[pb]+list(pb.parent_recursive[:max(0,constraint.chain_count-1)]) if constraint.chain_count else [pb]+list(pb.parent_recursive)
    ik_chain.update(b.name for b in chain)
 trusted=[n for n in deltas if n in names and all(b.name not in ik_chain and not any(not c.mute and c.influence>0 for c in b.constraints) for b in [obj.pose.bones[n]]+list(obj.pose.bones[n].parent_recursive))]
 base=root if root in trusted else (trusted[0] if trusted else (root if root in deltas else base_names[0]))
 common=Matrix(deltas[base]); world=Matrix(request['world']); invworld=world.inverted_safe()
 before={n:Matrix(m) for n,m in request['before'].items()}
 p0=center(before,request.get('selected',request['times']),request['pivot'],request['active'],request['cursor'])
 plans={}; candidates={}; changed=set(); previous={}; total=len(all_times)*len(bones)+len(all_times)*len(names); done=0
 def component(n,p,f):
  return [curves[n,p,i].evaluate(f) if (n,p,i) in curves and not curves[n,p,i].mute and has_values(curves[n,p,i]) else v for i,v in enumerate(defaults[n][p])]
 for frame in sorted(all_times):
  pose={}
  for b in bones:
   n=b.name; rm=order[n]; loc=Vector(component(n,'location',frame)); scale=Vector(component(n,'scale',frame))
   if rm=='QUATERNION':
    q=Quaternion(component(n,'rotation_quaternion',frame))
    if q.magnitude<1e-8: q=Quaternion()
    q.normalize()
   elif rm=='AXIS_ANGLE':
    aa=component(n,'rotation_axis_angle',frame); axis=Vector(aa[1:]); q=Quaternion(axis.normalized() if axis.length else Vector((0,1,0)),aa[0])
   else: q=Euler(component(n,'rotation_euler',frame),rm).to_quaternion()
   pose[n]=b.convert_local_to_pose(Matrix.LocRotScale(loc,q,scale),b.matrix_local,
      parent_matrix=pose[b.parent.name] if b.parent else Matrix.Identity(4),
      parent_matrix_local=b.parent.matrix_local if b.parent else Matrix.Identity(4))
   done+=1; yield done,total,'一起調整（換算骨架）'
  worldpose={n:world@m for n,m in pose.items()}; affected={n for n in names if frame in times[n]}
  pf=center(worldpose,request.get('selected',affected),request['pivot'],request['active'],request['cursor'])
  desired={}; desired_world={}
  for b in bones:
   n=b.name
   if n in affected:
    d=Matrix(deltas.get(n,common)) if mode=='LOCAL' else common.copy()
    linear=d.to_3x3().to_4x4()
    if mode=='KEEP_PATH':
     # Do not translate the reference trajectory when adjusting facing.
     pivot=worldpose[root].translation
     shift=d.translation-(p0-d.to_3x3()@p0)
     d=Matrix.Translation(shift)@Matrix.Translation(pivot)@linear@Matrix.Translation(-pivot)
    elif mode=='LOCAL':
     oldpivot=before[n].translation if request['pivot']=='INDIVIDUAL_ORIGINS' else p0
     newpivot=worldpose[n].translation if request['pivot']=='INDIVIDUAL_ORIGINS' else pf
     shift=d.translation-(oldpivot-d.to_3x3()@oldpivot)
     d=Matrix.Translation(shift)@Matrix.Translation(newpivot)@linear@Matrix.Translation(-newpivot)
    desired[n]=invworld@d@worldpose[n]
   else:
    # Unselected children inherit their transformed parent, without extra local keys.
    basis=b.convert_local_to_pose(pose[n],b.matrix_local,
       parent_matrix=pose[b.parent.name] if b.parent else Matrix.Identity(4),
       parent_matrix_local=b.parent.matrix_local if b.parent else Matrix.Identity(4),invert=True)
    desired[n]=b.convert_local_to_pose(basis,b.matrix_local,
       parent_matrix=desired[b.parent.name] if b.parent else Matrix.Identity(4),
       parent_matrix_local=b.parent.matrix_local if b.parent else Matrix.Identity(4))
   if n not in affected: continue
   basis=b.convert_local_to_pose(desired[n],b.matrix_local,
      parent_matrix=desired[b.parent.name] if b.parent else Matrix.Identity(4),
      parent_matrix_local=b.parent.matrix_local if b.parent else Matrix.Identity(4),invert=True)
   loc,q,scale=basis.decompose()
   if max(abs(basis[i][j]-Matrix.LocRotScale(loc,q,scale)[i][j]) for i in range(4) for j in range(4))>1e-4:
    raise ValueError(n+'：變換含剪切，無法以位置／旋轉／縮放 Key 表達')
   rm=order[n]
   if rm=='QUATERNION':
    oldq=Quaternion(component(n,'rotation_quaternion',frame))
    if q.dot(previous.get(n,oldq))<0: q.negate()
    values={'rotation_quaternion':tuple(q)}; previous[n]=q.copy()
   elif rm=='AXIS_ANGLE':
    axis,angle=q.to_axis_angle(); original=component(n,'rotation_axis_angle',frame)
    if axis.dot(Vector(original[1:]))<0: axis=-axis; angle=-angle
    angle+=round((original[0]-angle)/(2*math.pi))*2*math.pi
    values={'rotation_axis_angle':(angle,*axis)}
   else:
    e=q.to_euler(rm,previous.get(n,Euler(component(n,'rotation_euler',frame),rm)))
    values={'rotation_euler':tuple(e)}; previous[n]=e.copy()
   values.update(location=tuple(loc),scale=tuple(scale))
   for prop,vs in values.items():
    old=component(n,prop,frame)
    for i,v in enumerate(vs):
     if not math.isfinite(v): raise ValueError('變換產生非有限數值')
     key=(n,prop,i); candidates.setdefault(key,{})[frame]=v
     if abs(v-old[i])>1e-6: changed.add(key)
   done+=1; yield done,total,'一起調整（計算選取 Key）'
 # The caller commits only after all calculations succeed.
 return {key:candidates[key] for key in changed}

def commit_steps(request,plans):
 obj=bpy.data.objects[request['object']]; action=bpy.data.actions[request['action']]; bag=bag_for(action,obj)
 backups=[]; created=[]; groups=[]; count=0; done=0; total=sum(len(v) for v in plans.values()); success=False
 try:
  for (n,prop,i),values in plans.items():
   path=obj.pose.bones[n].path_from_id(prop); c=bag.fcurves.find(path,index=i)
   if c is None:
    c=bag.fcurves.new(path,index=i); created.append(c)
    group=bag.groups.get(n)
    if group is None: group=bag.groups.new(n); groups.append(group.name)
    c.group=group
   else: backups.append((c,core.snapshot(c)))
   indices={float(p.co.x):j for j,p in enumerate(c.keyframe_points)}
   missing=[]
   for frame,value in values.items():
    if frame in indices:
     point=c.keyframe_points[indices[frame]]
     delta=value-point.co.y; point.co.y=value
     point.handle_left.y+=delta; point.handle_right.y+=delta
    else: missing.append((frame,value))
    done+=1
    if done%128==0: yield done,total,'一起調整（寫入 Key）'
   offset=len(c.keyframe_points); c.keyframe_points.add(len(missing))
   for j,(frame,value) in enumerate(missing):
    point=c.keyframe_points[offset+j]; point.co=(frame,value)
    point.interpolation='BEZIER'; point.handle_left_type=point.handle_right_type='AUTO_CLAMPED'
    point.select_control_point=True; count+=1
    if j%128==127: yield done,total,'一起調整（補同影格 Key）'
   c.update()
   yield done,total,'一起調整（更新曲線）'
  action.update_tag(); obj.update_tag(refresh={'TIME'}); success=True
  return count
 finally:
  if not success:
   for c,points in backups: core.write_points(c,points)
   for c in created: bag.fcurves.remove(c)
   for name in groups:
    group=bag.groups.get(name)
    if group: bag.groups.remove(group)
   action.update_tag(); obj.update_tag(refresh={'TIME'})

def commit(request,plans):
 g=commit_steps(request,plans)
 while True:
  try: next(g)
  except StopIteration as end: return end.value
