"""Non-destructive local-channel composition, shared by preview and baking."""
from dataclasses import dataclass, replace
import math
import bpy
from mathutils import Euler, Quaternion, Vector
from . import core


@dataclass
class Clip:
    action: object
    source_start: float
    source_end: float
    start: float
    duration: float
    mode: str = 'TRIM'

    @classmethod
    def from_action(cls, action, start=None):
        bounds = core.actual_range(action)
        if bounds is None:
            raise ValueError('Action 沒有動畫 Key：' + action.name)
        return cls(action, *bounds, bounds[0] if start is None else start,
                   max(bounds[1] - bounds[0], 0.001))

    @property
    def end(self):
        return self.start + self.duration

    def source_frame(self, frame):
        offset = min(max(frame - self.start, 0), self.duration)
        return self.source_start + offset * (self.source_end - self.source_start) / self.duration

    def resize(self, edge, frame):
        if edge == 'RIGHT':
            duration = max(0.001, frame - self.start)
            if self.mode == 'TRIM':
                bounds = core.actual_range(self.action)
                self.source_end = min(bounds[1], self.source_start + duration)
                duration = max(0.001, self.source_end - self.source_start)
            self.duration = duration
        else:
            end = self.end
            start = min(frame, end - 0.001)
            if self.mode == 'TRIM':
                bounds = core.actual_range(self.action)
                source = max(bounds[0], self.source_start + start - self.start)
                start = self.start + source - self.source_start
                self.source_start = source
            self.start, self.duration = start, max(0.001, end - start)

    def duplicate(self):
        return replace(self, start=self.end)


def choose(clips, frame, hold=False):
    overlaps = [c for c in clips if c.start <= frame <= c.end]
    if overlaps:
        return overlaps[-1]
    return min(clips, key=lambda c: min(abs(frame-c.start), abs(frame-c.end))) if hold and clips else None


class Evaluator:
    def __init__(self, obj, tracks, selected, transition=0, custom=False):
        self.obj, self.tracks = obj, tracks
        self.selected, self.transition, self.custom = set(selected), transition, custom
        self.maps = {}
        for clip in sum(tracks, []):
            action = clip.action
            slot = core.slot_for(action, obj)
            if not slot:
                raise ValueError(action.name + '：Slot 無法對應目前骨架')
            bags = [s.channelbag(slot) for l in action.layers for s in l.strips
                    if s.type == 'KEYFRAME' and s.channelbag(slot)]
            if len(bags) != 1:
                raise ValueError(action.name + '：多層 Action 請先烘焙')
            curves = [c for c in bags[0].fcurves if not c.mute and core.rotation_has_data(c)]
            mapping = {(c.data_path, c.array_index): c for c in curves}
            if len(mapping) != len(curves):
                raise ValueError(action.name + '：重複通道請先整理')
            self.maps[action.as_pointer()] = mapping
        self.defaults = {}
        for b in obj.pose.bones:
            path = b.path_from_id()
            mode = b.rotation_mode
            q = (b.rotation_quaternion.copy() if mode == 'QUATERNION' else
                 Quaternion(Vector(b.rotation_axis_angle[1:]), b.rotation_axis_angle[0])
                 if mode == 'AXIS_ANGLE' else b.rotation_euler.to_quaternion())
            self.defaults[b.name] = (path, mode, tuple(b.location), tuple(b.scale), q)
        self.extra = set()
        transforms = {path+'.'+prop for path, *_rest in self.defaults.values()
                      for prop in ('location','scale','rotation_euler','rotation_quaternion','rotation_axis_angle')}
        for clip in tracks[0]:
            self.extra.update(k for k in self.maps[clip.action.as_pointer()] if k[0] not in transforms)
        if custom:
            for clip in sum(tracks, []):
                for key in self.maps[clip.action.as_pointer()]:
                    if any(key[0].startswith(self.defaults[n][0] + '[') for n in self.defaults):
                        self.extra.add(key)

    def values(self, clip, frame):
        if not clip:
            return {}
        t = clip.source_frame(frame)
        return {key: c.evaluate(t) for key, c in self.maps[clip.action.as_pointer()].items()}

    def rotation(self, values, path, mode, default):
        for prop, count in (('rotation_quaternion', 4), ('rotation_euler', 3), ('rotation_axis_angle', 4)):
            keys = [(path + '.' + prop, i) for i in range(count)]
            if not any(k in values for k in keys):
                continue
            if prop == 'rotation_quaternion':
                base = tuple(default)
                q = Quaternion([values.get(k, base[i]) for i, k in enumerate(keys)])
                return q.normalized() if q.magnitude > 1e-9 else default.copy()
            if prop == 'rotation_euler':
                order = mode if mode not in {'QUATERNION', 'AXIS_ANGLE'} else 'XYZ'
                base = default.to_euler(order)
                return Euler([values.get(k, base[i]) for i, k in enumerate(keys)], order).to_quaternion()
            axis, angle = default.to_axis_angle()
            base = (angle, *axis)
            v = [values.get(k, base[i]) for i, k in enumerate(keys)]
            return Quaternion(Vector(v[1:]), v[0])
        return default.copy()

    def sample(self, frame, preview='COMBINED'):
        main = choose(self.tracks[0], frame, True)
        lower = choose(self.tracks[1], frame)
        a = self.values(main, frame)
        b = self.values(lower, frame)
        if preview == 'MAIN':
            b = {}
        elif preview == 'LOWER':
            a, b = self.values(choose(self.tracks[1], frame, True), frame), {}
        weight = 1.0
        if lower and self.transition and preview == 'COMBINED':
            weight = min(1, max(0, (frame-lower.start)/self.transition), max(0, (lower.end-frame)/self.transition))
        result = {}
        for name, (path, mode, loc, scale, default_q) in self.defaults.items():
            override = b if name in self.selected else {}
            for prop, defaults in (('location', loc), ('scale', scale)):
                for i, default in enumerate(defaults):
                    key = (path + '.' + prop, i)
                    base = a.get(key, default)
                    result[key] = base + (override.get(key, base)-base)*weight
            qa = self.rotation(a, path, mode, default_q)
            qb = self.rotation(override, path, mode, qa)
            q = qa.slerp(qb, weight)
            if mode == 'QUATERNION':
                prop, value = 'rotation_quaternion', q
            elif mode == 'AXIS_ANGLE':
                axis, angle = q.to_axis_angle()
                prop, value = 'rotation_axis_angle', (angle, *axis)
            else:
                prop, value = 'rotation_euler', q.to_euler(mode)
            for i, v in enumerate(value):
                result[(path + '.' + prop, i)] = v
        for key in self.extra:
            try:
                value = self.obj.path_resolve(key[0])
                default = value[key[1]] if hasattr(value, '__len__') else value
                base = a.get(key, float(default))
                override = b if self.custom and any(key[0].startswith(self.defaults[n][0]+'[') for n in self.selected) else {}
                result[key] = base + (override.get(key, base)-base)*weight
            except (ValueError, TypeError, IndexError):
                raise ValueError('無法解析動畫通道：' + key[0])
        return result


def set_values(obj, values):
    for (path, index), value in values.items():
        parent, _, prop = path.rpartition('.')
        if '[' in prop or not parent:
            # Custom properties use ID-property assignment, never eval/exec.
            if path.endswith(']') and '["' in path:
                import json
                owner, encoded = path.rsplit('[', 1)
                (obj.path_resolve(owner) if owner else obj)[json.loads(encoded[:-1])] = value
            else:
                target = getattr(obj, path)
                if hasattr(target, '__len__'):
                    target[index] = value
                else:
                    setattr(obj, path, value)
        else:
            setattr_target = obj.path_resolve(parent)
            target = getattr(setattr_target, prop)
            if hasattr(target, '__len__'):
                target[index] = value
            else:
                setattr(setattr_target, prop, value)
    obj.update_tag()


def bake_steps(obj, tracks, selected, name, start, end, step=1, transition=0, custom=False):
    if not all(math.isfinite(v) for v in (start,end,step,transition)) or end < start or step <= 0 or not tracks[0]:
        raise ValueError('請確認主 Action、輸出範圍與取樣間隔')
    evaluator = Evaluator(obj, tracks, selected, transition, custom)
    count = math.ceil((end-start)/step)+1
    if count > 1000000:
        raise ValueError('取樣超過一百萬影格，請縮短範圍或增加間隔')
    frames = {start, end}
    frames.update(min(end, start+i*step) for i in range(count))
    for clip in sum(tracks, []):
        frames.update(t for t in (clip.start, clip.end) if start <= t <= end)
        for c in evaluator.maps[clip.action.as_pointer()].values():
            for p in c.keyframe_points:
                if clip.source_start <= p.co.x <= clip.source_end:
                    t = clip.start+(p.co.x-clip.source_start)*clip.duration/max(clip.source_end-clip.source_start, 0.001)
                    if start <= t <= end:
                        frames.add(t)
    frames = sorted(frames)
    samples, previous = {}, {}
    total = len(frames)*2
    for done, frame in enumerate(frames, 1):
        values = evaluator.sample(frame)
        for bone, (path, mode, *_rest) in evaluator.defaults.items():
            if mode == 'QUATERNION':
                keys = [(path+'.rotation_quaternion', i) for i in range(4)]
                q = Quaternion([values[k] for k in keys])
                if bone in previous and q.dot(previous[bone]) < 0:
                    q.negate()
                previous[bone] = q.copy()
                values.update(zip(keys, q))
            elif mode != 'AXIS_ANGLE':
                keys = [(path+'.rotation_euler', i) for i in range(3)]
                e = Euler([values[k] for k in keys], mode)
                if bone in previous:
                    e.make_compatible(previous[bone])
                previous[bone] = e.copy()
                values.update(zip(keys, e))
        for key, value in values.items():
            samples.setdefault(key, []).append((frame, value))
        yield done, total
    action = None
    try:
        action = bpy.data.actions.new(name or 'Combined_Action')
        action.use_fake_user = True
        slot = action.slots.new('OBJECT', obj.name)
        strip = action.layers.new('Combined').strips.new(type='KEYFRAME')
        bag = strip.channelbag(slot, ensure=True)
        written = 0
        size = sum(len(points) for points in samples.values())
        for (path, index), points in samples.items():
            curve = bag.fcurves.new(path, index=index)
            curve.keyframe_points.add(len(points))
            for offset in range(0, len(points), 128):
                for i in range(offset, min(offset+128, len(points))):
                    point = curve.keyframe_points[i]
                    point.co = points[i]
                    point.interpolation = 'LINEAR'
                written += min(128, len(points)-offset)
                yield len(frames)+written/size*len(frames), total
            curve.update()
        core.sync_ranges([action])
        return action
    except BaseException:
        if action is not None:
            bpy.data.actions.remove(action)
        raise
