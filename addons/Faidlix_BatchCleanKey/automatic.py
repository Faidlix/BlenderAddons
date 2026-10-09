"""Confirmed rotation repair on native Action copies; atomic user remapping."""
import math
import bpy
from . import core


def inspect(obj, names, actions, target):
    actions = list(dict.fromkeys(actions + core.rotation_dependencies(obj,names,actions,target)))
    issues, failures = [], []
    source = 'rotation_quaternion' if target=='XYZ' else 'rotation_euler'
    dest = 'rotation_euler' if target=='XYZ' else 'rotation_quaternion'
    source_paths={obj.pose.bones[n].path_from_id()+'.'+source for n in names}
    actions=[a for a in actions if any(c.data_path in source_paths and core.rotation_has_data(c) for c in core.action_curves(a))]
    if not actions: failures.append('所選骨骼沒有可轉換的來源旋轉 Key')
    present_paths={c.data_path for a in actions for c in core.target_curves(a,obj,names) if core.rotation_has_data(c)}
    converted_names={n for n in names if obj.pose.bones[n].path_from_id()+'.'+source in present_paths}
    for bone in converted_names:
        if obj.pose.bones[bone].rotation_mode not in {'XYZ','QUATERNION'}:
            failures.append(bone+'：目前旋轉模式不是 XYZ／Quaternion')
    if not obj.is_editable:
        failures.append('骨架為唯讀，無法切換旋轉模式')
    paths={obj.pose.bones[n].path_from_id()+'.'+p for n in names for p in (source,dest)}
    if obj.animation_data and any(c.data_path in paths for c in obj.animation_data.drivers):
        failures.append('旋轉 Driver 無法以單純 Action 曲線安全換算')
    for action in actions:
        slot=core.slot_for(action,obj)
        bags=[s.channelbag(slot) for l in action.layers for s in l.strips
              if slot and s.type=='KEYFRAME' and s.channelbag(slot)]
        if not slot or len(bags)!=1:
            failures.append(action.name+'：Slot 不明確或多層動畫無法安全合併')
            continue
        curves=core.target_curves(action,obj,names)
        for n in names:
            prefix=obj.pose.bones[n].path_from_id()+'.'
            channels=[c for c in curves if c.data_path==prefix+source]
            if not any(core.rotation_has_data(c) for c in channels): continue
            count=4 if target=='XYZ' else 3
            if len({c.array_index for c in channels})!=len(channels):
                failures.append(action.name+'/'+n+'：來源通道重複，無法確定有效曲線')
            labels=[]
            if len(channels)!=count or any(not core.rotation_has_data(c) for c in channels): labels.append('補齊缺少分量')
            if any(c.lock for c in channels): labels.append('解除鎖定')
            if any(c.mute for c in channels): labels.append('啟用停用曲線')
            if any(c.modifiers for c in channels): labels.append('烘焙修飾器（含 Cycles）')
            if any(c.sampled_points for c in channels): labels.append('烘焙取樣曲線')
            if any(c.extrapolation!='CONSTANT' for c in channels): labels.append('烘焙動作範圍內外插')
            if any(c.data_path==prefix+dest for c in curves): labels.append('取代重複目標通道')
            if labels: issues.append(action.name+'/'+n+'：'+'、'.join(labels))
    return actions,issues,failures


def rotation_steps(context,obj,names,actions,target,step=1):
    from mathutils import Quaternion
    actions,issues,failures=inspect(obj,names,list(actions),target)
    if failures: raise ValueError('；'.join(failures))
    if not math.isfinite(step) or step<.01-1e-8: raise ValueError('取樣間隔無效')
    step=max(.01,step)
    source='rotation_quaternion' if target=='XYZ' else 'rotation_euler'
    dest='rotation_euler' if target=='XYZ' else 'rotation_quaternion'
    size=4 if target=='XYZ' else 3
    copies,remapped=[],[]
    pose={n:(obj.pose.bones[n].rotation_mode,tuple(obj.pose.bones[n].rotation_euler),tuple(obj.pose.bones[n].rotation_quaternion)) for n in names}
    worker=None
    try:
        jobs=[]
        for original in actions:
            copied=original.copy(); copied.name='__BCK_Auto__'+original.name
            copies.append((original,copied,original.name))
            yield 0,1,original.name+'（準備副本）'
            slot=core.slot_for(copied,obj)
            bag=next(s.channelbag(slot) for l in copied.layers for s in l.strips if s.type=='KEYFRAME' and s.channelbag(slot))
            bounds=core.actual_range(original)
            for name in names:
                prefix=obj.pose.bones[name].path_from_id()+'.'
                channels=[c for c in bag.fcurves if c.data_path==prefix+source]
                if not any(core.rotation_has_data(c) for c in channels): continue
                times={float(p.co.x) for c in channels for points in (c.keyframe_points,c.sampled_points) for p in points}
                if bounds: times.update(bounds)
                if not times: times.add(float(context.scene.frame_current))
                first,last=min(times),max(times)
                count=math.ceil((last-first)/step)
                if count>200000: raise ValueError('取樣過多，請增加間隔')
                times.update(first+i*step for i in range(count) if first+i*step<last)
                defaults=tuple(obj.pose.bones[name].rotation_quaternion if target=='XYZ' else obj.pose.bones[name].rotation_euler)
                jobs.append((copied,bag,prefix,channels,sorted(times),defaults))
                yield 0,1,original.name+'（準備取樣）'
        total=sum(len(j[4])*2 for j in jobs); done=0
        for copied,bag,prefix,channels,times,defaults in jobs:
            values=[]
            for frame in times:
                v=[next((c.evaluate(frame) for c in channels if c.array_index==i and core.rotation_has_data(c)),defaults[i]) for i in range(size)]
                if not all(math.isfinite(value) for value in v): raise ValueError('來源旋轉含非有限數值，取消處理')
                if target=='XYZ' and Quaternion(v).magnitude<1e-8: v=[1,0,0,0]
                values.append(v); done+=1
                yield done,total,copied.name.replace('__BCK_Auto__','')+'（自動烘焙）'
            group_name=channels[0].group.name if channels and channels[0].group else None
            for c in list(bag.fcurves):
                if c.data_path in {prefix+source,prefix+dest}: bag.fcurves.remove(c)
            for i in range(size):
                c=bag.fcurves.new(prefix+source,index=i)
                if group_name: c.group=bag.groups.get(group_name) or bag.groups.new(group_name)
                c.keyframe_points.add(len(times))
                for j,(frame,v) in enumerate(zip(times,values)):
                    p=c.keyframe_points[j]; p.co=frame,v[i]; p.interpolation='LINEAR'
                    if j%128==0: yield done,total,copied.name+'（準備轉換）'
                c.update()
            done+=len(times)
        worker=core.rotation_steps(context,obj,names,[c for _,c,_ in copies],target,step,check_dependencies=False)
        while True:
            try:
                d,t,label=next(worker)
                yield total+d,total+t,label.replace('__BCK_Auto__','')
            except StopIteration as finished:
                result=finished.value; worker=None; break
        # No yields after remapping starts: this final commit is one event turn.
        for original,copied,name in copies:
            original.user_remap(copied); remapped.append((original,copied))
        context.scene.frame_set(context.scene.frame_current,subframe=context.scene.frame_subframe)
        for original,copied,name in copies:
            bpy.data.actions.remove(original)
            copied.name=name
        copies.clear()
        result['automatic']=True
        return result
    except BaseException:
        if worker: worker.close()
        for original,copied in reversed(remapped): copied.user_remap(original)
        for n,(mode,euler,quat) in pose.items():
            b=obj.pose.bones[n]; b.rotation_mode=mode; b.rotation_euler=euler; b.rotation_quaternion=quat
        for original,copied,name in copies: bpy.data.actions.remove(copied)
        context.scene.frame_set(context.scene.frame_current,subframe=context.scene.frame_subframe)
        raise
