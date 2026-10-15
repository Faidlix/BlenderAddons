"""Persistent Action looping; UI calls toggle_steps and consumes its progress.

Only the resolved rig slot is edited. A native Action copy stages all changes;
closing the generator before commit leaves the source and all users untouched.
The public _faidlix_action_loop boolean is also read by independent exporters.
"""
import math
import bpy
from . import core

LOOP_KEY = '_faidlix_action_loop'


def enabled(action):
    return bool(action.get(LOOP_KEY, action.use_cyclic))


def _bag(action, obj):
    slot = core.slot_for(action, obj)
    bags = [s.channelbag(slot) for l in action.layers for s in l.strips
            if slot and s.type == 'KEYFRAME' and s.channelbag(slot)]
    if len(bags) != 1:
        raise ValueError('Action Slot 不明確或包含多層動畫，無法安全切換循環')
    return bags[0]


def _slope(point, side):
    handle = getattr(point, 'handle_' + side)
    dx = handle.x - point.co.x
    return (handle.y - point.co.y) / dx if abs(dx) > 1e-7 else 0.0


def _handles(point, slope, span):
    distance = max(span / 3, 1e-5)
    point.handle_left_type = point.handle_right_type = 'FREE'
    point.handle_left = (point.co.x-distance, point.co.y-slope*distance)
    point.handle_right = (point.co.x+distance, point.co.y+slope*distance)


def _close_curve(curve, start, end):
    cycles=[m for m in curve.modifiers if m.type=='CYCLES']
    for m in cycles: m.mute=True
    values={frame:curve.evaluate(frame) for frame in {start,end}}
    for frame in sorted({start, end}):
        if not any(abs(p.co.x-frame) < 1e-6 for p in curve.keyframe_points):
            point = curve.keyframe_points.insert(frame, values[frame])
            point.interpolation = 'BEZIER'
            point.handle_left_type = point.handle_right_type = 'AUTO_CLAMPED'
    for m in cycles: m.mute=False
    curve.update()
    points = curve.keyframe_points
    if len(points) == 1:
        return
    first, last = points[0], points[-1]
    outgoing, incoming = _slope(first, 'right'), _slope(last, 'left')
    delta = first.co.y-last.co.y
    last.co.y = first.co.y
    last.handle_left.y += delta; last.handle_right.y += delta
    first.interpolation = 'BEZIER'
    points[-2].interpolation = 'BEZIER'
    right_span = points[1].co.x-start
    left_span = end-points[-2].co.x
    right_secant = (points[1].co.y-first.co.y)/right_span
    left_secant = (last.co.y-points[-2].co.y)/left_span
    if right_secant*left_secant <= 1e-12:
        slope = 0.0
        first.handle_left_type = first.handle_right_type = 'AUTO_CLAMPED'
        last.handle_left_type = last.handle_right_type = 'AUTO_CLAMPED'
    else:
        if outgoing*right_secant <= 1e-12: outgoing = right_secant
        if incoming*left_secant <= 1e-12: incoming = left_secant
        slope = 2/(1/outgoing+1/incoming)
        slope = math.copysign(min(abs(slope), 3*min(abs(right_secant), abs(left_secant))), slope)
        _handles(first, slope, right_span); _handles(last, slope, left_span)
        if math.isclose(right_secant, left_secant, rel_tol=1e-5, abs_tol=1e-6):
            first.handle_left_type = first.handle_right_type = 'VECTOR'
            last.handle_left_type = last.handle_right_type = 'VECTOR'
        else:
            first.handle_left_type = first.handle_right_type = 'ALIGNED'
            last.handle_left_type = last.handle_right_type = 'ALIGNED'
    curve.update()
    # Native auto handles can react to modifiers/smoothing. C1 continuity wins.
    if not (math.isclose(_slope(first, 'right'), slope, rel_tol=1e-5, abs_tol=1e-6)
            and math.isclose(_slope(last, 'left'), slope, rel_tol=1e-5, abs_tol=1e-6)):
        _handles(first, slope, right_span); _handles(last, slope, left_span)
        curve.update()


def toggle_steps(context, obj, action, turn_on):
    if not action or not action.is_editable or not obj or not obj.is_editable:
        raise ValueError('請使用可編輯的骨架與 Action')
    source = _bag(action, obj)
    animated = [c for c in source.fcurves if c.keyframe_points or c.sampled_points]
    frames = [float(p.co.x) for c in animated for points in (c.keyframe_points, c.sampled_points) for p in points]
    if turn_on and not frames:
        raise ValueError('Action 沒有動畫 Key')
    start, end = (min(frames), max(frames)) if frames else (0, 0)
    original_name, fake_user = action.name, action.use_fake_user
    staged = action.copy(); staged.name = '__ActionEditorLoop__' + original_name
    remapped = False
    try:
        bag = _bag(staged, obj)
        curves = list(bag.fcurves)
        total = max(1, len(curves)); completed = 0
        for curve in curves:
            if turn_on and not (curve.keyframe_points or curve.sampled_points):
                completed += 1; yield completed, total+1, original_name
                continue
            flags = curve.lock, curve.mute
            if turn_on:
                # Cycles are repetition only; preserve the underlying sparse keys.
                other = any(m.type != 'CYCLES' for m in curve.modifiers)
                if other or curve.sampled_points:
                    times = sorted({start, end} | {float(p.co.x) for pts in (curve.keyframe_points, curve.sampled_points) for p in pts})
                    values = []
                    for i, frame in enumerate(times):
                        values.append(curve.evaluate(frame))
                        if i % 128 == 0: yield completed, total+1, original_name
                    for modifier in list(curve.modifiers): curve.modifiers.remove(modifier)
                    if curve.sampled_points:
                        curve.convert_to_keyframes(math.floor(start), math.ceil(end))
                    curve.keyframe_points.clear(); curve.keyframe_points.add(len(times))
                    for i, (frame, value) in enumerate(zip(times, values)):
                        p = curve.keyframe_points[i]; p.co = frame, value
                        p.interpolation = 'BEZIER'; p.handle_left_type = p.handle_right_type = 'AUTO_CLAMPED'
                        if i % 128 == 0: yield completed, total+1, original_name
                for modifier in list(curve.modifiers): curve.modifiers.remove(modifier)
                modifier = curve.modifiers.new('CYCLES')
                modifier.mode_before = modifier.mode_after = 'REPEAT'
                _close_curve(curve, start, end)
            else:
                # Freeze seam geometry before removing cyclic auto-handle context.
                if curve.keyframe_points and any(m.type == 'CYCLES' for m in curve.modifiers):
                    for point in (curve.keyframe_points[0], curve.keyframe_points[-1]):
                        left, right = tuple(point.handle_left), tuple(point.handle_right)
                        point.handle_left_type = point.handle_right_type = 'FREE'
                        point.handle_left, point.handle_right = left, right
                for modifier in list(curve.modifiers):
                    if modifier.type == 'CYCLES': curve.modifiers.remove(modifier)
            curve.lock, curve.mute = flags
            completed += 1
            yield completed, total+1, original_name
        staged[LOOP_KEY] = bool(turn_on); staged.use_cyclic = bool(turn_on)
        staged.use_fake_user = fake_user
        staged.update_tag()
        yield total, total+1, original_name+'（完成準備）'
        action.user_remap(staged); remapped = True
        bpy.data.actions.remove(action); staged.name = original_name
        result = {'loop_action': staged.name, 'loop_enabled': bool(turn_on)}
        staged = None
        return result
    finally:
        if staged:
            if remapped: staged.user_remap(action)
            bpy.data.actions.remove(staged)
