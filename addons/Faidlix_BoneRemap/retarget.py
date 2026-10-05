import math
import os

import bpy
from mathutils import Euler, Matrix, Quaternion, Vector

from .model import action_keyframes, flip_bone_name, iter_action_fcurves, normalize_bone_name


SYNONYMS = {
    "hips": ("hips", "pelvis", "root", "crootmasterx", "crootmaster"),
    "pelvis": ("hips", "pelvis", "root", "crootmasterx", "crootmaster"),
    "spine": ("spine", "spine01", "cspine01x", "cspine01"),
    "chest": ("chest", "spine02", "spine2", "cspine02x", "cspine02"),
    "neck": ("neck", "cneckx", "cneck"),
    "head": ("head", "cheadx", "chead"),
    "lupperarm": ("lupperarm", "larm", "upperarml", "carmfkl"),
    "rupperarm": ("rupperarm", "rarm", "upperarmr", "carmfkr"),
    "lforearm": ("lforearm", "lowerarml", "forearml", "cforearmfkl"),
    "rforearm": ("rforearm", "lowerarmr", "forearmr", "cforearmfkr"),
    "lthigh": ("lthigh", "upperlegl", "thighl", "cthighfkl"),
    "rthigh": ("rthigh", "upperlegr", "thighr", "cthighfkr"),
    "lcalf": ("lcalf", "lowerlegl", "shinl", "clegfkl"),
    "rcalf": ("rcalf", "lowerlegr", "shinr", "clegfkr"),
    "lfoot": ("lfoot", "footl", "cfootikl", "cfootfkl"),
    "rfoot": ("rfoot", "footr", "cfootikr", "cfootfkr"),
}


def _name_candidates(source_name):
    normalized = normalize_bone_name(source_name)
    result = [normalized]
    for key, values in SYNONYMS.items():
        normalized_values = tuple(normalize_bone_name(value) for value in values)
        if normalized == normalize_bone_name(key) or normalized in normalized_values:
            result.extend(normalized_values)
    return list(dict.fromkeys(result))


def build_automatic_mapping(source_obj, target_obj, collection):
    collection.clear()
    if not source_obj or not target_obj:
        return 0
    target_by_name = {}
    for bone in target_obj.data.bones:
        target_by_name.setdefault(normalize_bone_name(bone.name), bone.name)
    mapped = 0
    root_assigned = False
    for source_bone in source_obj.data.bones:
        item = collection.add()
        item.source_bone = source_bone.name
        for candidate in _name_candidates(source_bone.name):
            if candidate in target_by_name:
                item.target_bone = target_by_name[candidate]
                mapped += 1
                break
        normalized = normalize_bone_name(source_bone.name)
        root_like = any(token in normalized for token in ("hips", "pelvis", "root"))
        if not root_assigned and (root_like or source_bone.parent is None):
            item.is_root = True
            item.transfer_location = True
            root_assigned = True
        item.reset_rotation_offset = item.rotation_offset
        item.reset_transfer_location = item.transfer_location
        item.reset_location_multiplier = item.location_multiplier
        item.reset_is_root = item.is_root
    return mapped


def mapping_source(settings, source_file):
    if source_file.reuse_mapping == "SELF":
        return source_file
    for candidate in settings.files:
        if candidate.uid == source_file.reuse_mapping:
            return candidate
    return source_file


def output_name(settings, source_file, clip, mirrored=False):
    if settings.naming_mode == "CUSTOM":
        name = clip.custom_name or clip.action_name
    elif settings.naming_mode == "ACTION":
        name = clip.action_name
    else:
        stem = os.path.splitext(source_file.display_name)[0]
        name = f"{stem}_{clip.action_name}"
    if mirrored:
        name += "_Mirror"
    return name


def _frame_sequence(action, mode):
    if mode == "SOURCE":
        return action_keyframes(action)
    start, end = action.frame_range
    return list(range(math.floor(start), math.ceil(end) + 1))


def _reflect_basis(matrix):
    reflection = Matrix.Diagonal((-1.0, 1.0, 1.0, 1.0))
    return reflection @ matrix @ reflection


def _rest_rotation(obj, bone_name):
    bone = obj.data.bones.get(bone_name)
    if not bone:
        return None
    if bone.parent:
        return (
            bone.parent.matrix_local.inverted() @ bone.matrix_local
        ).to_quaternion()
    return obj.matrix_world.to_quaternion() @ bone.matrix_local.to_quaternion()


def _basis_correction(
    source_obj,
    target_obj,
    source_name,
    target_name,
    global_correction,
):
    source_bone = source_obj.data.bones.get(source_name)
    target_bone = target_obj.data.bones.get(target_name)
    if not source_bone or not target_bone:
        return None
    source_rest = _rest_rotation(source_obj, source_name)
    target_rest = _rest_rotation(target_obj, target_name)
    if not source_rest or not target_rest:
        return None
    if source_bone.parent and target_bone.parent:
        return target_rest.inverted() @ source_rest
    return target_rest.inverted() @ global_correction @ source_rest


def _clear_target_pose(target_obj):
    for bone in target_obj.pose.bones:
        bone.location = (0.0, 0.0, 0.0)
        bone.rotation_mode = "QUATERNION"
        bone.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        bone.scale = (1.0, 1.0, 1.0)


def assign_action_and_slot(target_obj, action):
    animation = target_obj.animation_data_create()
    if not action.slots:
        slot = action.slots.new(target_obj.id_type, target_obj.name)
    else:
        slot = next(
            (
                candidate
                for candidate in action.slots
                if candidate.target_id_type == target_obj.id_type
                and candidate.name_display == target_obj.name
            ),
            None,
        )
    animation.action = action
    suitable_slots = list(animation.action_suitable_slots)
    if slot is not None:
        pass
    elif suitable_slots:
        slot = suitable_slots[0]
    else:
        slot = next(
            (
                candidate
                for candidate in action.slots
                if candidate.target_id_type == target_obj.id_type
            ),
            action.slots[0],
        )
        slot.name_display = target_obj.name
    animation.action_slot = slot
    return slot


def _ik_chain_names(target_obj, mapping):
    bone = target_obj.data.bones.get(mapping.target_bone)
    if not bone:
        return set()
    result = set()
    remaining = mapping.ik_chain_count
    while bone and (remaining > 0 or mapping.ik_chain_count == 0):
        result.add(bone.name)
        bone = bone.parent
        if mapping.ik_chain_count:
            remaining -= 1
    return result


def _fbr_ik_constraint(pose_bone):
    return next(
        (
            constraint
            for constraint in pose_bone.constraints
            if constraint.type == "IK" and constraint.name.startswith("FBR IK")
        ),
        None,
    )


def iter_bake_clip(
    context,
    settings,
    source_file,
    clip,
    target_obj,
    out_action,
    out_start,
    mirrored=False,
):
    source_obj = bpy.data.objects.get(source_file.source_object)
    source_action = bpy.data.actions.get(clip.action_name)
    if not source_obj or not source_action:
        raise RuntimeError(f"找不到來源：{source_file.display_name} / {clip.action_name}")
    mapping_file = mapping_source(settings, source_file)
    mappings = [item for item in mapping_file.mappings if item.target_bone]
    if not mappings:
        raise RuntimeError(f"{source_file.display_name} 沒有可用骨骼映射")

    source_obj.animation_data_create()
    target_obj.animation_data_create()
    previous_source_action = source_obj.animation_data.action
    previous_source_slot = source_obj.animation_data.action_slot
    previous_target_action = target_obj.animation_data.action
    previous_target_slot = target_obj.animation_data.action_slot
    previous_source_use_nla = source_obj.animation_data.use_nla
    previous_target_use_nla = target_obj.animation_data.use_nla
    previous_source_hidden = source_obj.hide_get()
    previous_source_hide_viewport = source_obj.hide_viewport
    source_obj.hide_viewport = False
    source_obj.hide_set(False)
    source_obj.animation_data.use_nla = False
    target_obj.animation_data.use_nla = False
    assign_action_and_slot(source_obj, source_action)
    assign_action_and_slot(target_obj, out_action)
    frames = _frame_sequence(source_action, settings.key_mode)
    if not frames:
        return 0

    root_baselines = {}
    root_vertical_baselines = {}
    root_target_names = {
        mapping.target_bone for mapping in mappings if mapping.is_root
    }
    global_correction = Quaternion(source_file.global_axis_correction).normalized()
    applied_scale = float(source_obj.get("_fbr_alignment_scale", 1.0))
    try:
        for frame_index, source_frame in enumerate(frames):
            context.scene.frame_set(source_frame)
            context.view_layer.update()
            evaluated_source = source_obj.evaluated_get(
                context.evaluated_depsgraph_get()
            )
            target_frame = out_start + (source_frame - frames[0])
            ik_mappings = []
            ik_chain_names = set()
            muted_constraints = []
            for mapping in mappings:
                if not mapping.ik_enabled or not mapping.ik_control_bone:
                    continue
                owner = target_obj.pose.bones.get(mapping.target_bone)
                control = target_obj.pose.bones.get(mapping.ik_control_bone)
                constraint = _fbr_ik_constraint(owner) if owner else None
                if not owner or not control or not constraint:
                    continue
                constraint.target = target_obj
                constraint.subtarget = mapping.ik_control_bone
                constraint.chain_count = mapping.ik_chain_count
                constraint.iterations = mapping.ik_iterations
                constraint.influence = mapping.ik_influence
                constraint.use_tail = mapping.ik_use_tail
                constraint.use_rotation = mapping.ik_use_rotation
                constraint.use_stretch = mapping.ik_use_stretch
                ik_mappings.append((mapping, owner, control, constraint))
                ik_chain_names.update(_ik_chain_names(target_obj, mapping))
                muted_constraints.append((constraint, constraint.mute))
                constraint.mute = True

            # The output action is evaluated as the scene advances.  Without
            # resetting every pose channel here, an IK control starts from the
            # previous frame's solved offset and the iterative correction adds
            # that offset again.  This produces the visible per-frame downward
            # drift, especially across several batch jobs.  Each sampled frame
            # must start from the same rest basis before FK mapping and IK solve.
            _clear_target_pose(target_obj)
            context.view_layer.update()

            # Foot/hand IK may walk all the way up the hierarchy when its
            # chain count is zero or large.  Root motion must never become an
            # IK-owned channel: it is authored by the mapped Root bone and
            # remains stable while the limb solver adjusts only the chain.
            ik_chain_names.difference_update(root_target_names)

            for mapping in mappings:
                source_name = mapping.source_bone
                if mirrored:
                    counterpart = flip_bone_name(source_name)
                    if counterpart in source_obj.pose.bones:
                        source_name = counterpart
                source_pose = evaluated_source.pose.bones.get(source_name)
                target_pose = target_obj.pose.bones.get(mapping.target_bone)
                if not source_pose or not target_pose:
                    continue

                basis = source_pose.matrix_basis.copy()
                if mirrored:
                    basis = _reflect_basis(basis)
                location, source_rotation, scale = basis.decompose()

                correction = _basis_correction(
                    source_obj,
                    target_obj,
                    source_name,
                    mapping.target_bone,
                    global_correction,
                )
                if correction:
                    corrected_source = (
                        Euler(mapping.pair_rotation_offset).to_quaternion()
                        @ Euler(mapping.rotation_offset).to_quaternion()
                        @ source_rotation
                    )
                    target_rotation = correction @ corrected_source @ correction.inverted()
                    location = correction @ location
                else:
                    target_rotation = (
                        Euler(mapping.pair_rotation_offset).to_quaternion()
                        @ Euler(mapping.rotation_offset).to_quaternion()
                        @ source_rotation
                    )

                target_pose.rotation_mode = "QUATERNION"
                target_pose.rotation_quaternion = target_rotation
                target_pose.scale = scale
                if target_pose.name not in ik_chain_names:
                    target_pose.keyframe_insert(
                        data_path="rotation_quaternion",
                        frame=target_frame,
                        group=target_pose.name,
                    )
                    target_pose.keyframe_insert(
                        data_path="scale",
                        frame=target_frame,
                        group=target_pose.name,
                    )

                if mapping.is_root or mapping.transfer_location:
                    location = Vector(location) * mapping.location_multiplier
                    if settings.auto_scale:
                        location *= applied_scale
                    if clip.in_place and mapping.is_root:
                        baseline = root_baselines.setdefault(mapping.target_bone, location.copy())
                        location.x -= baseline.x
                        location.y -= baseline.y
                    if ik_mappings and mapping.is_root:
                        vertical = root_vertical_baselines.setdefault(
                            mapping.target_bone,
                            location.z,
                        )
                        location.z = vertical
                    if settings.extract_root_motion and mapping.is_root:
                        trajectory = target_obj.pose.bones.get("c_traj")
                        if trajectory and trajectory.name != target_pose.name:
                            trajectory.location = (location.x, location.y, 0.0)
                            trajectory.keyframe_insert(
                                data_path="location",
                                frame=target_frame,
                                group=trajectory.name,
                            )
                            location.x = 0.0
                            location.y = 0.0
                    target_pose.location = location
                    if target_pose.name not in ik_chain_names:
                        target_pose.keyframe_insert(
                            data_path="location",
                            frame=target_frame,
                            group=target_pose.name,
                        )

            context.view_layer.update()
            desired_ik_positions = {
                mapping.as_pointer(): owner.matrix.translation.copy()
                for mapping, owner, _control, _constraint in ik_mappings
            }
            for bone_name in ik_chain_names:
                pose_bone = target_obj.pose.bones.get(bone_name)
                if pose_bone:
                    pose_bone.location = (0.0, 0.0, 0.0)
                    pose_bone.rotation_mode = "QUATERNION"
                    pose_bone.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
                    pose_bone.scale = (1.0, 1.0, 1.0)
            for constraint, was_muted in muted_constraints:
                constraint.mute = was_muted
            context.view_layer.update()
            for mapping, owner, control, constraint in ik_mappings:
                if constraint.mute:
                    continue
                desired = desired_ik_positions[mapping.as_pointer()]
                # PoseBone.matrix and owner.matrix are both in Target armature
                # object space.  Assign the control directly in that same
                # space; the previous iterative owner-error correction mixed
                # the solved IK result back into the control and could send it
                # far away after scale/axis conversion.
                control_matrix = control.bone.matrix_local.copy()
                control_matrix.translation = desired
                control.matrix = control_matrix
                context.view_layer.update()
                control.keyframe_insert(
                    data_path="location",
                    frame=target_frame,
                    group=control.name,
                )
            yield frame_index + 1
        out_action.use_fake_user = settings.fake_user
        return math.ceil(frames[-1] - frames[0]) + 1
    finally:
        source_obj.animation_data.action = previous_source_action
        target_obj.animation_data.action = previous_target_action
        if previous_source_action and previous_source_slot:
            try:
                source_obj.animation_data.action_slot = previous_source_slot
            except TypeError:
                pass
        source_obj.animation_data.use_nla = previous_source_use_nla
        target_obj.animation_data.use_nla = previous_target_use_nla
        source_obj.hide_viewport = previous_source_hide_viewport
        source_obj.hide_set(previous_source_hidden)
        if previous_target_action and previous_target_slot:
            try:
                target_obj.animation_data.action_slot = previous_target_slot
            except TypeError:
                pass


def bake_clip(*args, **kwargs):
    iterator = iter_bake_clip(*args, **kwargs)
    while True:
        try:
            next(iterator)
        except StopIteration as finished:
            return finished.value


def _rdp_indices(points, tolerance):
    if len(points) <= 2:
        return set(range(len(points)))
    x1, y1 = points[0]
    x2, y2 = points[-1]
    dx = x2 - x1
    dy = y2 - y1
    denominator = math.hypot(dx, dy)
    best_distance = -1.0
    best_index = 0
    for index, (x, y) in enumerate(points[1:-1], 1):
        if denominator <= 1.0e-12:
            distance = math.hypot(x - x1, y - y1)
        else:
            distance = abs(dy * x - dx * y + x2 * y1 - y2 * x1) / denominator
        if distance > best_distance:
            best_distance = distance
            best_index = index
    if best_distance <= tolerance:
        return {0, len(points) - 1}
    left = _rdp_indices(points[: best_index + 1], tolerance)
    right = _rdp_indices(points[best_index:], tolerance)
    return left | {best_index + value for value in right}


def simplify_action(action, rotation_tolerance, location_tolerance):
    removed = 0
    for curve in list(iter_action_fcurves(action)):
        points = list(curve.keyframe_points)
        if len(points) <= 2:
            continue
        tolerance = rotation_tolerance if "rotation" in curve.data_path else location_tolerance
        keep = _rdp_indices([(point.co.x, point.co.y) for point in points], tolerance)
        for index in reversed(range(len(points))):
            if index not in keep:
                curve.keyframe_points.remove(points[index], fast=True)
                removed += 1
        curve.update()
    return removed
