"""Native curve operations staged in an isolated temporary scene before commit."""
import bpy
import json
import re
BONE_PREFIX = re.compile(r'^(pose\.bones\["(?:\\.|[^"\\])*"\])(?=[.\[])')


def reset_pose(obj, names):
    for name in names:
        bone = obj.pose.bones[name]
        bone.location = (0, 0, 0)
        bone.rotation_euler = (0, 0, 0)
        bone.rotation_quaternion = (1, 0, 0, 0)
        bone.rotation_axis_angle = (0, 0, 1, 0)
        bone.scale = (1, 1, 1)
    obj.update_tag()


def selected_bones(context):
    obj = context.object
    if not obj or obj.type != 'ARMATURE' or obj.mode != 'POSE':
        return []
    return [bone.name for bone in (context.selected_pose_bones or [])]


def slot_for(action, obj):
    """Never silently edit another object's slot in a multi-slot Action."""
    ad = obj.animation_data
    if ad and ad.action == action and ad.action_slot:
        return ad.action_slot
    named=[s for s in action.slots if s.identifier=='OB'+obj.name]
    if len(named)==1:
        return named[0]
    if ad and ad.action_slot:
        match = [s for s in action.slots if s.identifier == ad.action_slot.identifier]
        if len(match) == 1:
            return match[0]
    used = [s for s in action.slots if obj in s.users()]
    if len(used) == 1:
        return used[0]
    compatible = [s for s in action.slots if s.target_id_type == 'OBJECT']
    return compatible[0] if len(compatible) == 1 else None


def target_curves(action, obj, names):
    prefixes = {'pose.bones["' + bpy.utils.escape_identifier(n) + '"]' for n in names}
    slot = slot_for(action, obj)
    if not slot:
        return []
    curves = []
    for layer in action.layers:
        for strip in layer.strips:
            if strip.type != 'KEYFRAME':
                continue
            bag = strip.channelbag(slot)
            if bag:
                curves.extend(f for f in bag.fcurves
                              if (match := BONE_PREFIX.match(f.data_path)) and match[1] in prefixes)
    return curves


def action_curves(action):
    for layer in action.layers:
        for strip in layer.strips:
            if strip.type == 'KEYFRAME':
                for bag in strip.channelbags:
                    yield from bag.fcurves


def actual_range(action):
    frames = [p.co.x for c in action_curves(action)
              for points in (c.keyframe_points, c.sampled_points) for p in points]
    return (min(frames), max(frames)) if frames else None


def pad_bone_bounds(action,obj):
    """Pad existing bone curves only, in this rig's slot; never create new channels."""
    if not action.is_editable: return 0
    curves=target_curves(action,obj,[b.name for b in obj.pose.bones])
    times=[float(p.co.x) for c in curves for pts in (c.keyframe_points,c.sampled_points) for p in pts]
    if not times: return 0
    start,end=min(times),max(times); added=0
    for c in curves:
        if not c.keyframe_points or c.sampled_points or c.modifiers: continue
        existing={float(p.co.x) for p in c.keyframe_points}
        pending=[(f,c.evaluate(f)) for f in {start,end} if f not in existing]
        for frame,value in pending:
            p=c.keyframe_points.insert(frame,value,options={'FAST'})
            p.interpolation='BEZIER'; p.handle_left_type=p.handle_right_type='AUTO_CLAMPED'; added+=1
        if pending: c.update()
    return added


def sync_ranges(actions):
    changed = skipped = 0
    for action in actions:
        bounds = actual_range(action)
        if bounds is None or not action.is_editable:
            skipped += 1
            continue
        action.use_frame_range = True
        # Expand first so Blender's coupled start/end setters cannot clamp bounds.
        action.frame_end = max(action.frame_end, bounds[1])
        action.frame_start = bounds[0]
        action.frame_end = bounds[1]
        changed += 1
    return changed, skipped


def sync_action_modes(obj, action):
    """Select each bone's keyed representation without rewriting other Actions."""
    if not action or obj.type != 'ARMATURE' or not obj.is_editable:
        return False
    keyed = {}
    for c in target_curves(action,obj,[b.name for b in obj.pose.bones]):
        if not rotation_has_data(c):
            continue
        m=re.match(r'^pose\.bones\[("(?:\\.|[^"\\])*")\]\.rotation_(quaternion|euler|axis_angle)$',c.data_path)
        if m:
            keyed.setdefault(json.loads(m[1]),set()).add(m[2])
    changed=False
    for name,kinds in keyed.items():
        if len(kinds)!=1:
            continue
        bone=obj.pose.bones[name]
        kind=next(iter(kinds))
        mode={'quaternion':'QUATERNION','axis_angle':'AXIS_ANGLE'}.get(kind)
        if mode is None:
            mode=action.get('_bck_euler_orders',{}).get(name,'XYZ')
        if bone.rotation_mode!=mode:
            bone.rotation_mode=mode
            changed=True
    return changed


def assign_action(context, obj, action):
    if not obj.is_editable:
        raise ValueError('目前骨架為唯讀')
    slot = slot_for(action, obj)
    if not action.slots and action.is_editable:
        slot = action.slots.new('OBJECT', obj.name)
    if not slot:
        raise ValueError('Action 的 Slot 無法明確對應目前骨架')
    ad = obj.animation_data_create()
    ad.action = action
    ad.action_slot = slot
    sync_action_modes(obj, action)
    obj.update_tag(refresh={'TIME'})
    context.scene.frame_set(context.scene.frame_current, subframe=context.scene.frame_subframe)


def sync_scene_range(scene, action):
    import math
    bounds = actual_range(action)
    if bounds is not None and action.is_editable:
        sync_ranges([action])
    if bounds is None:
        bounds = (1, 1)
    start, end = math.floor(bounds[0]), math.ceil(bounds[1])
    scene.frame_end = max(scene.frame_end, end)
    scene.frame_start = start
    scene.frame_end = end


def loop_curves(action, obj):
    slot = slot_for(action, obj)
    if not action.is_editable or not slot:
        raise ValueError('Action 為唯讀或 Slot 不明確')
    bags = [strip.channelbag(slot) for layer in action.layers for strip in layer.strips
            if strip.type == 'KEYFRAME' and strip.channelbag(slot)]
    if len(bags) != 1:
        raise ValueError('多層 Action 請先烘焙')
    curves = [c for c in bags[0].fcurves if c.keyframe_points or c.sampled_points]
    if not curves:
        raise ValueError('Action 沒有 Key')
    for c in curves:
        reason = ('曲線已鎖定，請解鎖' if c.lock else '曲線已停用，請先確認是否啟用' if c.mute else
                  '含修飾器：' + ', '.join(m.type for m in c.modifiers) + '，請先烘焙' if c.modifiers else
                  '使用取樣曲線，請先轉為 Key' if c.sampled_points else '')
        if reason:
            raise ValueError(f'{action.name} / {c.data_path}[{c.array_index}]：{reason}')
    frames = [p.co.x for c in curves for p in c.keyframe_points]
    return curves, min(frames), max(frames)


def make_loop(action, obj, smooth=True):
    """Close every curve in the rig slot over their union range, atomically."""
    curves, start, end = loop_curves(action, obj)
    if end <= start:
        raise ValueError('循環至少需要兩個不同影格')
    plans, added = [], 0
    for curve in curves:
        before = snapshot(curve)
        points = [dict(p) for p in before]
        value = curve.evaluate(start)
        for frame in (start, end):
            if not any(p['co'][0] == frame for p in points):
                point = dict(before[0] if frame == start else before[-1])
                point['co'] = (frame, curve.evaluate(frame))
                point['handle_left'] = point['handle_right'] = point['co']
                points.append(point)
                added += 1
        points.sort(key=lambda p: p['co'][0])
        first, last = points[0], points[-1]
        slope = 0.0
        if smooth and before[0]['co'][0] == start and len(before) > 1:
            if first['interpolation'] == 'BEZIER':
                dx = first['handle_right'][0] - start
                slope = (first['handle_right'][1] - value) / dx if abs(dx) > 1e-6 else 0
            elif first['interpolation'] == 'LINEAR':
                slope = (before[1]['co'][1] - value) / (before[1]['co'][0] - start)
        for point in (first, last):
            point['co'] = (point['co'][0], value)
        if smooth:
            # Adjacent segment lengths avoid crossing a neighbouring control point.
            for point, span in ((first, points[1]['co'][0]-start),
                                (last, end-points[-2]['co'][0])):
                frame = point['co'][0]
                distance = span / 3
                point['handle_left_type'] = point['handle_right_type'] = 'FREE'
                point['handle_left'] = (frame-distance, value-slope*distance)
                point['handle_right'] = (frame+distance, value+slope*distance)
                point['interpolation'] = 'BEZIER'
            # The outgoing interpolation belongs to the penultimate point.
            if points[-2] is not first:
                points[-2]['interpolation'] = 'BEZIER'
        else:
            for point in (first, last):
                point['handle_left_type'] = point['handle_right_type'] = 'AUTO_CLAMPED'
        plans.append((curve, before, points))
    applied = []
    try:
        for curve, before, points in plans:
            applied.append((curve, before))
            write_points(curve, points)
    except Exception:
        for curve, before in applied:
            write_points(curve, before)
        raise
    action.update_tag()
    return len(curves), added, start, end


def rotation_has_data(curve):
    return bool(curve.keyframe_points or curve.sampled_points or curve.modifiers)


def loop_copy_steps(action, obj, smooth=True, step=1.0):
    """Bake evaluated curves to a cancellable, unlocked loop copy; preserve source."""
    import math
    slot = slot_for(action, obj)
    bags = [s.channelbag(slot) for l in action.layers for s in l.strips
            if s.type == 'KEYFRAME' and slot and s.channelbag(slot)]
    frames = [float(p.co.x) for bag in bags for c in bag.fcurves
              for points in (c.keyframe_points,c.sampled_points) for p in points]
    bounds = (min(frames),max(frames)) if frames else None
    if len(bags) != 1 or not bounds or bounds[1] <= bounds[0]:
        raise ValueError('循環副本需有可辨識 Slot、單層 Action 與兩個不同影格')
    if not math.isfinite(step) or step < .01-1e-8:
        raise ValueError('取樣間隔至少 0.01 影格')
    step = max(step,.01)
    start,end = bounds
    count = math.ceil((end-start)/step)
    if count > 200000:
        raise ValueError('循環取樣過多，請增加間隔')
    times = {start,end}
    times.update(start+i*step for i in range(count) if start+i*step<end)
    times.update(float(p.co.x) for c in bags[0].fcurves for p in c.keyframe_points)
    times = sorted(times)
    source_curves = [c for c in bags[0].fcurves if rotation_has_data(c)]
    total = len(times)*len(source_curves)*2
    if total > 4000000:
        raise ValueError('循環取樣過多，請增加間隔')
    copy = action.copy()
    copy.name = action.name+'_Loop'
    copy.use_fake_user = True
    try:
        copied_slot = slot_for(copy,obj)
        bag = next(s.channelbag(copied_slot) for l in copy.layers for s in l.strips
                   if s.type=='KEYFRAME' and s.channelbag(copied_slot))
        done = 0
        for curve in [c for c in bag.fcurves if rotation_has_data(c)]:
            values = []
            for frame in times:
                values.append(curve.evaluate(frame))
                done += 1
                yield done,total,copy.name
            for modifier in list(curve.modifiers):
                curve.modifiers.remove(modifier)
            if curve.sampled_points:
                curve.convert_to_keyframes(math.floor(start),math.ceil(end))
            curve.keyframe_points.clear()
            curve.keyframe_points.add(len(times))
            curve.lock = curve.mute = False
            for i,(frame,value) in enumerate(zip(times,values)):
                p=curve.keyframe_points[i]
                p.co=frame,value; p.interpolation='LINEAR'
                done += 1
                if i%128==0:
                    yield done,total,copy.name
            first,last=curve.keyframe_points[0],curve.keyframe_points[-1]
            last.co.y=first.co.y
            if smooth:
                slope=(values[1]-values[0])/(times[1]-times[0])
                for p,span in ((first,times[1]-start),(last,end-times[-2])):
                    d=span/3
                    p.handle_left_type=p.handle_right_type='FREE'
                    p.handle_left=(p.co.x-d,first.co.y-slope*d)
                    p.handle_right=(p.co.x+d,first.co.y+slope*d)
                    p.interpolation='BEZIER'
                curve.keyframe_points[-2].interpolation='BEZIER'
            curve.update()
            yield done,total,copy.name
        sync_ranges([copy])
        return copy
    except BaseException:
        bpy.data.actions.remove(copy)
        raise


def rotation_dependencies(obj, names, actions, target):
    source = 'rotation_quaternion' if target == 'XYZ' else 'rotation_euler'
    paths = {obj.pose.bones[n].path_from_id() + '.' + source for n in names}
    return [a for a in bpy.data.actions if a not in actions and
            any(c.data_path in paths and rotation_has_data(c) for c in target_curves(a, obj, names))]


def rotation_steps(context, obj, names, actions, target, step=1.0, check_dependencies=True, original_only=False):
    """Bake evaluated local rotation channels; stage before an atomic commit.

    Samples include original subframe keys. Between samples conversion is an
    approximation: use a smaller step for fast rotations or subframe rendering.
    """
    import math
    from mathutils import Euler, Quaternion
    if target not in {'XYZ', 'QUATERNION'} or not math.isfinite(step) or step < 0.01-1e-8:
        raise ValueError('旋轉模式或取樣間隔無效')
    step = max(step,.01)
    source = 'rotation_quaternion' if target == 'XYZ' else 'rotation_euler'
    dest = 'rotation_euler' if target == 'XYZ' else 'rotation_quaternion'
    size = 4 if target == 'XYZ' else 3
    names, actions = list(dict.fromkeys(names)), list(dict.fromkeys(actions))
    if not names or not actions or not obj.is_editable:
        raise ValueError('請選取可編輯的骨架、骨骼與 Action')
    paths = {n: obj.pose.bones[n].path_from_id() + '.' + source for n in names}
    for action in bpy.data.actions if check_dependencies else []:
        if action.slots and not slot_for(action, obj) and any(c.data_path in paths.values() and rotation_has_data(c) for c in action_curves(action)):
            raise ValueError(action.name + '：來源旋轉 Slot 不明確，請先整理 Slot')
    # Changing a pose bone's mode affects every Action, including NLA users.
    blockers = [a.name for a in rotation_dependencies(obj, names, actions, target)] if check_dependencies else []
    if blockers:
        raise ValueError('請一併勾選仍有來源旋轉 Key 的 Action：' + ', '.join(blockers[:8]))
    if obj.animation_data and any(d.data_path in paths.values() or
            d.data_path in {obj.pose.bones[n].path_from_id() + '.' + dest for n in names}
            for d in obj.animation_data.drivers):
        raise ValueError('所選骨骼有旋轉 Driver，請先烘焙')
    jobs = []
    for action in actions:
        curves = target_curves(action, obj, names)
        if not action.is_editable or (action.slots and not slot_for(action, obj)):
            raise ValueError(action.name + '：唯讀或 Slot 不明確')
        bags = [strip.channelbag(slot_for(action, obj)) for layer in action.layers
                for strip in layer.strips if strip.type == 'KEYFRAME' and slot_for(action, obj)]
        for name, path in paths.items():
            channels = [c for c in curves if c.data_path == path]
            if not any(rotation_has_data(c) for c in channels):
                continue
            if len(bags) != 1 or not bags[0]:
                raise ValueError(action.name + '：多層旋轉需先烘焙')
            if len(channels) != size or {c.array_index for c in channels} != set(range(size)):
                raise ValueError(action.name + ' / ' + name + '：旋轉通道不完整，請先補齊 Key')
            for c in channels:
                reason = ('曲線已鎖定，請解鎖' if c.lock else
                          '曲線已停用，請先確認是否啟用' if c.mute else
                          '含修飾器：' + ', '.join(m.type for m in c.modifiers) + '，請先烘焙' if c.modifiers else
                          '使用取樣曲線，請先轉為 Key' if c.sampled_points else
                          '分量沒有 Key，請補齊旋轉通道' if not c.keyframe_points else
                          '使用 ' + c.extrapolation + ' 外插，請先確認轉換範圍' if c.extrapolation != 'CONSTANT' else '')
                if reason:
                    component = ('WXYZ' if size == 4 else 'XYZ')[c.array_index]
                    raise ValueError(f'{action.name} / {name} / {component}：{reason}')
            if obj.pose.bones[name].rotation_mode not in {'XYZ', 'QUATERNION'}:
                raise ValueError(name + '：目前只支援 XYZ Euler')
            destpath = obj.pose.bones[name].path_from_id() + '.' + dest
            if any(c.data_path == destpath and rotation_has_data(c) for c in curves):
                raise ValueError(action.name + '：已有目標旋轉通道，請先移除重複通道')
            if any(c.data_path == destpath for c in curves):
                raise ValueError(f'{action.name} / {name}：目標模式留有空通道，請先清除空通道')
            times = {float(p.co.x) for c in channels for p in c.keyframe_points}
            first, last = min(times), max(times)
            count = math.ceil((last - first) / step)
            if not original_only and count > 200000:
                raise ValueError('取樣數過多，請增加間隔')
            if not original_only:
                times.update(first + i * step for i in range(count) if first + i * step < last)
            jobs.append((action, name, bags[0], sorted(channels, key=lambda c: c.array_index), destpath, sorted(times)))
    if not jobs:
        raise ValueError('所選 Action／骨骼沒有來源旋轉 Key')
    total = sum(len(j[-1]) for j in jobs)
    done, staged = 0, []
    for action, name, bag, channels, path, times in jobs:
        samples, previous = [], None
        for frame in times:
            values = [c.evaluate(frame) for c in channels]
            quat = Quaternion(values) if target == 'XYZ' else Euler(values, 'XYZ').to_quaternion()
            if quat.magnitude < 1e-8:
                raise ValueError(action.name + '：零長度 Quaternion')
            quat.normalize()
            if target == 'XYZ':
                value = quat.to_euler('XYZ', previous) if previous else quat.to_euler('XYZ')
            else:
                if previous and quat.dot(previous) < 0:
                    quat.negate()
                value = quat
            previous = value.copy()
            constant = False if original_only else all(next((p.interpolation == 'CONSTANT' for p in reversed(c.keyframe_points)
                                 if p.co.x <= frame), False) for c in channels)
            samples.append((frame, tuple(value), 'BEZIER' if original_only else 'CONSTANT' if constant else 'LINEAR'))
            done += 1
            yield done, total, action.name
        staged.append((action, name, bag, channels, path, samples))
    created, removed = [], []
    bones = {name: (obj.pose.bones[name].rotation_mode,
                   obj.pose.bones[name].rotation_euler.copy(),
                   obj.pose.bones[name].rotation_quaternion.copy()) for name in names}
    try:
        for action, name, bag, channels, path, samples in staged:
            for index in range(3 if target == 'XYZ' else 4):
                curve = bag.fcurves.new(path, index=index)
                created.append((bag, curve))
                if channels[0].group:
                    curve.group = channels[0].group
                curve.keyframe_points.add(len(samples))
                for sample_index, (point, (frame, values, interp)) in enumerate(zip(curve.keyframe_points, samples)):
                    point.co = frame, values[index]
                    point.interpolation = interp
                    if original_only:
                        point.handle_left_type = point.handle_right_type = 'AUTO_CLAMPED'
                    if (sample_index + 1) % 128 == 0:
                        yield total, total, action.name + '（寫回中）'
                curve.update()
                yield total, total, action.name + '（寫回中）'
        for action, name, bag, channels, path, samples in staged:
            for curve in channels:
                record = (bag, curve.data_path, curve.array_index, snapshot(curve), curve.extrapolation,
                          curve.group.name if curve.group else None,
                          {k: tuple(curve.color) if k == 'color' else getattr(curve, k)
                           for k in ('color_mode', 'color', 'auto_smoothing', 'hide', 'select')})
                bag.fcurves.remove(curve)
                removed.append(record)
            yield total, total, action.name + '（寫回中）'
        for name, (mode, euler, quat) in bones.items():
            bone = obj.pose.bones[name]
            rotation = quat.normalized() if mode == 'QUATERNION' else Euler(euler, mode).to_quaternion()
            bone.rotation_mode = target
            if target == 'XYZ':
                bone.rotation_euler = rotation.to_euler('XYZ')
            else:
                bone.rotation_quaternion = rotation
        context.scene.frame_set(context.scene.frame_current, subframe=context.scene.frame_subframe)
        for action in actions:
            action.update_tag()
    except (Exception, GeneratorExit):
        for bag, curve in reversed(created):
            bag.fcurves.remove(curve)
        for bag, path, index, points, extrapolation, group, attributes in removed:
            curve = bag.fcurves.new(path, index=index)
            curve.extrapolation = extrapolation
            for key, value in attributes.items():
                setattr(curve, key, value)
            if group:
                curve.group = bag.groups.get(group) or bag.groups.new(group)
            write_points(curve, points)
        for name, (mode, euler, quat) in bones.items():
            bone = obj.pose.bones[name]
            bone.rotation_mode, bone.rotation_euler, bone.rotation_quaternion = mode, euler, quat
        context.scene.frame_set(context.scene.frame_current, subframe=context.scene.frame_subframe)
        raise
    return {'actions': len({j[0] for j in jobs}), 'bones': len(bones), 'samples': total}


def mirror_action(action, obj):
    """Mirror local pose channels with Blender Paste Flipped's X-axis convention.

    Preserve key times/interpolation/handles; never resample or touch other slots.
    """
    if not action.is_editable:
        raise ValueError('Action 為唯讀，請選擇建立翻轉副本')
    if not slot_for(action, obj):
        raise ValueError('Action 的 Slot 無法明確對應目前骨架')
    plans, skipped = [], 0
    for curve in target_curves(action, obj, [b.name for b in obj.pose.bones]):
        match = re.match(r'^pose\.bones\[("(?:\\.|[^"\\])*")\](.*)$', curve.data_path)
        if not match:
            continue
        name, suffix = json.loads(match[1]), match[2]
        flipped = bpy.utils.flip_name(name)
        if flipped not in obj.pose.bones:
            skipped += 1
            continue
        sign = -1 if ((suffix == '.location' and curve.array_index == 0) or
                      (suffix == '.rotation_euler' and curve.array_index in (1, 2)) or
                      (suffix in ('.rotation_quaternion', '.rotation_axis_angle') and curve.array_index in (2, 3)) or
                      suffix in ('.bbone_curveinx', '.bbone_curveoutx', '.bbone_rollin', '.bbone_rollout')) else 1
        if sign == -1 and (curve.modifiers or curve.sampled_points):
            raise ValueError('含修飾器或取樣曲線的翻轉通道需先烘焙為 Key')
        before = snapshot(curve)
        after = [dict(p) for p in before]
        if sign == -1:
            for p in after:
                for attr in ('co', 'handle_left', 'handle_right'):
                    p[attr] = (p[attr][0], -p[attr][1])
        path = 'pose.bones["' + bpy.utils.escape_identifier(flipped) + '"]' + suffix
        plans.append((curve, curve.data_path, path, before, after))
    committed = []
    try:
        for curve, old_path, path, before, after in plans:
            committed.append((curve, old_path, before))
            curve.data_path = path
            write_points(curve, after)
        action.update_tag()
    except Exception:
        for curve, old_path, before in committed:
            curve.data_path = old_path
            write_points(curve, before)
        raise
    return len(plans), skipped


KEY_FIELDS = ('co', 'handle_left', 'handle_right', 'handle_left_type',
              'handle_right_type', 'interpolation', 'easing', 'type',
              'amplitude', 'back', 'period', 'select_control_point',
              'select_left_handle', 'select_right_handle')


def snapshot(curve):
    return [{k: tuple(getattr(p, k)) if k in ('co', 'handle_left', 'handle_right')
             else getattr(p, k) for k in KEY_FIELDS} for p in curve.keyframe_points]


def write_points_steps(curve, points):
    curve.keyframe_points.clear()
    curve.keyframe_points.add(len(points))
    for index, (p, values) in enumerate(zip(curve.keyframe_points, points)):
        for key, value in values.items():
            if key not in ('handle_left', 'handle_right'):
                setattr(p, key, value)
        p.handle_left = values['handle_left']
        p.handle_right = values['handle_right']
        if (index + 1) % 128 == 0:
            yield None
    curve.update()


def write_points(curve, points):
    for _ in write_points_steps(curve, points):
        pass


def choose(items, index, anchor, ctrl=False, shift=False):
    if shift and 0 <= anchor < len(items):
        first, last = sorted((anchor, index))
        for i, item in enumerate(items):
            item.selected = (item.selected if ctrl else False) or first <= i <= last
        return anchor
    for i, item in enumerate(items):
        item.selected = (not item.selected if i == index else item.selected) if ctrl else i == index
    return index


class NativeProcessor:
    def __init__(self, context):
        self.context = context
        self.scene = bpy.data.scenes.new('__BatchCleanKey_Work__')
        self.obj = bpy.data.objects.new('__BatchCleanKey_Work__', None)
        self.scene.collection.objects.link(self.obj)
        self.scene.view_layers[0].objects.active = self.obj
        self.obj.select_set(True, view_layer=self.scene.view_layers[0])
        self.action = bpy.data.actions.new('__BatchCleanKey_Work__')
        slot = self.action.slots.new('OBJECT', self.obj.name)
        bag = self.action.layers.new('Work').strips.new(type='KEYFRAME').channelbag(slot, ensure=True)
        self.curve = bag.fcurves.new('location', index=0)
        ad = self.obj.animation_data_create()
        ad.action = self.action
        ad.action_slot = slot

    def run(self, points, operation, threshold, mode, ratio, error):
        write_points(self.curve, points)
        self.curve.select = True
        for p in self.curve.keyframe_points:
            p.select_control_point = p.select_left_handle = p.select_right_handle = True
        context = self.context
        window = context.window
        area = context.area or next((a for a in window.screen.areas
                                     if a.type in {'VIEW_3D', 'GRAPH_EDITOR', 'DOPESHEET_EDITOR'}),
                                    window.screen.areas[0])
        old_scene, old_type = window.scene, area.type
        old_ui_type = area.ui_type
        props = {}
        try:
            window.scene = self.scene
            area.type = 'GRAPH_EDITOR'
            space = area.spaces.active
            for name, value in [('mode', 'FCURVES'), ('pin', False)]:
                if hasattr(space, name):
                    props[(space, name)] = getattr(space, name)
                    setattr(space, name, value)
            ds = space.dopesheet
            for name, value in [('show_only_selected', False), ('show_hidden', True),
                                ('show_only_errors', False), ('filter_text', '')]:
                props[(ds, name)] = getattr(ds, name)
                setattr(ds, name, value)
            region = next(r for r in area.regions if r.type == 'WINDOW')
            with context.temp_override(window=window, area=area, region=region,
                                       scene=self.scene, view_layer=self.scene.view_layers[0],
                                       active_object=self.obj, object=self.obj,
                                       selected_objects=[self.obj], selected_editable_objects=[self.obj]):
                if operation == 'CLEAN':
                    result = bpy.ops.graph.clean('EXEC_DEFAULT', False, threshold=threshold, channels=False)
                else:
                    result = bpy.ops.graph.decimate('EXEC_DEFAULT', False, mode=mode, factor=ratio, remove_error_margin=error)
                if result != {'FINISHED'}:
                    raise RuntimeError('Blender 原生運算未完成')
            output = snapshot(self.curve)
            # Preserve selection of surviving source keys; scratch selection is internal.
            selections = {p['co'][0]: p for p in points}
            for p in output:
                original = selections.get(p['co'][0])
                if original:
                    for name in KEY_FIELDS[-3:]:
                        p[name] = original[name]
            return output
        finally:
            for (owner, name), value in props.items():
                setattr(owner, name, value)
            area.type = old_type
            area.ui_type = old_ui_type
            window.scene = old_scene

    def close(self):
        bpy.data.objects.remove(self.obj, do_unlink=True)
        bpy.data.actions.remove(self.action)
        bpy.data.scenes.remove(self.scene)


def process_steps(context, obj, names, actions, operation, threshold=0.001,
                  mode='RATIO', ratio=0.5, error=0.01):
    if operation not in {'DELETE', 'CLEAN', 'DECIMATE'}:
        raise ValueError('Unknown operation')
    plans, skipped, changed_actions = [], 0, set()
    jobs = [(a, c) for a in actions if a.is_editable for c in target_curves(a, obj, names)]
    skipped = sum(not a.is_editable for a in actions)
    processor = None
    try:
        for index, (action, curve) in enumerate(jobs):
            if curve.lock or not curve.keyframe_points:
                skipped += 1
                yield (index + 1, len(jobs), action.name)
                continue
            before = snapshot(curve)
            if operation == 'DELETE':
                after = []
            else:
                if operation == 'DECIMATE' and any(p['interpolation'] not in {'BEZIER', 'LINEAR'} for p in before):
                    skipped += 1
                    yield (index + 1, len(jobs), action.name)
                    continue
                if processor is None:
                    processor = NativeProcessor(context)
                after = processor.run(before, operation, threshold, mode, ratio, error)
            if before != after:
                plans.append((curve, before, after, action))
                changed_actions.add(action.name)
            yield (index + 1, len(jobs), action.name)
    finally:
        if processor:
            processor.close()
    # Commit only after all native operations succeeded; roll back on failure.
    committed = []
    try:
        for curve, before, after, action in plans:
            committed.append((curve, before))
            for _ in write_points_steps(curve, after):
                yield len(jobs), len(jobs), action.name + '（寫回中）'
            action.update_tag()
            yield len(jobs), len(jobs), action.name + '（寫回中）'
    except (Exception, GeneratorExit):
        for curve, before in committed:
            write_points(curve, before)
        context.scene.frame_set(context.scene.frame_current, subframe=context.scene.frame_subframe)
        raise
    context.view_layer.update()
    return {'actions': len(changed_actions), 'curves': len(plans),
            'removed': sum(len(before) - len(after) for _, before, after, _ in plans), 'skipped': skipped}


def process(context, obj, names, actions, operation, threshold=0.001,
            mode='RATIO', ratio=0.5, error=0.01):
    steps = process_steps(context, obj, names, actions, operation, threshold, mode, ratio, error)
    while True:
        try:
            next(steps)
        except StopIteration as done:
            return done.value
