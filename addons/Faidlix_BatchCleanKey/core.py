"""Native curve operations staged in an isolated temporary scene before commit."""
import bpy
import json
import re


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
    prefixes = tuple('pose.bones["' + bpy.utils.escape_identifier(n) + '"]' for n in names)
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
                              if any(f.data_path.startswith(p + '.') or
                                     f.data_path.startswith(p + '[') for p in prefixes))
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
    obj.update_tag(refresh={'TIME'})
    context.scene.frame_set(context.scene.frame_current, subframe=context.scene.frame_subframe)


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


def write_points(curve, points):
    curve.keyframe_points.clear()
    curve.keyframe_points.add(len(points))
    for p, values in zip(curve.keyframe_points, points):
        for key, value in values.items():
            if key not in ('handle_left', 'handle_right'):
                setattr(p, key, value)
        p.handle_left = values['handle_left']
        p.handle_right = values['handle_right']
    curve.update()


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
            write_points(curve, after)
            action.update_tag()
    except Exception:
        for curve, before in committed:
            write_points(curve, before)
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
