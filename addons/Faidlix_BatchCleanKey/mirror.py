"""Rest-aware armature-space reflection, staged on a native Action copy."""
import math
import json
import re
import bpy
from mathutils import Matrix, Vector, Euler, Quaternion
from . import core

TRS={'location','rotation_euler','rotation_quaternion','rotation_axis_angle','scale'}


def reverse_steps(context,obj,source,mode='COPY'):
    """Reverse one rig's slot on a native copy, preserving other slots."""
    slot=core.slot_for(source,obj) if source and obj else None
    bags=[s.channelbag(slot) for l in source.layers for s in l.strips
          if slot and s.type=='KEYFRAME' and s.channelbag(slot)] if source else []
    if not obj or not obj.is_editable or len(bags)!=1:
        raise ValueError('時間翻轉需要明確的單一骨架 Slot／動畫層')
    curves=[c for c in bags[0].fcurves if c.keyframe_points or c.sampled_points]
    times=[float(p.co.x) for c in curves for pts in (c.keyframe_points,c.sampled_points) for p in pts]
    if not times: raise ValueError('Action 沒有可翻轉的 Key')
    pivot=min(times)+max(times); copied=None
    total=max(1,sum(len(c.keyframe_points)+len(c.sampled_points) for c in curves)); done=0
    try:
        copied=source.copy(); copied.name='__BCK_Reverse__'+source.name
        bag=next(s.channelbag(core.slot_for(copied,obj)) for l in copied.layers for s in l.strips if s.type=='KEYFRAME' and s.channelbag(core.slot_for(copied,obj)))
        for c in list(bag.fcurves):
            if not c.keyframe_points and not c.sampled_points: continue
            bake=bool(c.sampled_points or any(m.type!='CYCLES' for m in c.modifiers))
            if bake:
                frames=sorted({float(p.co.x) for pts in (c.keyframe_points,c.sampled_points) for p in pts})
                values=[(pivot-f,c.evaluate(f)) for f in frames]
                path,index,group,lock,mute,extrap=c.data_path,c.array_index,c.group,c.lock,c.mute,c.extrapolation
                bag.fcurves.remove(c); c=bag.fcurves.new(path,index=index)
                c.group,c.lock,c.mute,c.extrapolation=group,lock,mute,extrap
                c.keyframe_points.add(len(values))
                for p,value in zip(c.keyframe_points,sorted(values)):
                    p.co=value; p.interpolation='BEZIER'; p.handle_left_type=p.handle_right_type='AUTO_CLAMPED'
                    done+=1
                    if done%128==0: yield done,total,source.name+'（時間倒播）'
                c.update()
            else:
                before=core.snapshot(c); points=[]
                for j in range(len(before)-1,-1,-1):
                    original=before[j]; p=dict(original)
                    p['co']=(pivot-original['co'][0],original['co'][1])
                    for left,right in [('handle_left','handle_right'),('handle_left_type','handle_right_type'),('select_left_handle','select_right_handle')]:
                        p[left],p[right]=original[right],original[left]
                    for side in ('handle_left','handle_right'):
                        p[side]=(pivot-p[side][0],p[side][1])
                    segment=before[max(0,j-1)]
                    for key in ('interpolation','easing','back','amplitude','period'):
                        if key in segment: p[key]=segment[key]
                    p['easing']={'EASE_IN':'EASE_OUT','EASE_OUT':'EASE_IN'}.get(p['easing'],p['easing'])
                    points.append(p)
                for _ in core.write_points_steps(c,points):
                    yield done,total,source.name+'（時間倒播）'
                for m in c.modifiers:
                    m.mode_before,m.mode_after=m.mode_after,m.mode_before
                    m.cycles_before,m.cycles_after=m.cycles_after,m.cycles_before
                done+=len(points)
            yield done,total,source.name+'（時間倒播）'
        if mode=='COPY': copied.name=source.name+'_Reversed'; copied.use_fake_user=True
        else:
            name=source.name; source.user_remap(copied); bpy.data.actions.remove(source); copied.name=name
        core.assign_action(context,obj,copied); core.sync_scene_range(context.scene,copied,obj)
        result=copied; copied=None
        return {'flip_action':result.name}
    finally:
        if copied: bpy.data.actions.remove(copied)


def steps(context,obj,source,mode='COPY',step=1,keyed_only=False):
    if not source or not obj or not obj.is_editable or (not keyed_only and (step<.01 or not math.isfinite(step))):
        raise ValueError('骨架、Action 或取樣間隔無效')
    slot=core.slot_for(source,obj)
    bags=[s.channelbag(slot) for l in source.layers for s in l.strips
          if slot and s.type=='KEYFRAME' and s.channelbag(slot)]
    if len(bags)!=1: raise ValueError('翻轉需要明確的單一骨架 Slot／動畫層')
    curves=list(bags[0].fcurves)
    keyed={}; other=[]
    for c in curves:
        m=re.match(r'^pose\.bones\[("(?:\\.|[^"\\])*")\](.*)$',c.data_path)
        if not m: continue
        name,suffix=json.loads(m[1]),m[2]
        if name not in obj.pose.bones: continue
        if suffix[1:] in TRS:
            key=(name,suffix[1:],c.array_index)
            if key in keyed: raise ValueError(name+'：重複變換通道，無法確定有效曲線')
            keyed[key]=c
        else: other.append((c,name,suffix))
    source_times={key:sorted({float(p.co.x) for pts in (c.keyframe_points,c.sampled_points) for p in pts})
                  for key,c in keyed.items()}
    frame_curves=keyed.values() if keyed_only else curves
    frames={float(p.co.x) for c in frame_curves for pts in (c.keyframe_points,c.sampled_points) for p in pts}
    if not frames: raise ValueError('Action 沒有可翻轉的 Key')
    start,end=min(frames),max(frames)
    if not keyed_only:
        count=math.ceil((end-start)/step)
        if count>200000: raise ValueError('取樣過多，請增加間隔')
        frames.update(start+i*step for i in range(count) if start+i*step<end)
    frames=sorted(frames)
    bones=sorted(obj.data.bones,key=lambda b:len(b.parent_recursive))
    pairs={b.name:bpy.utils.flip_name(b.name) for b in bones
           if bpy.utils.flip_name(b.name) in obj.data.bones}
    active={name for name,prop,index in keyed if core.rotation_has_data(keyed[name,prop,index])}
    keyed_mask={(pairs[n],p,i) for (n,p,i),c in keyed.items()
                if n in pairs and (bool(source_times[n,p,i]) if keyed_only else core.rotation_has_data(c))}
    output_times={(pairs[n],p,i):times for (n,p,i),times in source_times.items() if n in pairs and times}
    output_props={n:{p for d,p,i in keyed_mask if d==n} for n in pairs}
    affected={n for n,p,i in keyed_mask} if keyed_only else (set(pairs) if any(n in pairs for n in active) else set())
    if not affected: raise ValueError('沒有可配對的骨骼變換 Key')
    modes={}
    for b in bones:
        props={p for n,p,i in keyed if n==b.name and core.rotation_has_data(keyed[n,p,i])}
        rotprops=props & {'rotation_quaternion','rotation_euler','rotation_axis_angle'}
        current=obj.pose.bones[b.name].rotation_mode
        preferred={'QUATERNION':'rotation_quaternion','AXIS_ANGLE':'rotation_axis_angle'}.get(current,'rotation_euler')
        prop=preferred if preferred in rotprops else next(iter(rotprops),preferred)
        modes[b.name]='QUATERNION' if prop=='rotation_quaternion' else 'AXIS_ANGLE' if prop=='rotation_axis_angle' else (current if current not in {'QUATERNION','AXIS_ANGLE'} else 'XYZ')
    reflect=Matrix.Diagonal((-1,1,1,1))
    corrections={n:obj.data.bones[n].matrix_local.inverted() @ reflect @ obj.data.bones[d].matrix_local for n,d in pairs.items()}
    values={n:[] for n in affected}; previous={}
    # Missing channels retain the rig's current values, rather than an identity pose.
    defaults={b.name:{p:tuple(getattr(b,p)) for p in TRS} for b in obj.pose.bones}
    total=len(frames)*len(bones)+(sum(len(times) for times in output_times.values()) if keyed_only else len(frames)*len(affected)*10); done=0
    def components(name,prop,defaults,frame):
        return [keyed[name,prop,i].evaluate(frame) if (name,prop,i) in keyed and not keyed[name,prop,i].mute and core.rotation_has_data(keyed[name,prop,i]) else v for i,v in enumerate(defaults)]
    copied=None
    try:
        for frame in frames:
            pose={}
            for b in bones:
                n=b.name; rm=modes[n]
                loc=Vector(components(n,'location',defaults[n]['location'],frame))
                scale=Vector(components(n,'scale',defaults[n]['scale'],frame))
                if rm=='QUATERNION':
                    q=Quaternion(components(n,'rotation_quaternion',defaults[n]['rotation_quaternion'],frame))
                    if q.magnitude<1e-8: q=Quaternion()
                    q.normalize()
                elif rm=='AXIS_ANGLE':
                    a=components(n,'rotation_axis_angle',defaults[n]['rotation_axis_angle'],frame)
                    axis=Vector(a[1:]); q=Quaternion(axis.normalized() if axis.length else Vector((0,1,0)),a[0])
                else: q=Euler(components(n,'rotation_euler',defaults[n]['rotation_euler'],frame),rm).to_quaternion()
                pose[n]=b.convert_local_to_pose(Matrix.LocRotScale(loc,q,scale),b.matrix_local,
                    parent_matrix=pose[b.parent.name] if b.parent else Matrix.Identity(4),
                    parent_matrix_local=b.parent.matrix_local if b.parent else Matrix.Identity(4))
                done+=1
                yield done,total,source.name+'（骨架空間翻轉）'
            desired={d:reflect @ pose[n] @ corrections[n] for n,d in pairs.items()}
            desired.update({b.name:pose[b.name] for b in bones if b.name not in desired})
            for n in affected:
                b=obj.data.bones[n]
                basis=b.convert_local_to_pose(desired[n],b.matrix_local,
                    parent_matrix=desired[b.parent.name] if b.parent else Matrix.Identity(4),
                    parent_matrix_local=b.parent.matrix_local if b.parent else Matrix.Identity(4),invert=True)
                loc,q,scale=basis.decompose(); rm=modes[pairs[n]]
                # Pose channels cannot express shear; never silently distort it.
                reconstructed=Matrix.LocRotScale(loc,q,scale)
                if max(abs(basis[i][j]-reconstructed[i][j]) for i in range(4) for j in range(4))>1e-4:
                    raise ValueError(n+'：鏡像含無法以 TRS 表達的剪切，取消翻轉')
                if rm=='QUATERNION':
                    if n in previous and q.dot(previous[n])<0: q.negate()
                    rotation=q; prop='rotation_quaternion'
                elif rm=='AXIS_ANGLE':
                    axis,angle=q.to_axis_angle(); rotation=(angle,*axis); prop='rotation_axis_angle'
                else:
                    rotation=q.to_euler(rm,previous.get(n)) if n in previous else q.to_euler(rm)
                    prop='rotation_euler'
                if hasattr(rotation,'copy'): previous[n]=rotation.copy()
                sample={'location':tuple(loc),prop:tuple(rotation),'scale':tuple(scale)}
                if keyed_only:
                    # Legacy Actions may contain more than one rotation representation.
                    # Write every keyed representation without introducing unkeyed ones.
                    if 'rotation_quaternion' in output_props[n]:
                        sample['rotation_quaternion']=tuple(q)
                    if 'rotation_euler' in output_props[n]:
                        order=rm if rm not in {'QUATERNION','AXIS_ANGLE'} else 'XYZ'
                        sample['rotation_euler']=tuple(q.to_euler(order)) if prop!='rotation_euler' else tuple(rotation)
                    if 'rotation_axis_angle' in output_props[n]:
                        axis,angle=q.to_axis_angle(); sample['rotation_axis_angle']=(angle,*axis)
                if not all(math.isfinite(v) for vs in sample.values() for v in vs): raise ValueError('翻轉產生非有限數值')
                values[n].append(sample)
        copied=source.copy(); copied.name='__BCK_Mirror__'+source.name
        bag=next(s.channelbag(core.slot_for(copied,obj)) for l in copied.layers for s in l.strips if s.type=='KEYFRAME' and s.channelbag(core.slot_for(copied,obj)))
        # Pair custom properties without changing their values or curve metadata.
        for c in list(bag.fcurves):
            m=re.match(r'^pose\.bones\[("(?:\\.|[^"\\])*")\](.*)$',c.data_path)
            if not m: continue
            n,suffix=json.loads(m[1]),m[2]
            if n not in pairs: continue
            if suffix[1:] in TRS:
                if ((not keyed_only and n in affected) or
                    (keyed_only and ((n,suffix[1:],c.array_index) in keyed_mask or
                     bool(source_times.get((n,suffix[1:],c.array_index)))))):
                    bag.fcurves.remove(c)
            elif not keyed_only or core.rotation_has_data(c):
                c.data_path=obj.pose.bones[pairs[n]].path_from_id()+suffix
        orders={}
        frame_indices={frame:j for j,frame in enumerate(frames)}
        for n,samples in values.items():
            rm=modes[pairs[n]]
            if rm not in {'QUATERNION','AXIS_ANGLE'} and (not keyed_only or 'rotation_euler' in output_props[n]): orders[n]=rm
            for prop,vs in samples[0].items():
                for i in range(len(vs)):
                    if keyed_only and (n,prop,i) not in keyed_mask: continue
                    c=bag.fcurves.new(obj.pose.bones[n].path_from_id()+'.'+prop,index=i)
                    c.group=bag.groups.get(n) or bag.groups.new(n)
                    curve_frames=output_times[n,prop,i] if keyed_only else frames
                    c.keyframe_points.add(len(curve_frames))
                    for j,frame in enumerate(curve_frames):
                        sample=samples[frame_indices[frame]]
                        p=c.keyframe_points[j]; p.co=frame,sample[prop][i]; p.interpolation='BEZIER'
                        p.handle_left_type=p.handle_right_type='AUTO_CLAMPED'
                        done+=1
                        if j%128==0: yield done,total,source.name+'（寫入翻轉副本）'
                    c.update()
        copied['_bck_euler_orders']=orders
        if mode=='COPY':
            copied.name=source.name+'_Flipped'; copied.use_fake_user=True
        else:
            name=source.name; source.user_remap(copied); bpy.data.actions.remove(source); copied.name=name
        core.assign_action(context,obj,copied)
        core.sync_scene_range(context.scene,copied,obj)
        result=copied; copied=None
        return {'flip_action':result.name}
    finally:
        if copied: bpy.data.actions.remove(copied)
