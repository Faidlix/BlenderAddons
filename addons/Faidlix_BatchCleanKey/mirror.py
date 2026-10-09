"""Rest-aware armature-space reflection, staged on a native Action copy."""
import math
import json
import re
import bpy
from mathutils import Matrix, Vector, Euler, Quaternion
from . import core

TRS={'location','rotation_euler','rotation_quaternion','rotation_axis_angle','scale'}


def steps(context,obj,source,mode='COPY',step=1):
    if not source or not obj or not obj.is_editable or step<.01 or not math.isfinite(step):
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
    frames={float(p.co.x) for c in curves for pts in (c.keyframe_points,c.sampled_points) for p in pts}
    if not frames: raise ValueError('Action 沒有可翻轉的 Key')
    start,end=min(frames),max(frames)
    count=math.ceil((end-start)/step)
    if count>200000: raise ValueError('取樣過多，請增加間隔')
    frames.update(start+i*step for i in range(count) if start+i*step<end)
    frames=sorted(frames)
    bones=sorted(obj.data.bones,key=lambda b:len(b.parent_recursive))
    pairs={b.name:bpy.utils.flip_name(b.name) for b in bones
           if bpy.utils.flip_name(b.name) in obj.data.bones}
    active={name for name,prop,index in keyed if core.rotation_has_data(keyed[name,prop,index])}
    affected=set(pairs) if any(n in pairs for n in active) else set()
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
    total=len(frames)*len(bones)+len(frames)*len(affected)*10; done=0
    def components(name,prop,defaults,frame):
        return [keyed[name,prop,i].evaluate(frame) if (name,prop,i) in keyed and not keyed[name,prop,i].mute and core.rotation_has_data(keyed[name,prop,i]) else v for i,v in enumerate(defaults)]
    copied=None
    try:
        for frame in frames:
            pose={}
            for b in bones:
                n=b.name; rm=modes[n]
                loc=Vector(components(n,'location',(0,0,0),frame))
                scale=Vector(components(n,'scale',(1,1,1),frame))
                if rm=='QUATERNION':
                    q=Quaternion(components(n,'rotation_quaternion',(1,0,0,0),frame))
                    if q.magnitude<1e-8: q=Quaternion()
                    q.normalize()
                elif rm=='AXIS_ANGLE':
                    a=components(n,'rotation_axis_angle',(0,0,1,0),frame)
                    axis=Vector(a[1:]); q=Quaternion(axis.normalized() if axis.length else Vector((0,1,0)),a[0])
                else: q=Euler(components(n,'rotation_euler',(0,0,0),frame),rm).to_quaternion()
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
            if suffix[1:] in TRS and n in affected: bag.fcurves.remove(c)
            elif suffix[1:] not in TRS:
                c.data_path=obj.pose.bones[pairs[n]].path_from_id()+suffix
        orders={}
        for n,samples in values.items():
            rm=modes[pairs[n]]
            if rm not in {'QUATERNION','AXIS_ANGLE'}: orders[n]=rm
            for prop,vs in samples[0].items():
                for i in range(len(vs)):
                    c=bag.fcurves.new(obj.pose.bones[n].path_from_id()+'.'+prop,index=i)
                    c.group=bag.groups.get(n) or bag.groups.new(n)
                    c.keyframe_points.add(len(frames))
                    for j,(frame,sample) in enumerate(zip(frames,samples)):
                        p=c.keyframe_points[j]; p.co=frame,sample[prop][i]; p.interpolation='LINEAR'
                        done+=1
                        if j%128==0: yield done,total,source.name+'（寫入翻轉副本）'
                    c.update()
        copied['_bck_euler_orders']=orders
        if mode=='COPY':
            copied.name=source.name+'_Flipped'; copied.use_fake_user=True
        else:
            name=source.name; source.user_remap(copied); bpy.data.actions.remove(source); copied.name=name
        core.assign_action(context,obj,copied)
        core.sync_scene_range(context.scene,copied)
        result=copied; copied=None
        return {'flip_action':result.name}
    finally:
        if copied: bpy.data.actions.remove(copied)
