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


def source_action_for_clip(clip):
    return bpy.data.actions.get(getattr(clip, "source_action_name", "") or clip.action_name)


def _frame_sequence(action, mode):
    if mode == "SOURCE":
        return action_keyframes(action)
    start, end = action.frame_range
    return list(range(math.floor(start), math.ceil(end) + 1))


def pose_only_action(action):
    """Make a temporary source Action that cannot animate the armature object.

    FBX files commonly key object scale/rotation as well as pose bones.  The
    object channels otherwise overwrite the alignment matrix on every frame.
    """
    if not any(not curve.data_path.startswith('pose.bones[')
               for curve in iter_action_fcurves(action)):
        return action
    copy = action.copy()
    copy.name = f"__FBR_SOURCE_POSE__{action.name}"
    copy.use_fake_user = False
    legacy = getattr(copy, "fcurves", None)
    if legacy:
        for curve in list(legacy):
            if not curve.data_path.startswith('pose.bones['):
                legacy.remove(curve)
    for layer in getattr(copy, "layers", ()):
        for strip in getattr(layer, "strips", ()):
            for channelbag in getattr(strip, "channelbags", ()):
                for curve in list(channelbag.fcurves):
                    if not curve.data_path.startswith('pose.bones['):
                        channelbag.fcurves.remove(curve)
    return copy


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
    if source_bone.parent and target_bone.parent:
        # Pose basis rotations act in each bone's armature-space rest axes.
        # Comparing parent-relative rest matrices can invert one mirrored
        # limb when the source and target shoulder/hip rest axes differ.
        source_rest = source_bone.matrix_local.to_quaternion()
        target_rest = target_bone.matrix_local.to_quaternion()
        return target_rest.inverted() @ source_rest
    source_rest = _rest_rotation(source_obj, source_name)
    target_rest = _rest_rotation(target_obj, target_name)
    if not source_rest or not target_rest:
        return None
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


def _ik_chain_names(target_obj, mapping, owner_name=None, chain_count=None):
    endpoint = target_obj.data.bones.get(mapping.target_bone)
    bone = target_obj.data.bones.get(owner_name) if owner_name else (
        endpoint.parent
        if endpoint and endpoint.parent and endpoint.parent.parent
        else endpoint
    )
    if not bone:
        return set()
    # The endpoint is driven by the IK control as well.  Keeping its FK keys
    # would make the final pose a mixture of two competing animations.
    result = {endpoint.name} if endpoint else set()
    remaining = max(1, int(chain_count if chain_count is not None else mapping.ik_chain_count))
    while bone and remaining > 0:
        result.add(bone.name)
        bone = bone.parent
        remaining -= 1
    return result


def _ik_solver_pose_bone(target_obj, mapping):
    endpoint = target_obj.pose.bones.get(mapping.target_bone)
    if endpoint and endpoint.parent and endpoint.parent.parent:
        return endpoint.parent
    return endpoint


def _ik_bend_direction(upper_head, joint, tip):
    axis = tip - upper_head
    if axis.length_squared < 1.0e-10:
        return None
    bend = joint - upper_head
    bend -= axis * bend.dot(axis) / axis.length_squared
    if bend.length_squared < axis.length_squared * 1.0e-8:
        return None
    return bend.normalized()


def _source_ik_bend_direction(evaluated_source, target_obj, source_name):
    endpoint = evaluated_source.pose.bones.get(source_name)
    lower = endpoint.parent if endpoint else None
    upper = lower.parent if lower else None
    if not upper:
        return None
    source_direction = _ik_bend_direction(upper.head, lower.head, lower.tail)
    if source_direction is None:
        return None
    source_world = evaluated_source.matrix_world.to_3x3() @ source_direction
    target_local = target_obj.matrix_world.inverted_safe().to_3x3() @ source_world
    return target_local.normalized() if target_local.length_squared > 1.0e-10 else None


def _ik_pole_position(solver, distance_factor=1.0, source_direction=None,
                      previous=None, forward_direction=None):
    upper = solver.parent if solver else None
    if not solver or not upper:
        return None, None
    direction = _ik_bend_direction(upper.head, solver.head, solver.tail)
    axis = solver.tail - upper.head
    forward = None
    if forward_direction is not None and axis.length_squared > 1.0e-10:
        forward = forward_direction - axis * forward_direction.dot(axis) / axis.length_squared
        if forward.length_squared > 1.0e-10:
            forward.normalize()
            if distance_factor < 0:
                forward.negate()
        else:
            forward = None
    if source_direction is not None and axis.length_squared > 1.0e-10:
        source_plane = source_direction - axis * source_direction.dot(axis) / axis.length_squared
        if source_plane.length_squared > 1.0e-10:
            direction = source_plane.normalized()
    if forward is not None and direction is not None and direction.dot(forward) < 0:
        # A signed length selects the front/back hemisphere. Source motion
        # still steers the pole within that hemisphere.
        direction.negate()
    if direction is None and forward is not None:
        direction = forward.copy()
    if direction is None and previous is not None:
        direction = previous.copy()
    if direction is None:
        direction = axis.cross(Vector((0.0, 0.0, 1.0)))
        if direction.length_squared < 1.0e-10:
            direction = axis.cross(Vector((0.0, 1.0, 0.0)))
        direction.normalize()
    if previous is not None and direction.dot(previous) < -0.7:
        # A fully straight frame has no reliable bend plane. Preserve the
        # previous pole hemisphere instead of causing a one-frame IK flip.
        if _ik_bend_direction(upper.head, solver.head, solver.tail) is None:
            direction = previous.copy()
    # Zero is the joint in the UI; a tiny solver offset avoids a degenerate
    # pole vector while evaluating the IK constraint.
    distance = solver.length * max(abs(distance_factor), 0.02)
    return solver.head + direction * distance, direction


def _refine_pole_position(context, owner, desired_joint, upper_head,
                          tip, pole, initial_position):
    axis = tip - upper_head
    if axis.length_squared < 1.0e-10:
        return initial_position
    axis.normalize()
    tolerance = max(owner.length * 0.02, 1.0e-5)
    best_position = initial_position
    best_error = float("inf")
    pole_rest = pole.bone.matrix_local.copy()
    base_vector = initial_position - upper_head
    best_angle = 0.0
    for angles in (
        (index * math.pi / 6 for index in range(12)),
        (best_angle + index * math.pi / 36 for index in range(-5, 6)),
    ):
        for angle in angles:
            position = upper_head + Quaternion(axis, angle) @ base_vector
            pole_matrix = pole_rest.copy()
            pole_matrix.translation = position
            pole.matrix = pole_matrix
            context.view_layer.update()
            error = (owner.head - desired_joint).length
            if error < best_error:
                best_error = error
                best_position = position.copy()
                best_angle = angle
            if error <= tolerance:
                break
        if best_error <= tolerance:
            break
    pole_matrix = pole_rest.copy()
    pole_matrix.translation = best_position
    pole.matrix = pole_matrix
    context.view_layer.update()
    return best_position


def _set_scene_frame(scene, frame):
    """Evaluate integer and fractional Action keys without losing subframes."""
    whole = math.floor(frame)
    scene.frame_set(whole, subframe=float(frame - whole))


def _fbr_ik_constraint(pose_bone):
    return next(
        (
            constraint
            for constraint in pose_bone.constraints
            if constraint.type == "IK" and constraint.name.startswith("FBR IK")
        ),
        None,
    )


def _existing_ik_for_endpoint(target_obj, endpoint_name):
    """Find one same-armature IK for an endpoint without changing it."""
    endpoint = target_obj.pose.bones.get(endpoint_name)
    if not endpoint:
        return None
    candidates = []
    for owner in (endpoint.parent, endpoint):
        if not owner:
            continue
        owner_candidates = []
        for constraint in owner.constraints:
            if constraint.type != "IK" or constraint.mute or constraint.influence <= 0:
                continue
            if constraint.target != target_obj or not constraint.subtarget:
                raise RuntimeError(
                    f"{owner.name} 的 IK 使用外部或未指定控制器；不會寫入外部物件"
                )
            control = target_obj.pose.bones.get(constraint.subtarget)
            if not control:
                raise RuntimeError(f"{owner.name} 的 IK 控制骨不存在：{constraint.subtarget}")
            pole = None
            if constraint.pole_target:
                if constraint.pole_target != target_obj:
                    raise RuntimeError(f"{owner.name} 的 IK Pole 位於外部物件；不會寫入")
                pole = target_obj.pose.bones.get(constraint.pole_subtarget)
                if not pole:
                    raise RuntimeError(f"{owner.name} 的 IK Pole 骨不存在")
            owner_candidates.append((owner, constraint, control, pole))
        if owner_candidates:
            # A foot can itself own the toes' IK while its parent owns the
            # foot IK. Prefer the parent chain for this mapped endpoint.
            candidates = owner_candidates
            break
    if len(candidates) > 1:
        raise RuntimeError(f"{endpoint_name} 找到多組 IK，請先明確選擇一組")
    return candidates[0] if candidates else None


def _existing_ik_for_mapping(target_obj, mapping):
    return _existing_ik_for_endpoint(target_obj, mapping.target_bone)


def source_has_ik(source_obj, mappings):
    """Whether a mapped source endpoint has a usable same-armature IK."""
    if not source_obj or source_obj.type != "ARMATURE":
        return False
    for mapping in mappings:
        try:
            if _existing_ik_for_endpoint(source_obj, mapping.source_bone):
                return True
        except RuntimeError:
            continue
    return False


def _evaluated_source_basis(source_obj, source_pose):
    """Bake evaluated constraints into a local bone transform for FK transfer."""
    return source_obj.convert_space(
        pose_bone=source_pose, matrix=source_pose.matrix,
        from_space="POSE", to_space="LOCAL",
    )


def _source_pole_direction(evaluated_source, target_obj, binding):
    owner, _constraint, _control, pole = binding
    if pole is None:
        return None
    direction = evaluated_source.matrix_world.to_3x3() @ (pole.head - owner.head)
    direction = target_obj.matrix_world.inverted_safe().to_3x3() @ direction
    return direction.normalized() if direction.length_squared > 1.0e-10 else None


def _ik_endpoint_priority(mapping, owner_name):
    name = normalize_bone_name(mapping.target_bone)
    if any(part in name for part in ("foot", "hand", "wrist", "ankle")):
        return 3
    return 2 if mapping.target_bone != owner_name else 1


def existing_ik_for_row(target_obj, mappings, mapping):
    """Resolve a chain member to its mapped endpoint, not its solver bone.

    Blender stores an IK constraint on the lower limb for a hand/foot chain.
    That does not make the lower-limb mapping a separate IK endpoint.
    """
    by_constraint = {}
    for candidate in mappings:
        if not candidate.target_bone:
            continue
        try:
            binding = _existing_ik_for_mapping(target_obj, candidate)
        except RuntimeError:
            if candidate.as_pointer() == mapping.as_pointer():
                raise
            continue
        if not binding:
            continue
        owner, constraint, _control, _pole = binding
        identity = constraint.as_pointer()
        previous = by_constraint.get(identity)
        if previous is None or _ik_endpoint_priority(
            candidate, owner.name,
        ) > _ik_endpoint_priority(previous[0], owner.name):
            by_constraint[identity] = (candidate, binding)
    for driver, binding in by_constraint.values():
        owner, constraint, _control, _pole = binding
        if mapping.target_bone in _ik_chain_names(
            target_obj, driver, owner.name, constraint.chain_count,
        ):
            return driver, binding, driver.as_pointer() != mapping.as_pointer()
    return None, None, False


def _source_fk_matrix(pose_bone, cache):
    """Calculate the unconstrained pose from input bases for an IK residual."""
    if pose_bone.name in cache:
        return cache[pose_bone.name]
    rest = pose_bone.bone.matrix_local
    if pose_bone.parent:
        parent_matrix = _source_fk_matrix(pose_bone.parent, cache)
        matrix = (
            parent_matrix @ pose_bone.parent.bone.matrix_local.inverted_safe()
            @ rest @ pose_bone.matrix_basis
        )
    else:
        matrix = rest @ pose_bone.matrix_basis
    cache[pose_bone.name] = matrix
    return matrix


def _source_ik_residual(source_obj, evaluated_source, source_name, target_obj):
    source_pose = evaluated_source.pose.bones.get(source_name)
    if not source_pose:
        return Matrix.Identity(4)
    fk_matrix = _source_fk_matrix(source_pose, {})
    source_delta = source_pose.matrix @ fk_matrix.inverted_safe()
    world_delta = source_obj.matrix_world @ source_delta @ source_obj.matrix_world.inverted_safe()
    target_delta = target_obj.matrix_world.inverted_safe() @ world_delta @ target_obj.matrix_world
    return target_delta


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
    # Pose matrices stay at rest while an armature is in Edit Mode.  The
    # properties may still accept keyframes, making a bake look successful
    # while all IK controls remain stationary (for example in 1008_1.blend).
    if target_obj.mode == "EDIT":
        if context.view_layer.objects.active != target_obj:
            raise RuntimeError("Target 正處於編輯模式；請先切回物件或姿勢模式")
        bpy.ops.object.mode_set(mode="OBJECT")
    source_obj = bpy.data.objects.get(source_file.source_object)
    source_action = source_action_for_clip(clip)
    if not source_obj or not source_action:
        raise RuntimeError(f"找不到來源：{source_file.display_name} / {clip.action_name}")
    mapping_file = mapping_source(settings, source_file)
    mappings = [item for item in mapping_file.mappings if item.target_bone]
    if not mappings:
        raise RuntimeError(f"{source_file.display_name} 沒有可用骨骼映射")

    existing_ik = {}
    if settings.ik_bake_mode == "EXISTING":
        for mapping in mappings:
            binding = _existing_ik_for_mapping(target_obj, mapping)
            if not binding:
                continue
            owner, constraint, _control, _pole = binding
            identity = constraint.as_pointer()
            previous = existing_ik.get(identity)
            # The foot/hand endpoint is the child of the solver. Do not also
            # bake the same IK for a mapping directly on its lower limb.
            if previous is None or _ik_endpoint_priority(
                mapping, owner.name,
            ) > _ik_endpoint_priority(previous[0], owner.name):
                existing_ik[identity] = (mapping, binding)
        if not existing_ik:
            raise RuntimeError("Target 沒有可沿用的同骨架 IK；請選姿勢 Bake 或先設定 IK")

    source_ik = {}
    source_ik_chain_names = set()
    if settings.use_source_ik and existing_ik:
        for mapping, _binding in existing_ik.values():
            source_name = mapping.source_bone
            if mirrored:
                counterpart = flip_bone_name(source_name)
                if counterpart in source_obj.pose.bones:
                    source_name = counterpart
            try:
                binding = _existing_ik_for_endpoint(source_obj, source_name)
            except RuntimeError:
                binding = None
            if binding:
                source_ik[mapping.as_pointer()] = binding
                owner, constraint, _control, _pole = binding
                source_ik_chain_names.add(source_name)
                bone = owner
                for _ in range(max(1, constraint.chain_count)):
                    if bone is None:
                        break
                    source_ik_chain_names.add(bone.name)
                    bone = bone.parent

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
    evaluation_action = pose_only_action(source_action)
    assign_action_and_slot(source_obj, evaluation_action)
    assign_action_and_slot(target_obj, out_action)
    frames = _frame_sequence(source_action, settings.key_mode)

    root_baselines = {}
    previous_pole_directions = {}
    muted_constraints = []
    root_target_names = {
        mapping.target_bone for mapping in mappings if mapping.is_root
    }
    global_correction = Quaternion(source_file.global_axis_correction).normalized()
    applied_scale = float(source_obj.get("_fbr_alignment_scale", 1.0))
    try:
        if not frames:
            return 0
        for frame_index, source_frame in enumerate(frames):
            _set_scene_frame(context.scene, source_frame)
            context.view_layer.update()
            evaluated_source = source_obj.evaluated_get(
                context.evaluated_depsgraph_get()
            )
            target_frame = out_start + (source_frame - frames[0])
            ik_mappings = []
            ik_chain_names = set()
            muted_constraints = []
            if settings.ik_bake_mode == "EXISTING":
                bindings = (
                    (mapping, *binding) for mapping, binding in existing_ik.values()
                )
            else:
                bindings = (
                    (
                        mapping,
                        _ik_solver_pose_bone(target_obj, mapping),
                        _fbr_ik_constraint(_ik_solver_pose_bone(target_obj, mapping))
                        if _ik_solver_pose_bone(target_obj, mapping) else None,
                        target_obj.pose.bones.get(mapping.ik_control_bone),
                        target_obj.pose.bones.get(mapping.ik_pole_bone)
                        if mapping.ik_use_pole else None,
                    )
                    for mapping in mappings
                    if mapping.ik_enabled and mapping.ik_control_bone
                )
            for mapping, owner, constraint, control, pole in bindings:
                endpoint = target_obj.pose.bones.get(mapping.target_bone)
                if not endpoint or not owner or not control or not constraint:
                    continue
                if settings.ik_bake_mode != "EXISTING":
                    constraint.target = target_obj
                    constraint.subtarget = mapping.ik_control_bone
                    constraint.pole_target = target_obj if pole else None
                    constraint.pole_subtarget = mapping.ik_pole_bone if pole else ""
                    constraint.chain_count = max(1, mapping.ik_chain_count)
                    constraint.iterations = mapping.ik_iterations
                    constraint.influence = mapping.ik_influence
                    constraint.use_tail = mapping.ik_use_tail
                    constraint.use_rotation = mapping.ik_use_rotation
                    constraint.use_stretch = mapping.ik_use_stretch
                ik_mappings.append((mapping, endpoint, owner, control, pole, constraint))
                ik_chain_names.update(_ik_chain_names(
                    target_obj, mapping, owner.name, constraint.chain_count,
                ))
                muted_constraints.append((constraint, constraint.mute))
                constraint.mute = True

            # Child IK controls inherit their parent's pose. Solve parent
            # controls first even when the mapping list is in another order.
            ik_mappings.sort(key=lambda item: len(item[1].parent_recursive))

            # The output action is evaluated as the scene advances.  Without
            # resetting every pose channel here, an IK control starts from the
            # previous frame's solved offset and the iterative correction adds
            # that offset again.  This produces the visible per-frame downward
            # drift, especially across several batch jobs.  Each sampled frame
            # must start from the same rest basis before FK mapping and IK solve.
            _clear_target_pose(target_obj)
            context.view_layer.update()

            # A large foot/hand IK chain can reach the root. Root motion must never become an
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

                # Without source-IK transfer, use the fully evaluated pose:
                # matrix_basis alone omits the motion produced by constraints.
                use_source_binding = (
                    settings.ik_bake_mode == "EXISTING"
                    and source_name in source_ik_chain_names
                )
                basis = (
                    source_pose.matrix_basis.copy() if use_source_binding
                    else _evaluated_source_basis(evaluated_source, source_pose)
                )
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
            desired_ik_transforms = {}
            for mapping, endpoint, owner, _control, _pole, _constraint in ik_mappings:
                pole_position = None
                desired_joint = owner.head.copy()
                upper_head = owner.parent.head.copy() if owner.parent else owner.head.copy()
                tip = owner.tail.copy()
                if pole:
                    source_name = mapping.source_bone
                    if mirrored:
                        counterpart = flip_bone_name(source_name)
                        if counterpart in evaluated_source.pose.bones:
                            source_name = counterpart
                    source_binding = source_ik.get(mapping.as_pointer())
                    source_bend = (
                        _source_pole_direction(evaluated_source, target_obj, source_binding)
                        if source_binding else None
                    ) or _source_ik_bend_direction(
                        evaluated_source, target_obj, source_name
                    )
                    from .operators import _character_basis
                    forward = _character_basis(
                        target_obj, source_file.target_forward_axis
                    ) @ Vector((0.0, -1.0, 0.0))
                    pole_distance = (
                        (pole.head - owner.head).length / max(owner.length, 1.0e-6)
                        if settings.ik_bake_mode == "EXISTING"
                        else mapping.ik_pole_length
                    )
                    pole_position, direction = _ik_pole_position(
                        owner, pole_distance, source_bend,
                        previous_pole_directions.get(mapping.as_pointer()),
                        forward,
                    )
                    if direction is not None:
                        previous_pole_directions[mapping.as_pointer()] = direction
                desired_matrix = endpoint.matrix.copy()
                if settings.ik_bake_mode == "EXISTING" and mapping.as_pointer() in source_ik:
                    source_name = mapping.source_bone
                    if mirrored:
                        counterpart = flip_bone_name(source_name)
                        if counterpart in evaluated_source.pose.bones:
                            source_name = counterpart
                    desired_matrix = (
                        _source_ik_residual(
                            source_obj, evaluated_source, source_name, target_obj,
                        ) @ desired_matrix
                    )
                desired_ik_transforms[mapping.as_pointer()] = (
                    desired_matrix, pole_position,
                    desired_joint, upper_head, tip,
                )
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
            for mapping, _endpoint, owner, control, pole, constraint in ik_mappings:
                if constraint.mute:
                    continue
                desired_matrix, pole_position, desired_joint, upper_head, tip = (
                    desired_ik_transforms[mapping.as_pointer()]
                )
                # ARP-style endpoint solving: bake the complete endpoint
                # transform to a separate control, while the IK constraint
                # lives on the lower limb.  This keeps the hand/foot at the
                # mapped pose without feeding the previous solved offset back
                # into the next frame.
                control.rotation_mode = "QUATERNION"
                control.matrix = desired_matrix
                context.view_layer.update()
                for data_path in ("location", "rotation_quaternion", "scale"):
                    control.keyframe_insert(
                        data_path=data_path,
                        frame=target_frame,
                        group=control.name,
                    )
                if pole and pole_position is not None:
                    _refine_pole_position(
                        context, owner, desired_joint,
                        upper_head, tip, pole, pole_position,
                    )
                    pole.keyframe_insert(
                        data_path="location",
                        frame=target_frame,
                        group=pole.name,
                    )
            # The solver rotates the lower limb to reach the IK control.
            # Preserve the mapped wrist/toe endpoint orientation after that
            # solve; otherwise the endpoint inherits an unintended forearm
            # or shin rotation even when its position is correct.
            for mapping, endpoint, _owner, _control, _pole, constraint in ik_mappings:
                if constraint.mute or _owner == endpoint or _fbr_ik_constraint(endpoint):
                    continue
                desired_matrix = desired_ik_transforms[mapping.as_pointer()][0]
                endpoint.rotation_mode = "QUATERNION"
                endpoint.matrix = desired_matrix
                context.view_layer.update()
                for data_path in ("location", "rotation_quaternion", "scale"):
                    endpoint.keyframe_insert(
                        data_path=data_path,
                        frame=target_frame,
                        group=endpoint.name,
                    )
            yield frame_index + 1
        out_action.use_fake_user = settings.fake_user
        return math.ceil(frames[-1] - frames[0]) + 1
    finally:
        for constraint, was_muted in muted_constraints:
            constraint.mute = was_muted
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
        if evaluation_action != source_action and evaluation_action.users == 0:
            bpy.data.actions.remove(evaluation_action)


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
    if any('pose.bones["FBR_IK_' in curve.data_path
           for curve in iter_action_fcurves(action)):
        # Channel-by-channel simplification changes the parent/pole/control
        # combination and is not pose-equivalent for an IK solve.
        return 0
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
