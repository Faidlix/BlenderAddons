import math
import os
import uuid

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, IntProperty, StringProperty
from bpy.types import Operator, OperatorFileListElement
from bpy_extras.io_utils import ImportHelper
from mathutils import Euler, Matrix

from .model import action_bone_names, armature_signature, flip_bone_name
from .retarget import (
    assign_action_and_slot,
    build_automatic_mapping,
    bake_clip,
    iter_bake_clip,
    mapping_source,
    output_name,
    simplify_action,
)


SUPPORTED_EXTENSIONS = {".fbx", ".glb", ".gltf", ".blend"}
TEMP_COLLECTION_NAME = "__FBR_Animation_Sources__"
_TARGET_BONE_ITEMS_CACHE = {}
_AXIS_PREVIEW_STATE = {}
_ANIMATION_PREVIEW_STATE = {}
_IK_EDIT_STATE = {}
_IK_UPDATE_GUARD = False
_AXIS_UPDATE_GUARD = False
IK_CONSTRAINT_NAME = "FBR IK"
IK_SHAPE_COLLECTION = "__FBR_IK_Shapes__"


def _bone_color_state(bones):
    return [
        (
            bone.name,
            bone.color.palette,
            tuple(bone.color.custom.normal),
            tuple(bone.color.custom.select),
            tuple(bone.color.custom.active),
        )
        for bone in bones
    ]


def _restore_bone_colors(bones, state):
    for name, palette, normal, select, active in state:
        bone = bones.get(name)
        if not bone:
            continue
        bone.color.palette = palette
        if palette == "CUSTOM":
            bone.color.custom.normal = normal
            bone.color.custom.select = select
            bone.color.custom.active = active


def _set_preview_bone_colors(bones):
    for bone in bones:
        bone.color.palette = "CUSTOM"
        bone.color.custom.normal = (1.0, 0.62, 0.02)
        bone.color.custom.select = (1.0, 0.78, 0.12)
        bone.color.custom.active = (1.0, 0.92, 0.35)


def _tag_view3d_redraw(context):
    window_manager = getattr(context, "window_manager", None)
    if not window_manager:
        return
    for window in window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def _end_axis_preview(context, source_file):
    state = _AXIS_PREVIEW_STATE.pop(source_file.uid, None)
    if not state:
        return
    source_obj = bpy.data.objects.get(state["source_name"])
    if source_obj:
        source_obj.hide_viewport = state["source_hide_viewport"]
        source_obj.hide_set(state["source_hidden"])
        source_obj.show_in_front = state["source_in_front"]
        source_obj.display_type = state["source_object_display"]
        source_obj.color = state["source_color"]
        source_obj.matrix_world = state["source_matrix_world"]
        source_data = source_obj.data
        source_data.display_type = state["source_armature_display"]
        source_data.show_axes = state["source_show_axes"]
        source_data.axes_position = state["source_axes_position"]
        source_data.pose_position = state["source_pose_position"]
        source_data.show_bone_colors = state["source_show_bone_colors"]
        _restore_bone_colors(source_data.bones, state["source_bone_colors"])
        _restore_bone_colors(source_obj.pose.bones, state["source_pose_bone_colors"])
        for bone_name, matrix_basis in state["source_pose_bases"].items():
            pose_bone = source_obj.pose.bones.get(bone_name)
            if pose_bone:
                pose_bone.matrix_basis = matrix_basis
        for bone_name, selection in state.get("source_selection", {}).items():
            bone = source_obj.pose.bones.get(bone_name)
            if bone:
                bone.select = selection
    target_obj = bpy.data.objects.get(state.get("target_name", ""))
    if target_obj:
        for bone_name, selection in state.get("target_selection", {}).items():
            bone = target_obj.pose.bones.get(bone_name)
            if bone:
                bone.select = selection
    if context:
        context.view_layer.update()
        _tag_view3d_redraw(context)


def _start_axis_preview(context, source_file, mapping):
    source_obj = bpy.data.objects.get(source_file.source_object)
    target_obj = _target_object(context.scene.fbr_settings)
    if not source_obj or not target_obj or not mapping.target_bone:
        return
    source_pose_bone = source_obj.pose.bones.get(mapping.source_bone)
    if not source_pose_bone:
        return
    bone_colors = []
    for bone in source_obj.data.bones:
        color = bone.color
        custom = color.custom
        bone_colors.append(
            (
                bone.name,
                color.palette,
                tuple(custom.normal),
                tuple(custom.select),
                tuple(custom.active),
            )
        )
    _AXIS_PREVIEW_STATE[source_file.uid] = {
        "source_name": source_obj.name,
        "source_hidden": source_obj.hide_get(),
        "source_hide_viewport": source_obj.hide_viewport,
        "source_in_front": source_obj.show_in_front,
        "source_object_display": source_obj.display_type,
        "source_color": tuple(source_obj.color),
        "source_matrix_world": source_obj.matrix_world.copy(),
        "source_armature_display": source_obj.data.display_type,
        "source_show_axes": source_obj.data.show_axes,
        "source_axes_position": source_obj.data.axes_position,
        "source_pose_position": source_obj.data.pose_position,
        "source_show_bone_colors": source_obj.data.show_bone_colors,
        "source_bone_colors": bone_colors,
        "source_pose_bone_colors": _bone_color_state(source_obj.pose.bones),
        "source_pose_bases": {
            pose_bone.name: pose_bone.matrix_basis.copy()
            for pose_bone in source_obj.pose.bones
        },
        "source_selection": {
            bone.name: bone.select for bone in source_obj.pose.bones
        },
        "target_selection": {
            bone.name: bone.select for bone in target_obj.pose.bones
        },
        "target_name": target_obj.name,
    }
    source_obj.hide_viewport = False
    source_obj.hide_set(False)
    source_obj.show_in_front = True
    source_obj.display_type = "WIRE"
    source_obj.color = (1.0, 0.70, 0.05, 0.35)
    source_obj.matrix_world = _root_aligned_preview_matrix(
        context.scene.fbr_settings,
        source_file,
        source_obj,
        target_obj,
        source_obj.matrix_world.copy(),
    )
    source_obj.data.display_type = "OCTAHEDRAL"
    source_obj.data.pose_position = "POSE"
    source_obj.data.show_axes = True
    source_obj.data.axes_position = 0.0
    source_obj.data.show_bone_colors = True
    _set_preview_bone_colors(source_obj.data.bones)
    _set_preview_bone_colors(source_obj.pose.bones)
    selected_mappings = [mapping]
    pair_name = flip_bone_name(mapping.source_bone)
    if pair_name != mapping.source_bone:
        pair = next(
            (item for item in source_file.mappings if item.source_bone == pair_name),
            None,
        )
        if pair:
            selected_mappings.append(pair)
    for obj in (source_obj, target_obj):
        for bone in obj.pose.bones:
            bone.select = False
    for selected in selected_mappings:
        source_bone = source_obj.pose.bones.get(selected.source_bone)
        target_bone = target_obj.pose.bones.get(selected.target_bone)
        if source_bone:
            source_bone.select = True
        if target_bone:
            target_bone.select = True
    _update_axis_preview(context, mapping)


def _update_axis_preview(context, changed_mapping=None):
    global _AXIS_UPDATE_GUARD
    if _AXIS_UPDATE_GUARD:
        return
    settings = getattr(getattr(context, "scene", None), "fbr_settings", None)
    if not settings:
        return
    for source_file in settings.files:
        state = _AXIS_PREVIEW_STATE.get(source_file.uid)
        if not source_file.axis_editing or not state:
            continue
        if changed_mapping is not None and not any(
            mapping.as_pointer() == changed_mapping.as_pointer()
            for mapping in source_file.mappings
        ):
            continue
        if changed_mapping is not None:
            pair_name = flip_bone_name(changed_mapping.source_bone)
            pair = next(
                (
                    mapping
                    for mapping in source_file.mappings
                    if mapping.source_bone == pair_name
                ),
                None,
            )
            if pair and pair_name != changed_mapping.source_bone:
                _AXIS_UPDATE_GUARD = True
                try:
                    pair.pair_rotation_offset = tuple(
                        changed_mapping.pair_rotation_offset
                    )
                finally:
                    _AXIS_UPDATE_GUARD = False
        source_obj = bpy.data.objects.get(state["source_name"])
        if not source_obj:
            continue
        for mapping in source_file.mappings:
            pose_bone = source_obj.pose.bones.get(mapping.source_bone)
            original = state["source_pose_bases"].get(mapping.source_bone)
            if not pose_bone or original is None:
                continue
            corrected = original.copy()
            corrected @= Euler(mapping.rotation_offset, "XYZ").to_matrix().to_4x4()
            corrected @= Euler(mapping.pair_rotation_offset, "XYZ").to_matrix().to_4x4()
            if mapping.transfer_location or mapping.is_root:
                corrected.translation *= mapping.location_multiplier
            pose_bone.matrix_basis = corrected
        target_obj = _target_object(settings)
        if target_obj:
            source_obj.matrix_world = _root_aligned_preview_matrix(
                settings,
                source_file,
                source_obj,
                target_obj,
                state["source_matrix_world"],
            )
        context.view_layer.update()
        _tag_view3d_redraw(context)


def _ik_shape_geometry(shape):
    if shape == "BOX":
        vertices = [
            (-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
            (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1),
        ]
        edges = [
            (0, 1), (1, 2), (2, 3), (3, 0),
            (4, 5), (5, 6), (6, 7), (7, 4),
            (0, 4), (1, 5), (2, 6), (3, 7),
        ]
        return vertices, edges
    if shape == "SQUARE":
        return [(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)], [
            (0, 1), (1, 2), (2, 3), (3, 0)
        ]
    segments = 24
    vertices = []
    edges = []
    planes = ("XY",) if shape == "CIRCLE" else ("XY", "XZ", "YZ")
    for plane in planes:
        offset = len(vertices)
        for index in range(segments):
            angle = math.tau * index / segments
            first, second = math.cos(angle), math.sin(angle)
            if plane == "XY":
                vertices.append((first, second, 0.0))
            elif plane == "XZ":
                vertices.append((first, 0.0, second))
            else:
                vertices.append((0.0, first, second))
            edges.append((offset + index, offset + (index + 1) % segments))
    return vertices, edges


def _ik_shape_object(shape):
    name = f"FBR_IK_SHAPE_{shape}"
    existing = bpy.data.objects.get(name)
    if existing:
        return existing
    collection = bpy.data.collections.get(IK_SHAPE_COLLECTION)
    if collection is None:
        collection = bpy.data.collections.new(IK_SHAPE_COLLECTION)
        bpy.context.scene.collection.children.link(collection)
    mesh = bpy.data.meshes.new(name + "_Mesh")
    vertices, edges = _ik_shape_geometry(shape)
    mesh.from_pydata(vertices, edges, [])
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.hide_render = True
    obj.hide_set(True)
    obj["_fbr_ik_shape"] = True
    return obj


def _set_active_object_mode(context, obj, mode):
    active = context.view_layer.objects.active
    if active and active.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for selected in list(context.selected_objects):
        selected.select_set(False)
    obj.hide_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode=mode)


def _ik_owner(context, mapping):
    settings = context.scene.fbr_settings
    target_obj = _target_object(settings)
    if target_obj and mapping.target_bone in target_obj.data.bones:
        return target_obj, mapping.target_bone
    for source_file in settings.files:
        if any(item.as_pointer() == mapping.as_pointer() for item in source_file.mappings):
            source_obj = bpy.data.objects.get(source_file.source_object)
            if source_obj and mapping.source_bone in source_obj.data.bones:
                return source_obj, mapping.source_bone
    return None, ""


def _add_ik_control_bone(context, owner_obj, owner_bone_name, mapping):
    if mapping.ik_control_bone and mapping.ik_control_bone in owner_obj.data.bones:
        return mapping.ik_control_bone
    owner_bone = owner_obj.data.bones.get(owner_bone_name)
    if not owner_bone:
        return ""
    matrix = owner_bone.matrix_local.copy()
    _set_active_object_mode(context, owner_obj, "EDIT")
    edit_bone = owner_obj.data.edit_bones.new(f"FBR_IK_{owner_bone_name}")
    edit_bone.matrix = matrix
    edit_bone.use_deform = False
    name = edit_bone.name
    bpy.ops.object.mode_set(mode="OBJECT")
    owner_obj.data.bones[name]["_fbr_ik_control"] = True
    owner_obj.data.bones[name].use_deform = False
    mapping.ik_control_bone = name
    return name


def _ik_constraint(pose_bone):
    return next(
        (
            constraint
            for constraint in pose_bone.constraints
            if constraint.type == "IK" and constraint.name.startswith(IK_CONSTRAINT_NAME)
        ),
        None,
    )


def _sync_ik_mapping(context, mapping):
    owner_obj, owner_bone_name = _ik_owner(context, mapping)
    if not owner_obj or not owner_bone_name:
        return
    owner = owner_obj.pose.bones.get(owner_bone_name)
    if not owner:
        return
    constraint = _ik_constraint(owner)
    if mapping.ik_enabled and constraint is None:
        control_name = _add_ik_control_bone(
            context, owner_obj, owner_bone_name, mapping
        )
        if not control_name:
            return
        constraint = owner.constraints.new("IK")
        constraint.name = IK_CONSTRAINT_NAME
        constraint.target = owner_obj
        constraint.subtarget = control_name
    if not mapping.ik_enabled or constraint is None:
        return
    constraint.target = owner_obj
    constraint.subtarget = mapping.ik_control_bone
    constraint.chain_count = mapping.ik_chain_count
    constraint.iterations = mapping.ik_iterations
    constraint.influence = mapping.ik_influence
    constraint.use_tail = mapping.ik_use_tail
    constraint.use_rotation = mapping.ik_use_rotation
    constraint.use_stretch = mapping.ik_use_stretch
    control = owner_obj.pose.bones.get(mapping.ik_control_bone)
    if control:
        control.custom_shape = _ik_shape_object(mapping.ik_shape)
        scale = mapping.ik_shape_scale
        control.custom_shape_scale_xyz = (scale, scale, scale)
        owner_obj.show_in_front = True
        owner_obj.hide_set(False)
        for bone in owner_obj.pose.bones:
            bone.select = False
        control_bone = owner_obj.pose.bones.get(mapping.ik_control_bone)
        if control_bone:
            control_bone.select = True


def _delete_ik_mapping(context, mapping):
    owner_obj, owner_bone_name = _ik_owner(context, mapping)
    if not owner_obj:
        mapping.ik_enabled = False
        mapping.ik_control_bone = ""
        return
    owner = owner_obj.pose.bones.get(owner_bone_name)
    if owner:
        constraint = _ik_constraint(owner)
        if constraint:
            owner.constraints.remove(constraint)
    control_name = mapping.ik_control_bone
    if control_name and control_name in owner_obj.data.bones:
        bone = owner_obj.data.bones[control_name]
        if bone.get("_fbr_ik_control", False):
            _set_active_object_mode(context, owner_obj, "EDIT")
            edit_bone = owner_obj.data.edit_bones.get(control_name)
            if edit_bone:
                owner_obj.data.edit_bones.remove(edit_bone)
            bpy.ops.object.mode_set(mode="OBJECT")
    mapping.ik_enabled = False
    mapping.ik_control_bone = ""
    context.view_layer.update()


def _update_ik_preview(context, changed_mapping=None):
    global _IK_UPDATE_GUARD
    if _IK_UPDATE_GUARD or changed_mapping is None:
        return
    if not changed_mapping.ik_enabled:
        return
    _IK_UPDATE_GUARD = True
    try:
        _sync_ik_mapping(context, changed_mapping)
        settings = context.scene.fbr_settings
        for source_file in settings.files:
            if not any(
                item.as_pointer() == changed_mapping.as_pointer()
                for item in source_file.mappings
            ):
                continue
            pair_name = flip_bone_name(changed_mapping.source_bone)
            pair = next(
                (item for item in source_file.mappings if item.source_bone == pair_name),
                None,
            )
            if pair and pair_name != changed_mapping.source_bone:
                for prop in (
                    "ik_chain_count", "ik_iterations", "ik_influence",
                    "ik_use_tail", "ik_use_rotation", "ik_use_stretch",
                    "ik_shape", "ik_shape_scale",
                ):
                    setattr(pair, prop, getattr(changed_mapping, prop))
                pair.ik_enabled = changed_mapping.ik_enabled
                _sync_ik_mapping(context, pair)
            break
        context.view_layer.update()
        _tag_view3d_redraw(context)
    finally:
        _IK_UPDATE_GUARD = False


def _temporary_collection(scene):
    collection = bpy.data.collections.get(TEMP_COLLECTION_NAME)
    if collection is None:
        collection = bpy.data.collections.new(TEMP_COLLECTION_NAME)
    if collection.name not in scene.collection.children:
        scene.collection.children.link(collection)
    collection.hide_render = True
    return collection


def _move_to_temporary_collection(scene, obj):
    collection = _temporary_collection(scene)
    for owner in list(obj.users_collection):
        owner.objects.unlink(obj)
    if obj.name not in collection.objects:
        collection.objects.link(obj)
    obj.hide_render = True
    obj["_fbr_temp_source"] = True
    obj.hide_set(True)


def _cleanup_imported_sources(settings):
    context = bpy.context
    for source in settings.files:
        _end_axis_preview(context, source)
    object_names = {source.source_object for source in settings.files if source.source_object}
    action_names = {
        clip.action_name
        for source in settings.files
        for clip in source.clips
        if clip.action_name
    }
    for object_name in object_names:
        obj = bpy.data.objects.get(object_name)
        if obj is None:
            continue
        armature_data = obj.data if obj.type == "ARMATURE" else None
        bpy.data.objects.remove(obj, do_unlink=True)
        if armature_data and armature_data.users == 0:
            bpy.data.armatures.remove(armature_data)
    for action_name in action_names:
        action = bpy.data.actions.get(action_name)
        if action is not None:
            bpy.data.actions.remove(action)
    collection = bpy.data.collections.get(TEMP_COLLECTION_NAME)
    if collection is not None and not collection.objects:
        bpy.data.collections.remove(collection)
    settings.files.clear()


def _target_object(settings):
    obj = bpy.data.objects.get(settings.target_armature)
    return obj if obj and obj.type == "ARMATURE" else None


def _animation_action_state(obj):
    animation = obj.animation_data
    return {
        "action": animation.action if animation else None,
        "slot": animation.action_slot if animation and animation.action else None,
        "use_nla": animation.use_nla if animation else True,
        "pose_bases": {
            bone.name: bone.matrix_basis.copy()
            for bone in obj.pose.bones
        },
    }


def _restore_animation_action(obj, state):
    action = state["action"]
    if action:
        obj.animation_data_create()
        obj.animation_data.action = action
        slot = state["slot"]
        if slot:
            try:
                obj.animation_data.action_slot = slot
            except (RuntimeError, TypeError):
                pass
        obj.animation_data.use_nla = state["use_nla"]
        return
    if obj.animation_data:
        obj.animation_data.action = None
        obj.animation_data.use_nla = state["use_nla"]
    for bone_name, matrix_basis in state["pose_bases"].items():
        pose_bone = obj.pose.bones.get(bone_name)
        if pose_bone:
            pose_bone.matrix_basis = matrix_basis


def _root_aligned_preview_matrix(settings, source_file, source_obj, target_obj, original):
    preview = original @ Matrix.Scale(source_file.preview_scale, 4)
    mapping_file = mapping_source(settings, source_file)
    root_mapping = next(
        (
            mapping
            for mapping in mapping_file.mappings
            if mapping.is_root and mapping.target_bone
        ),
        None,
    )
    if root_mapping:
        source_root = source_obj.data.bones.get(root_mapping.source_bone)
        target_root = target_obj.data.bones.get(root_mapping.target_bone)
        if source_root and target_root:
            source_anchor = preview @ source_root.head_local
            target_anchor = target_obj.matrix_world @ target_root.head_local
            preview.translation += target_anchor - source_anchor
            return preview
    preview.translation = target_obj.matrix_world.translation
    return preview


def _armature_world_extent(obj, matrix_world=None, bone_names=None):
    matrix_world = matrix_world or obj.matrix_world
    bones = (
        [obj.data.bones[name] for name in bone_names if name in obj.data.bones]
        if bone_names
        else obj.data.bones
    )
    points = [
        matrix_world @ point
        for bone in bones
        for point in (bone.head_local, bone.tail_local)
    ]
    if not points:
        return 0.0
    minimum = points[0].copy()
    maximum = points[0].copy()
    for point in points[1:]:
        minimum.x = min(minimum.x, point.x)
        minimum.y = min(minimum.y, point.y)
        minimum.z = min(minimum.z, point.z)
        maximum.x = max(maximum.x, point.x)
        maximum.y = max(maximum.y, point.y)
        maximum.z = max(maximum.z, point.z)
    return (maximum - minimum).length


def _set_animation_preview_display(settings, source_file, source_obj, target_obj, state):
    state["source_display"] = {
        "hidden": source_obj.hide_get(),
        "hide_viewport": source_obj.hide_viewport,
        "show_in_front": source_obj.show_in_front,
        "display_type": source_obj.display_type,
        "color": tuple(source_obj.color),
        "matrix_world": source_obj.matrix_world.copy(),
        "armature_display": source_obj.data.display_type,
        "show_axes": source_obj.data.show_axes,
        "show_names": source_obj.data.show_names,
        "pose_position": source_obj.data.pose_position,
        "show_bone_colors": source_obj.data.show_bone_colors,
        "bone_colors": _bone_color_state(source_obj.data.bones),
        "pose_bone_colors": _bone_color_state(source_obj.pose.bones),
    }
    state["target_display"] = {
        "show_axes": target_obj.data.show_axes,
        "show_names": target_obj.data.show_names,
        "show_in_front": target_obj.show_in_front,
    }
    source_obj.hide_viewport = False
    source_obj.hide_set(False)
    source_obj.show_in_front = True
    source_obj.display_type = "WIRE"
    source_obj.color = (1.0, 0.70, 0.05, 0.35)
    source_obj.matrix_world = _root_aligned_preview_matrix(
        settings,
        source_file,
        source_obj,
        target_obj,
        state["source_display"]["matrix_world"],
    )
    source_obj.data.display_type = "OCTAHEDRAL"
    source_obj.data.pose_position = "POSE"
    source_obj.data.show_axes = True
    source_obj.data.show_names = False
    source_obj.data.show_bone_colors = True
    _set_preview_bone_colors(source_obj.data.bones)
    _set_preview_bone_colors(source_obj.pose.bones)
    target_obj.show_in_front = True
    target_obj.data.show_axes = True
    target_obj.data.show_names = False


def _restore_animation_preview_display(source_obj, target_obj, state):
    source = state["source_display"]
    source_obj.hide_viewport = source["hide_viewport"]
    source_obj.hide_set(source["hidden"])
    source_obj.show_in_front = source["show_in_front"]
    source_obj.display_type = source["display_type"]
    source_obj.color = source["color"]
    source_obj.matrix_world = source["matrix_world"]
    source_obj.data.display_type = source["armature_display"]
    source_obj.data.show_axes = source["show_axes"]
    source_obj.data.show_names = source["show_names"]
    source_obj.data.pose_position = source["pose_position"]
    source_obj.data.show_bone_colors = source["show_bone_colors"]
    _restore_bone_colors(source_obj.data.bones, source["bone_colors"])
    _restore_bone_colors(source_obj.pose.bones, source["pose_bone_colors"])
    target = state["target_display"]
    target_obj.data.show_axes = target["show_axes"]
    target_obj.data.show_names = target["show_names"]
    target_obj.show_in_front = target["show_in_front"]


def stop_animation_preview(context):
    state = _ANIMATION_PREVIEW_STATE.pop("active", None)
    settings = getattr(getattr(context, "scene", None), "fbr_settings", None)
    if settings:
        settings.preview_running = False
        settings.preview_source_uid = ""
    if not state:
        return
    screen = getattr(context, "screen", None)
    if screen and screen.is_animation_playing:
        try:
            bpy.ops.screen.animation_cancel(restore_frame=False)
        except RuntimeError:
            pass
    source_obj = bpy.data.objects.get(state["source_name"])
    target_obj = bpy.data.objects.get(state["target_name"])
    if source_obj and target_obj:
        _restore_animation_preview_display(source_obj, target_obj, state)
    if source_obj:
        _restore_animation_action(source_obj, state["source_action"])
    if target_obj:
        _restore_animation_action(target_obj, state["target_action"])
    scene = getattr(context, "scene", None)
    if scene:
        scene.frame_start = state["frame_start"]
        scene.frame_end = state["frame_end"]
        scene.frame_set(state["frame_current"])
    action = bpy.data.actions.get(state["preview_action"])
    if action:
        bpy.data.actions.remove(action)
    if context:
        context.view_layer.update()
        _tag_view3d_redraw(context)


def _start_animation_preview(context, source_file, play_animation=False):
    settings = context.scene.fbr_settings
    target_obj = _target_object(settings)
    source_obj = bpy.data.objects.get(source_file.source_object)
    try:
        clip_index = int(source_file.preview_clip or "0")
    except ValueError:
        clip_index = 0
    if not source_obj or not target_obj or not 0 <= clip_index < len(source_file.clips):
        return False, "找不到可預覽的來源、Target 或動畫"
    clip = source_file.clips[clip_index]
    source_action = bpy.data.actions.get(clip.action_name)
    if not source_action:
        return False, f"找不到 Action：{clip.action_name}"
    stop_animation_preview(context)
    state = {
        "source_name": source_obj.name,
        "target_name": target_obj.name,
        "source_uid": source_file.uid,
        "source_action": _animation_action_state(source_obj),
        "target_action": _animation_action_state(target_obj),
        "frame_start": context.scene.frame_start,
        "frame_end": context.scene.frame_end,
        "frame_current": context.scene.frame_current,
    }
    preview_action = bpy.data.actions.new(f"__FBR_PREVIEW__{source_file.uid}")
    state["preview_action"] = preview_action.name
    try:
        bake_clip(
            context,
            settings,
            source_file,
            clip,
            target_obj,
            preview_action,
            clip.frame_start,
            False,
        )
        preview_action.use_fake_user = False
        assign_action_and_slot(source_obj, source_action)
        assign_action_and_slot(target_obj, preview_action)
        source_obj.animation_data.use_nla = False
        target_obj.animation_data.use_nla = False
        context.scene.frame_start = math.floor(clip.frame_start)
        context.scene.frame_end = math.ceil(clip.frame_end)
        context.scene.frame_set(math.floor(clip.frame_start))
        _set_animation_preview_display(
            settings,
            source_file,
            source_obj,
            target_obj,
            state,
        )
        _ANIMATION_PREVIEW_STATE["active"] = state
        settings.preview_running = True
        settings.preview_source_uid = source_file.uid
        context.view_layer.update()
        _tag_view3d_redraw(context)
        screen = getattr(context, "screen", None)
        if play_animation and screen and not screen.is_animation_playing:
            try:
                bpy.ops.screen.animation_play()
            except RuntimeError:
                pass
        return True, ""
    except Exception:
        if "source_display" in state:
            _restore_animation_preview_display(source_obj, target_obj, state)
        _restore_animation_action(source_obj, state["source_action"])
        _restore_animation_action(target_obj, state["target_action"])
        if preview_action.name in bpy.data.actions:
            bpy.data.actions.remove(preview_action)
        context.scene.frame_start = state["frame_start"]
        context.scene.frame_end = state["frame_end"]
        context.scene.frame_set(state["frame_current"])
        raise


def restart_animation_preview(context, source_file):
    screen = getattr(context, "screen", None)
    was_playing = bool(screen and screen.is_animation_playing)
    success, _message = _start_animation_preview(
        context,
        source_file,
        play_animation=was_playing,
    )
    return success


def _mapping_axes_match(source_obj, target_obj, mapping, tolerance=math.radians(0.5)):
    if not source_obj or not target_obj or not mapping.target_bone:
        return False
    source_bone = source_obj.data.bones.get(mapping.source_bone)
    target_bone = target_obj.data.bones.get(mapping.target_bone)
    if not source_bone or not target_bone:
        return False
    source_rotation, target_rotation = _mapping_rest_rotations(
        source_obj,
        target_obj,
        source_bone,
        target_bone,
    )
    offset = (
        Euler(mapping.rotation_offset, "XYZ").to_quaternion()
        @ Euler(mapping.pair_rotation_offset, "XYZ").to_quaternion()
    )
    corrected = source_rotation @ offset
    return corrected.rotation_difference(target_rotation).angle <= tolerance


def _mapping_rest_rotations(source_obj, target_obj, source_bone, target_bone):
    if (
        source_bone.parent
        and target_bone.parent
        and source_bone.parent.name
        and target_bone.parent.name
    ):
        source_rotation = (
            source_bone.parent.matrix_local.inverted()
            @ source_bone.matrix_local
        ).to_quaternion()
        target_rotation = (
            target_bone.parent.matrix_local.inverted()
            @ target_bone.matrix_local
        ).to_quaternion()
    else:
        source_rotation = (
            source_obj.matrix_world.to_quaternion()
            @ source_bone.matrix_local.to_quaternion()
        )
        target_rotation = (
            target_obj.matrix_world.to_quaternion()
            @ target_bone.matrix_local.to_quaternion()
        )
    return source_rotation, target_rotation


def _target_bone_items(operator, context):
    items = [("0", "未指定", "清除目標骨骼")]
    if not context or not context.scene:
        return items
    settings = context.scene.fbr_settings
    target = _target_object(settings)
    if not target or not 0 <= operator.file_index < len(settings.files):
        return items
    source_file = settings.files[operator.file_index]
    assigned = {mapping.target_bone for mapping in source_file.mappings if mapping.target_bone}
    names = sorted(target.data.bones.keys(), key=lambda name: (name in assigned, name.lower()))
    for name in names:
        label = f"{name}  已被指定" if name in assigned else name
        items.append((name, label, f"指定到 {name}"))
    cache_key = (
        source_file.uid,
        tuple(sorted(assigned)),
        tuple(target.data.bones.keys()),
    )
    if cache_key not in _TARGET_BONE_ITEMS_CACHE:
        _TARGET_BONE_ITEMS_CACHE[cache_key] = items
    return _TARGET_BONE_ITEMS_CACHE[cache_key]


def _import_fbx(filepath):
    if hasattr(bpy.ops.wm, "fbx_import"):
        return bpy.ops.wm.fbx_import(filepath=filepath)
    return bpy.ops.import_scene.fbx(filepath=filepath)


def _import_gltf(filepath):
    if hasattr(bpy.ops.wm, "gltf_import"):
        return bpy.ops.wm.gltf_import(filepath=filepath)
    return bpy.ops.import_scene.gltf(filepath=filepath)


def _import_blend(filepath, collection):
    with bpy.data.libraries.load(filepath, link=False) as (data_from, data_to):
        data_to.objects = list(data_from.objects)
        data_to.actions = list(data_from.actions)
    imported = []
    for obj in data_to.objects:
        if obj and obj.type == "ARMATURE":
            collection.objects.link(obj)
            imported.append(obj)
    for obj in data_to.objects:
        if obj and obj.type != "ARMATURE" and obj.users == 0:
            bpy.data.objects.remove(obj)
    return imported


def _object_actions(obj):
    actions = []
    animation_data = obj.animation_data
    if not animation_data:
        return actions
    if animation_data.action:
        actions.append(animation_data.action)
    for track in animation_data.nla_tracks:
        for strip in track.strips:
            if strip.action and strip.action not in actions:
                actions.append(strip.action)
    return actions


def _compatible_actions(obj, actions):
    bone_names = set(obj.data.bones.keys())
    scored = []
    for action in actions:
        referenced = action_bone_names(action)
        score = len(referenced & bone_names)
        if score or not referenced:
            scored.append((score, action.name.lower(), action))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in scored]


def _animation_paths(directory):
    paths = []
    for root, folder_names, file_names in os.walk(directory):
        folder_names.sort(key=str.lower)
        for file_name in sorted(file_names, key=str.lower):
            path = os.path.join(root, file_name)
            if os.path.splitext(path)[1].lower() in SUPPORTED_EXTENSIONS:
                paths.append(path)
    return paths


def _selected_animation_paths(operator):
    directory = operator.directory or (
        os.path.dirname(operator.filepath) if operator.filepath else ""
    )
    candidates = []
    if operator.files:
        candidates.extend(
            os.path.join(directory, item.name)
            for item in operator.files
            if os.path.exists(os.path.join(directory, item.name))
        )
    if not candidates and operator.filepath and os.path.exists(operator.filepath):
        candidates.append(operator.filepath)
    if not candidates and directory:
        candidates.append(directory)

    paths = []
    for candidate in candidates:
        if os.path.isdir(candidate):
            paths.extend(_animation_paths(candidate))
        elif os.path.splitext(candidate)[1].lower() in SUPPORTED_EXTENSIONS:
            paths.append(candidate)
    unique = {}
    for path in paths:
        absolute = os.path.abspath(path)
        unique.setdefault(os.path.normcase(absolute), absolute)
    return sorted(unique.values(), key=str.lower)


def _source_entry(settings, filepath, obj, actions, suffix=""):
    entry = settings.files.add()
    entry.uid = uuid.uuid4().hex
    entry.filepath = filepath
    entry.file_type = os.path.splitext(filepath)[1].upper().lstrip(".")
    entry.display_name = os.path.basename(filepath)
    if suffix:
        stem, extension = os.path.splitext(entry.display_name)
        entry.display_name = f"{stem} [{suffix}]{extension}"
    entry.source_object = obj.name
    entry.signature = armature_signature(obj)
    for action in actions:
        clip = entry.clips.add()
        clip.action_name = action.name
        clip.frame_start = action.frame_range[0]
        clip.frame_end = action.frame_range[1]
    for index in range(max(0, len(settings.files) - 1)):
        previous = settings.files[index]
        if (
            previous.mapping_is_independent
            and previous.signature
            and previous.signature == entry.signature
        ):
            entry.reuse_mapping = previous.uid
            entry.mapping_expanded = False
            break
    else:
        entry.reuse_mapping = "SELF"
    return entry


class FBR_OT_import_files(Operator, ImportHelper):
    bl_idname = "fbr.import_files"
    bl_label = "加入動畫檔案"
    bl_description = "匯入檔案或整個資料夾；資料夾會包含所有子資料夾"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ""
    filter_glob: StringProperty(default="*.fbx;*.glb;*.gltf;*.blend", options={"HIDDEN"})
    directory: StringProperty(subtype="DIR_PATH")
    files: CollectionProperty(type=OperatorFileListElement)

    def execute(self, context):
        settings = context.scene.fbr_settings
        target_name = settings.target_armature
        target = _target_object(settings)
        paths = _selected_animation_paths(self)
        if not paths:
            self.report({"ERROR"}, "選取範圍內沒有 FBX、GLB、GLTF 或 BLEND 動畫檔")
            return {"CANCELLED"}
        imported_count = 0
        clip_count = 0
        for filepath in paths:
            extension = os.path.splitext(filepath)[1].lower()
            if extension not in SUPPORTED_EXTENSIONS:
                self.report({"WARNING"}, f"略過不支援檔案：{filepath}")
                continue
            before_objects = {obj.as_pointer() for obj in bpy.data.objects}
            before_actions = {action.as_pointer() for action in bpy.data.actions}
            try:
                if extension == ".fbx":
                    _import_fbx(filepath)
                elif extension in {".glb", ".gltf"}:
                    _import_gltf(filepath)
                else:
                    _import_blend(filepath, context.collection)
            except Exception as exc:
                for obj in list(bpy.data.objects):
                    if obj.as_pointer() not in before_objects:
                        bpy.data.objects.remove(obj, do_unlink=True)
                for action in list(bpy.data.actions):
                    if action.as_pointer() not in before_actions and action.users == 0:
                        bpy.data.actions.remove(action)
                self.report(
                    {"ERROR"},
                    f"無法讀取 {os.path.basename(filepath)}：{exc}",
                )
                continue
            all_new_objects = [
                obj
                for obj in bpy.data.objects
                if obj.as_pointer() not in before_objects
            ]
            new_objects = [obj for obj in all_new_objects if obj.type == "ARMATURE"]
            new_actions = [
                action for action in bpy.data.actions if action.as_pointer() not in before_actions
            ]
            if not new_objects:
                for obj in all_new_objects:
                    bpy.data.objects.remove(obj, do_unlink=True)
                for action in new_actions:
                    if action.users == 0:
                        bpy.data.actions.remove(action)
                self.report({"WARNING"}, f"沒有找到骨架：{os.path.basename(filepath)}")
                continue
            for index, obj in enumerate(new_objects):
                actions = _object_actions(obj)
                for action in _compatible_actions(obj, new_actions):
                    if action not in actions:
                        actions.append(action)
                if not actions and len(new_objects) == 1:
                    actions = list(new_actions)
                if not actions:
                    continue
                entry = _source_entry(
                    settings,
                    filepath,
                    obj,
                    actions,
                    suffix=obj.name if len(new_objects) > 1 else "",
                )
                if entry.reuse_mapping == "SELF" and target:
                    build_automatic_mapping(obj, target, entry.mappings)
                imported_count += 1
                clip_count += len(entry.clips)
            kept_armatures = {
                source.source_object
                for source in settings.files
                if source.filepath == filepath
            }
            kept_actions = {
                clip.action_name
                for source in settings.files
                if source.filepath == filepath
                for clip in source.clips
            }
            for obj in all_new_objects:
                if obj.type == "ARMATURE" and obj.name in kept_armatures:
                    _move_to_temporary_collection(context.scene, obj)
                else:
                    bpy.data.objects.remove(obj, do_unlink=True)
            for action in new_actions:
                if action.name in kept_actions:
                    action.use_fake_user = False
                else:
                    bpy.data.actions.remove(action)
        if not imported_count:
            if target_name and target_name in bpy.data.objects:
                settings.target_armature = target_name
            self.report({"ERROR"}, "沒有匯入可用的骨架動畫")
            return {"CANCELLED"}
        if target_name and target_name in bpy.data.objects:
            settings.target_armature = target_name
        self.report({"INFO"}, f"已加入 {imported_count} 組骨架、{clip_count} 個 Action")
        return {"FINISHED"}


class FBR_OT_import_folder(Operator):
    bl_idname = "fbr.import_folder"
    bl_label = "選擇檔案或資料夾"
    bl_description = "加入選取的動畫檔案，或遞迴加入選取資料夾與子資料夾內的動畫"
    bl_options = {"REGISTER", "UNDO"}

    filepath: StringProperty(subtype="FILE_PATH")
    filename: StringProperty(subtype="FILE_NAME")
    directory: StringProperty(subtype="DIR_PATH")
    files: CollectionProperty(type=OperatorFileListElement)
    filter_glob: StringProperty(
        default="*.fbx;*.glb;*.gltf;*.blend",
        options={"HIDDEN"},
    )
    filter_folder: BoolProperty(default=True, options={"HIDDEN"})

    def invoke(self, context, _event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, _context):
        selected = [{"name": item.name} for item in self.files]
        return bpy.ops.fbr.import_files(
            filepath=self.filepath,
            directory=self.directory,
            files=selected,
        )


class FBR_OT_clear_files(Operator):
    bl_idname = "fbr.clear_files"
    bl_label = "全部清空動畫檔"
    bl_description = "清除清單及所有暫存的來源骨架與 Action"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        _cleanup_imported_sources(context.scene.fbr_settings)
        return {"FINISHED"}


class FBR_OT_remove_file(Operator):
    bl_idname = "fbr.remove_file"
    bl_label = "移除動畫檔案"
    bl_description = "只移除這個動畫檔案與它匯入的動畫資料"
    bl_options = {"INTERNAL", "UNDO"}

    file_index: IntProperty()

    def execute(self, context):
        settings = context.scene.fbr_settings
        if not 0 <= self.file_index < len(settings.files):
            return {"CANCELLED"}
        stop_animation_preview(context)
        source = settings.files[self.file_index]
        removed_uid = source.uid
        _end_axis_preview(context, source)
        object_name = source.source_object
        action_names = {clip.action_name for clip in source.clips if clip.action_name}
        retained_actions = {
            clip.action_name
            for index, candidate in enumerate(settings.files)
            if index != self.file_index
            for clip in candidate.clips
        }
        for candidate in settings.files:
            if candidate.reuse_mapping == removed_uid:
                candidate.reuse_mapping = "SELF"
                candidate.mapping_is_independent = True
        settings.files.remove(self.file_index)
        obj = bpy.data.objects.get(object_name)
        if obj:
            armature = obj.data if obj.type == "ARMATURE" else None
            bpy.data.objects.remove(obj, do_unlink=True)
            if armature and armature.users == 0:
                bpy.data.armatures.remove(armature)
        for action_name in action_names - retained_actions:
            action = bpy.data.actions.get(action_name)
            if action and action.users == 0:
                bpy.data.actions.remove(action)
        collection = bpy.data.collections.get(TEMP_COLLECTION_NAME)
        if collection and not collection.objects:
            bpy.data.collections.remove(collection)
        settings.active_file_index = min(
            settings.active_file_index, max(0, len(settings.files) - 1)
        )
        return {"FINISHED"}


class FBR_OT_reset_all(Operator):
    bl_idname = "fbr.reset_all"
    bl_label = "全部重置"
    bl_description = "重設所有外掛選項，並清除暫存的來源骨架與 Action"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.fbr_settings
        _cleanup_imported_sources(settings)
        for prop in settings.bl_rna.properties:
            name = prop.identifier
            if name == "rna_type" or prop.is_readonly:
                continue
            try:
                if prop.type == "COLLECTION":
                    getattr(settings, name).clear()
                else:
                    settings.property_unset(name)
            except Exception:
                pass
        settings.target_armature = "0"
        settings.files.clear()
        self.report({"INFO"}, "Faidlix Bone Remap 已全部重置")
        return {"FINISHED"}


class FBR_OT_toggle_file(Operator):
    bl_idname = "fbr.toggle_file"
    bl_label = "切換整個檔案"
    bl_options = {"INTERNAL", "UNDO"}

    index: IntProperty()

    def execute(self, context):
        files = context.scene.fbr_settings.files
        if not 0 <= self.index < len(files):
            return {"CANCELLED"}
        source = files[self.index]
        enable = not all(clip.enabled for clip in source.clips)
        for clip in source.clips:
            clip.enabled = enable
        return {"FINISHED"}


class FBR_OT_toggle_clip_option(Operator):
    bl_idname = "fbr.toggle_clip_option"
    bl_label = "切換片段選項"
    bl_options = {"INTERNAL", "UNDO"}

    file_index: IntProperty()
    clip_index: IntProperty()
    option: StringProperty()

    def execute(self, context):
        files = context.scene.fbr_settings.files
        if not 0 <= self.file_index < len(files):
            return {"CANCELLED"}
        clips = files[self.file_index].clips
        if not 0 <= self.clip_index < len(clips):
            return {"CANCELLED"}
        clip = clips[self.clip_index]
        if self.option == "IN_PLACE":
            clip.in_place = not clip.in_place
        elif self.option in {"MIRROR", "COPY"}:
            clip.mirror_mode = "NONE" if clip.mirror_mode == self.option else self.option
        return {"FINISHED"}


class FBR_OT_select_target_bone(Operator):
    bl_idname = "fbr.select_target_bone"
    bl_label = "選擇目標骨骼"
    bl_description = "已指定的骨骼排在最後；選取時會與現有對應交換"
    bl_property = "target_bone"
    bl_options = {"REGISTER", "UNDO"}

    file_index: IntProperty()
    mapping_index: IntProperty()
    target_bone: EnumProperty(items=_target_bone_items)

    def invoke(self, context, _event):
        settings = context.scene.fbr_settings
        if not 0 <= self.file_index < len(settings.files):
            return {"CANCELLED"}
        mappings = settings.files[self.file_index].mappings
        if not 0 <= self.mapping_index < len(mappings):
            return {"CANCELLED"}
        current = mappings[self.mapping_index].target_bone
        self.target_bone = current if current else "0"
        context.window_manager.invoke_search_popup(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        settings = context.scene.fbr_settings
        if not 0 <= self.file_index < len(settings.files):
            return {"CANCELLED"}
        mappings = settings.files[self.file_index].mappings
        if not 0 <= self.mapping_index < len(mappings):
            return {"CANCELLED"}
        current = mappings[self.mapping_index]
        by_source = {mapping.source_bone: mapping for mapping in mappings}
        pair_name = flip_bone_name(current.source_bone)
        pair = by_source.get(pair_name) if pair_name != current.source_bone else None
        selected = "" if self.target_bone == "0" else self.target_bone

        def assign(mapping, target_name):
            previous = mapping.target_bone
            if target_name:
                for candidate in mappings:
                    if candidate.as_pointer() != mapping.as_pointer() and candidate.target_bone == target_name:
                        candidate.target_bone = previous
                        break
            mapping.target_bone = target_name

        assign(current, selected)
        target = _target_object(settings)
        selected_pair = flip_bone_name(selected) if selected else ""
        if (
            pair
            and selected_pair
            and selected_pair != selected
            and target
            and selected_pair in target.data.bones
        ):
            assign(pair, selected_pair)
        return {"FINISHED"}


class FBR_OT_clear_target_bone(Operator):
    bl_idname = "fbr.clear_target_bone"
    bl_label = "清除目標骨骼"
    bl_options = {"INTERNAL", "UNDO"}

    file_index: IntProperty()
    mapping_index: IntProperty()

    def execute(self, context):
        files = context.scene.fbr_settings.files
        if not 0 <= self.file_index < len(files):
            return {"CANCELLED"}
        mappings = files[self.file_index].mappings
        if not 0 <= self.mapping_index < len(mappings):
            return {"CANCELLED"}
        current = mappings[self.mapping_index]
        current.target_bone = ""
        pair_name = flip_bone_name(current.source_bone)
        if pair_name != current.source_bone:
            pair = next(
                (mapping for mapping in mappings if mapping.source_bone == pair_name),
                None,
            )
            if pair:
                pair.target_bone = ""
        return {"FINISHED"}


class FBR_OT_set_root(Operator):
    bl_idname = "fbr.set_root"
    bl_label = "設定為 Root"
    bl_description = "將這根骨頭設為唯一 Root"
    bl_options = {"INTERNAL", "UNDO"}

    file_index: IntProperty()
    mapping_index: IntProperty()

    def execute(self, context):
        files = context.scene.fbr_settings.files
        if not 0 <= self.file_index < len(files):
            return {"CANCELLED"}
        mappings = files[self.file_index].mappings
        if not 0 <= self.mapping_index < len(mappings):
            return {"CANCELLED"}
        for index, mapping in enumerate(mappings):
            mapping.is_root = index == self.mapping_index
        return {"FINISHED"}


class FBR_OT_align_source_rig(Operator):
    bl_idname = "fbr.align_source_rig"
    bl_label = "骨架縮放對位"
    bl_description = "依主要骨架與來源骨架的整體尺寸建立預覽縮放比例"
    bl_options = {"REGISTER", "UNDO"}

    file_index: IntProperty()

    def execute(self, context):
        settings = context.scene.fbr_settings
        target = _target_object(settings)
        if not target or not 0 <= self.file_index < len(settings.files):
            return {"CANCELLED"}
        source_file = settings.files[self.file_index]
        source_obj = bpy.data.objects.get(source_file.source_object)
        if not source_obj:
            return {"CANCELLED"}
        preview_state = _AXIS_PREVIEW_STATE.get(source_file.uid)
        animation_state = _ANIMATION_PREVIEW_STATE.get("active")
        source_matrix = (
            preview_state["source_matrix_world"]
            if preview_state
            else (
                animation_state["source_display"]["matrix_world"]
                if animation_state
                and animation_state.get("source_uid") == source_file.uid
                and "source_display" in animation_state
                else source_obj.matrix_world
            )
        )
        mapping_file = mapping_source(settings, source_file)
        source_bone_names = {
            mapping.source_bone
            for mapping in mapping_file.mappings
            if mapping.target_bone
        }
        target_bone_names = {
            mapping.target_bone
            for mapping in mapping_file.mappings
            if mapping.target_bone
        }
        source_length = max(
            _armature_world_extent(
                source_obj,
                source_matrix,
                source_bone_names,
            ),
            1.0e-8,
        )
        target_length = max(
            _armature_world_extent(target, bone_names=target_bone_names),
            1.0e-8,
        )
        source_file.preview_scale = target_length / source_length
        if source_file.axis_editing:
            mapping = source_file.mappings[source_file.active_mapping_index]
            _end_axis_preview(context, source_file)
            _start_axis_preview(context, source_file, mapping)
        elif (
            settings.preview_running
            and settings.preview_source_uid == source_file.uid
        ):
            restart_animation_preview(context, source_file)
        self.report({"INFO"}, f"預覽骨架縮放 {source_file.preview_scale:.3f} 倍")
        return {"FINISHED"}


class FBR_OT_auto_align_axes(Operator):
    bl_idname = "fbr.auto_align_axes"
    bl_label = "自動對軸向"
    bl_description = "一次將所有已映射來源骨頭的 Rest 軸向貼齊 Target"
    bl_options = {"REGISTER", "UNDO"}

    file_index: IntProperty()

    def execute(self, context):
        settings = context.scene.fbr_settings
        target_obj = _target_object(settings)
        if not target_obj or not 0 <= self.file_index < len(settings.files):
            return {"CANCELLED"}
        source_file = settings.files[self.file_index]
        source_obj = bpy.data.objects.get(source_file.source_object)
        mapping_file = mapping_source(settings, source_file)
        if not source_obj or not mapping_file:
            return {"CANCELLED"}

        aligned = 0
        for mapping in mapping_file.mappings:
            if not mapping.target_bone:
                continue
            source_bone = source_obj.data.bones.get(mapping.source_bone)
            target_bone = target_obj.data.bones.get(mapping.target_bone)
            if not source_bone or not target_bone:
                continue
            source_rotation, target_rotation = _mapping_rest_rotations(
                source_obj,
                target_obj,
                source_bone,
                target_bone,
            )
            mapping.rotation_offset = (
                source_rotation.inverted() @ target_rotation
            ).to_euler("XYZ")
            aligned += 1

        if source_file.axis_editing:
            _update_axis_preview(context)
        _tag_view3d_redraw(context)
        self.report({"INFO"}, f"已自動對齊 {aligned} 根骨頭軸向")
        return {"FINISHED"} if aligned else {"CANCELLED"}


class FBR_OT_preview_animation(Operator):
    bl_idname = "fbr.preview_animation"
    bl_label = "預覽動畫"
    bl_description = "暫時顯示來源骨架與完整重定向結果，不保留 Action 或 Key"
    bl_options = {"INTERNAL"}

    file_index: IntProperty()
    action: EnumProperty(
        items=(
            ("SHOW", "預覽", "顯示來源與重定向骨架，不自動播放"),
            ("HIDE", "隱藏預覽", "隱藏預覽骨架並還原原本狀態"),
            ("PLAY", "播放動畫", "顯示預覽骨架並播放動畫"),
            ("PAUSE", "停止播放", "停止動畫，保留預覽骨架"),
            ("START", "預覽動畫", "相容舊版：顯示並播放動畫"),
            ("STOP", "停止預覽", "相容舊版：停止預覽並還原狀態"),
        ),
        default="SHOW",
    )

    def execute(self, context):
        if self.action in {"HIDE", "STOP"}:
            stop_animation_preview(context)
            return {"FINISHED"}
        settings = context.scene.fbr_settings
        if not 0 <= self.file_index < len(settings.files):
            return {"CANCELLED"}
        screen = getattr(context, "screen", None)
        preview_active = (
            settings.preview_running
            and settings.preview_source_uid == settings.files[self.file_index].uid
        )
        if self.action == "PAUSE":
            if screen and screen.is_animation_playing:
                try:
                    bpy.ops.screen.animation_cancel(restore_frame=False)
                except RuntimeError:
                    return {"CANCELLED"}
            _tag_view3d_redraw(context)
            return {"FINISHED"}
        if self.action == "PLAY" and preview_active:
            if screen and not screen.is_animation_playing:
                try:
                    bpy.ops.screen.animation_play()
                except RuntimeError:
                    return {"CANCELLED"}
            _tag_view3d_redraw(context)
            return {"FINISHED"}
        try:
            success, message = _start_animation_preview(
                context,
                settings.files[self.file_index],
                play_animation=self.action in {"PLAY", "START"},
            )
        except Exception as exc:
            self.report({"ERROR"}, f"預覽失敗：{exc}")
            return {"CANCELLED"}
        if not success:
            self.report({"WARNING"}, message)
            return {"CANCELLED"}
        return {"FINISHED"}


class FBR_OT_clear_target_animation(Operator):
    bl_idname = "fbr.clear_target_animation"
    bl_label = "刪除所有動畫"
    bl_description = "清除主要骨架上的 Action 與 NLA 動畫，不刪除動畫資料塊"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        target = _target_object(context.scene.fbr_settings)
        if not target:
            return {"CANCELLED"}
        stop_animation_preview(context)
        target.animation_data_clear()
        identity = Matrix.Identity(4)
        for pose_bone in target.pose.bones:
            pose_bone.matrix_basis = identity
        context.view_layer.update()
        _tag_view3d_redraw(context)
        self.report({"INFO"}, f"已清除 {target.name} 的所有動畫")
        return {"FINISHED"}


class FBR_OT_ik_settings(Operator):
    bl_idname = "fbr.ik_settings"
    bl_label = "設定 IK"
    bl_options = {"INTERNAL", "UNDO"}

    file_index: IntProperty()
    mapping_index: IntProperty(default=-1)
    action: EnumProperty(
        items=(
            ("START", "設定 IK", "進入 IK 設定模式"),
            ("RESET", "刪除 IK", "刪除 IK Constraint 與控制骨"),
            ("CANCEL", "取消", "恢復進入設定前的狀態"),
            ("OK", "確認", "保留目前 IK 設定"),
        )
    )

    @staticmethod
    def _backup(source, mapping):
        source.ik_backup_enabled = mapping.ik_enabled
        source.ik_backup_control_bone = mapping.ik_control_bone
        source.ik_backup_chain_count = mapping.ik_chain_count
        source.ik_backup_iterations = mapping.ik_iterations
        source.ik_backup_influence = mapping.ik_influence
        source.ik_backup_use_tail = mapping.ik_use_tail
        source.ik_backup_use_rotation = mapping.ik_use_rotation
        source.ik_backup_use_stretch = mapping.ik_use_stretch
        source.ik_backup_shape = mapping.ik_shape
        source.ik_backup_shape_scale = mapping.ik_shape_scale

    @staticmethod
    def _restore(source, mapping):
        mapping.ik_chain_count = source.ik_backup_chain_count
        mapping.ik_iterations = source.ik_backup_iterations
        mapping.ik_influence = source.ik_backup_influence
        mapping.ik_use_tail = source.ik_backup_use_tail
        mapping.ik_use_rotation = source.ik_backup_use_rotation
        mapping.ik_use_stretch = source.ik_backup_use_stretch
        mapping.ik_shape = source.ik_backup_shape
        mapping.ik_shape_scale = source.ik_backup_shape_scale
        mapping.ik_control_bone = source.ik_backup_control_bone
        mapping.ik_enabled = source.ik_backup_enabled

    def execute(self, context):
        files = context.scene.fbr_settings.files
        if not 0 <= self.file_index < len(files):
            return {"CANCELLED"}
        source = files[self.file_index]
        mapping_index = self.mapping_index if self.mapping_index >= 0 else source.active_mapping_index
        if not 0 <= mapping_index < len(source.mappings):
            return {"CANCELLED"}
        mapping = source.mappings[mapping_index]
        pair_name = flip_bone_name(mapping.source_bone)
        pair = next(
            (item for item in source.mappings if item.source_bone == pair_name),
            None,
        )
        if pair_name == mapping.source_bone:
            pair = None
        if self.action == "START":
            for candidate in files:
                _end_axis_preview(context, candidate)
                candidate.axis_editing = False
                candidate.ik_editing = False
                candidate.ik_editing = False
            source.active_mapping_index = mapping_index
            source.axis_locked_mapping_index = mapping_index
            self._backup(source, mapping)
            _IK_EDIT_STATE[source.uid] = {
                item.as_pointer(): {
                    prop: getattr(item, prop)
                    for prop in (
                        "ik_enabled", "ik_control_bone", "ik_chain_count",
                        "ik_iterations", "ik_influence", "ik_use_tail",
                        "ik_use_rotation", "ik_use_stretch", "ik_shape",
                        "ik_shape_scale",
                    )
                }
                for item in (mapping, pair)
                if item
            }
            source.ik_editing = True
            mapping.ik_enabled = True
            _sync_ik_mapping(context, mapping)
            if pair:
                pair.ik_enabled = True
                _update_ik_preview(context, mapping)
        elif self.action == "RESET":
            _delete_ik_mapping(context, mapping)
            if pair:
                _delete_ik_mapping(context, pair)
        elif self.action == "CANCEL":
            _delete_ik_mapping(context, mapping)
            if pair:
                _delete_ik_mapping(context, pair)
            backups = _IK_EDIT_STATE.pop(source.uid, {})
            for item in (mapping, pair):
                if not item:
                    continue
                backup = backups.get(item.as_pointer())
                if not backup:
                    continue
                for prop, value in backup.items():
                    setattr(item, prop, value)
                if item.ik_enabled:
                    _sync_ik_mapping(context, item)
            source.ik_editing = False
        elif self.action == "OK":
            if mapping.ik_enabled:
                _sync_ik_mapping(context, mapping)
            if pair and pair.ik_enabled:
                _sync_ik_mapping(context, pair)
            _IK_EDIT_STATE.pop(source.uid, None)
            source.ik_editing = False
        _tag_view3d_redraw(context)
        return {"FINISHED"}


class FBR_OT_delete_ik(Operator):
    bl_idname = "fbr.delete_ik"
    bl_label = "刪除 IK"
    bl_description = "刪除 IK Constraint 與非 Deform 控制骨"
    bl_options = {"INTERNAL", "UNDO"}

    file_index: IntProperty()
    mapping_index: IntProperty(default=-1)

    def invoke(self, context, _event):
        return context.window_manager.invoke_confirm(self, _event)

    def execute(self, context):
        files = context.scene.fbr_settings.files
        if not 0 <= self.file_index < len(files):
            return {"CANCELLED"}
        source = files[self.file_index]
        index = self.mapping_index if self.mapping_index >= 0 else source.active_mapping_index
        if not 0 <= index < len(source.mappings):
            return {"CANCELLED"}
        mapping = source.mappings[index]
        _delete_ik_mapping(context, mapping)
        pair_name = flip_bone_name(mapping.source_bone)
        if pair_name != mapping.source_bone:
            pair = next(
                (item for item in source.mappings if item.source_bone == pair_name),
                None,
            )
            if pair:
                _delete_ik_mapping(context, pair)
        _IK_EDIT_STATE.pop(source.uid, None)
        source.ik_editing = False
        _tag_view3d_redraw(context)
        return {"FINISHED"}


class FBR_OT_axis_correction(Operator):
    bl_idname = "fbr.axis_correction"
    bl_label = "軸向修正"
    bl_options = {"INTERNAL", "UNDO"}

    file_index: IntProperty()
    mapping_index: IntProperty(default=-1)
    action: EnumProperty(
        items=(
            ("START", "軸向修正", "進入軸向修正模式"),
            ("RESET", "Reset", "重設這根骨骼的修正值"),
            ("AUTO", "自動對軸向", "只預覽目前骨頭的自動軸向校正"),
            ("CANCEL", "Cancel", "還原開始編輯前的值"),
            ("OK", "OK", "保留修正值"),
        )
    )

    def execute(self, context):
        files = context.scene.fbr_settings.files
        if not 0 <= self.file_index < len(files):
            return {"CANCELLED"}
        source = files[self.file_index]
        mapping_index = (
            self.mapping_index if self.mapping_index >= 0 else source.active_mapping_index
        )
        if not source.mappings or not 0 <= mapping_index < len(source.mappings):
            return {"CANCELLED"}
        source.active_mapping_index = mapping_index
        mapping = source.mappings[mapping_index]
        pair_name = flip_bone_name(mapping.source_bone)
        pair = next(
            (
                candidate
                for candidate in source.mappings
                if candidate.source_bone == pair_name
            ),
            None,
        )
        if pair_name == mapping.source_bone:
            pair = None
        if self.action == "START":
            for candidate in files:
                _end_axis_preview(context, candidate)
                candidate.axis_editing = False
            source.axis_backup_rotation = tuple(mapping.rotation_offset)
            source.axis_backup_transfer_location = mapping.transfer_location
            source.axis_backup_location_multiplier = mapping.location_multiplier
            source.axis_backup_is_root = mapping.is_root
            source.axis_backup_pair_rotation = tuple(mapping.pair_rotation_offset)
            if pair:
                pair.pair_rotation_offset = tuple(mapping.pair_rotation_offset)
            source.axis_locked_mapping_index = mapping_index
            source.axis_editing = True
            _start_axis_preview(context, source, mapping)
        elif self.action == "RESET":
            mapping.rotation_offset = mapping.reset_rotation_offset
            if pair:
                mapping.pair_rotation_offset = (0.0, 0.0, 0.0)
                pair.pair_rotation_offset = (0.0, 0.0, 0.0)
            mapping.transfer_location = mapping.reset_transfer_location
            mapping.location_multiplier = mapping.reset_location_multiplier
            mapping.is_root = mapping.reset_is_root
        elif self.action == "AUTO":
            settings = context.scene.fbr_settings
            source_obj = bpy.data.objects.get(source.source_object)
            target_obj = _target_object(settings)
            targets = [mapping] + ([pair] if pair else [])
            for candidate in targets:
                if not source_obj or not target_obj or not candidate.target_bone:
                    continue
                source_bone = source_obj.data.bones.get(candidate.source_bone)
                target_bone = target_obj.data.bones.get(candidate.target_bone)
                if not source_bone or not target_bone:
                    continue
                source_rotation, target_rotation = _mapping_rest_rotations(
                    source_obj, target_obj, source_bone, target_bone
                )
                total_offset = source_rotation.inverted() @ target_rotation
                if pair:
                    relative_offset = (
                        Euler(candidate.rotation_offset, "XYZ")
                        .to_quaternion()
                        .inverted()
                        @ total_offset
                    ).to_euler("XYZ")
                    mapping.pair_rotation_offset = relative_offset
                    pair.pair_rotation_offset = tuple(relative_offset)
                    break
                candidate.rotation_offset = total_offset.to_euler("XYZ")
            _update_axis_preview(context)
        elif self.action == "CANCEL":
            mapping.rotation_offset = tuple(source.axis_backup_rotation)
            mapping.pair_rotation_offset = tuple(source.axis_backup_pair_rotation)
            mapping.transfer_location = source.axis_backup_transfer_location
            mapping.location_multiplier = source.axis_backup_location_multiplier
            mapping.is_root = source.axis_backup_is_root
            _end_axis_preview(context, source)
            source.axis_editing = False
        elif self.action == "OK":
            _end_axis_preview(context, source)
            source.axis_editing = False
        return {"FINISHED"}


class FBR_OT_clip_name(Operator):
    bl_idname = "fbr.clip_name"
    bl_label = "片段名稱"
    bl_options = {"INTERNAL", "UNDO"}

    file_index: IntProperty()
    clip_index: IntProperty()
    action: EnumProperty(items=(("CLEAR", "清除", ""), ("RESET", "重設", "")))

    def execute(self, context):
        files = context.scene.fbr_settings.files
        if not 0 <= self.file_index < len(files):
            return {"CANCELLED"}
        clips = files[self.file_index].clips
        if not 0 <= self.clip_index < len(clips):
            return {"CANCELLED"}
        clip = clips[self.clip_index]
        clip.custom_name = "" if self.action == "CLEAR" else clip.action_name
        return {"FINISHED"}


class FBR_OT_auto_map(Operator):
    bl_idname = "fbr.auto_map"
    bl_label = "自動對應"
    bl_description = "依骨骼名稱自動建立對應"
    bl_options = {"REGISTER", "UNDO"}

    file_index: IntProperty()

    def execute(self, context):
        settings = context.scene.fbr_settings
        target = _target_object(settings)
        if not target:
            self.report({"ERROR"}, "請先選擇主要骨架")
            return {"CANCELLED"}
        if not 0 <= self.file_index < len(settings.files):
            return {"CANCELLED"}
        source_file = settings.files[self.file_index]
        source = bpy.data.objects.get(source_file.source_object)
        if not source:
            self.report({"ERROR"}, "來源骨架不存在")
            return {"CANCELLED"}
        mapped = build_automatic_mapping(source, target, source_file.mappings)
        source_file.reuse_mapping = "SELF"
        source_file.mapping_expanded = True
        self.report({"INFO"}, f"已對應 {mapped} 根骨骼")
        return {"FINISHED"}


class FBR_OT_set_reuse_mapping(Operator):
    bl_idname = "fbr.set_reuse_mapping"
    bl_label = "選擇骨架映射"
    bl_options = {"INTERNAL", "UNDO"}

    file_index: IntProperty()
    reuse_uid: StringProperty()

    def execute(self, context):
        files = context.scene.fbr_settings.files
        if not 0 <= self.file_index < len(files):
            return {"CANCELLED"}
        files[self.file_index].reuse_mapping = self.reuse_uid
        return {"FINISHED"}


class FBR_OT_mirror_mapping(Operator):
    bl_idname = "fbr.mirror_mapping"
    bl_label = "左右映射"
    bl_description = "依已設定的左右骨名，填入另一側的目標骨骼"
    bl_options = {"REGISTER", "UNDO"}

    file_index: IntProperty()
    mapping_index: IntProperty(default=-1)

    def execute(self, context):
        settings = context.scene.fbr_settings
        target = _target_object(settings)
        if not target:
            self.report({"ERROR"}, "請先選擇主要骨架")
            return {"CANCELLED"}
        if not 0 <= self.file_index < len(settings.files):
            return {"CANCELLED"}
        source_file = settings.files[self.file_index]
        by_source = {item.source_bone: item for item in source_file.mappings}
        target_names = set(target.data.bones.keys())
        mirrored = 0
        if 0 <= self.mapping_index < len(source_file.mappings):
            candidates = (source_file.mappings[self.mapping_index],)
        else:
            candidates = source_file.mappings
        for item in candidates:
            if not item.target_bone:
                continue
            source_pair = flip_bone_name(item.source_bone)
            target_pair = flip_bone_name(item.target_bone)
            pair = by_source.get(source_pair)
            if (
                pair is None
                or source_pair == item.source_bone
                or target_pair == item.target_bone
                or target_pair not in target_names
            ):
                continue
            if pair.target_bone != target_pair:
                pair.target_bone = target_pair
                pair.transfer_location = item.transfer_location
                pair.location_multiplier = item.location_multiplier
                pair.rotation_offset = item.rotation_offset
                mirrored += 1
        source_file.reuse_mapping = "SELF"
        source_file.mapping_expanded = True
        if not mirrored:
            self.report({"WARNING"}, "沒有找到可填入的左右骨骼對")
            return {"CANCELLED"}
        self.report({"INFO"}, f"已建立 {mirrored} 組左右映射")
        return {"FINISHED"}


class FBR_OT_retarget(Operator):
    bl_idname = "fbr.retarget"
    bl_label = "開始批次重定向"
    bl_description = "將啟用的來源 Action Bake 到主要骨架"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        settings = getattr(context.scene, "fbr_settings", None)
        return bool(settings and not settings.retarget_running)

    @staticmethod
    def _jobs(settings):
        jobs = []
        for source_file in settings.files:
            for clip in source_file.clips:
                if not clip.enabled:
                    continue
                if clip.mirror_mode == "MIRROR":
                    jobs.append((source_file, clip, True))
                elif clip.mirror_mode == "COPY":
                    jobs.extend(((source_file, clip, False), (source_file, clip, True)))
                else:
                    jobs.append((source_file, clip, False))
        return jobs

    @staticmethod
    def _popup(context, title, message, icon="CHECKMARK"):
        if bpy.app.background:
            return

        def draw(menu, _context):
            menu.layout.label(text=message)

        context.window_manager.popup_menu(draw, title=title, icon=icon)

    def _run_blocking(self, context, settings, target, jobs):
        original_frame = context.scene.frame_current
        created = []
        try:
            if settings.output_mode == "MERGED":
                action = bpy.data.actions.new(settings.merged_action_name or "Combined_Animation")
                action.use_fake_user = settings.fake_user
                created.append(action)
                cursor = settings.merged_start
                for source_file, clip, mirrored in jobs:
                    start = clip.custom_start if clip.custom_start >= 0 else cursor
                    length = bake_clip(
                        context, settings, source_file, clip, target, action, start, mirrored
                    )
                    cursor = start + length + settings.merged_gap
                if settings.key_mode == "SIMPLIFY":
                    simplify_action(action, settings.rotation_tolerance, settings.location_tolerance)
            else:
                for source_file, clip, mirrored in jobs:
                    action = bpy.data.actions.new(output_name(settings, source_file, clip, mirrored))
                    action.use_fake_user = settings.fake_user
                    created.append(action)
                    bake_clip(context, settings, source_file, clip, target, action, 1, mirrored)
                    if settings.key_mode == "SIMPLIFY":
                        simplify_action(action, settings.rotation_tolerance, settings.location_tolerance)
            assign_action_and_slot(target, created[-1])
        except Exception as exc:
            for action in created:
                bpy.data.actions.remove(action)
            self.report({"ERROR"}, f"重定向失敗：{exc}")
            return {"CANCELLED"}
        finally:
            context.scene.frame_set(original_frame)
        self.report({"INFO"}, f"完成 {len(jobs)} 個輸出片段")
        self._popup(context, "重定向完成", f"已完成 {len(jobs)} 個輸出片段")
        return {"FINISHED"}

    def _begin_job(self, context):
        settings = context.scene.fbr_settings
        if self._job_index >= len(self._jobs_data):
            return False
        source_file, clip, mirrored = self._jobs_data[self._job_index]
        if settings.output_mode == "MERGED":
            action = self._merged_action
            start = clip.custom_start if clip.custom_start >= 0 else self._cursor
        else:
            action = bpy.data.actions.new(output_name(settings, source_file, clip, mirrored))
            action.use_fake_user = settings.fake_user
            self._created.append(action)
            start = 1
        self._current_action = action
        self._current_start = start
        self._current_iterator = iter_bake_clip(
            context,
            settings,
            source_file,
            clip,
            self._target,
            action,
            start,
            mirrored,
        )
        settings.retarget_status = f"{self._job_index + 1}/{len(self._jobs_data)} · {clip.action_name}"
        return True

    def _finish_modal(self, context, cancelled=False, error=None):
        settings = context.scene.fbr_settings
        if self._current_iterator is not None:
            self._current_iterator.close()
            self._current_iterator = None
        if self._timer is not None:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        context.window_manager.progress_end()
        context.scene.frame_set(self._original_frame)
        settings.retarget_running = False
        settings.retarget_progress = 0.0 if cancelled or error else 1.0
        if cancelled or error:
            for action in list(self._created):
                if action.name in bpy.data.actions:
                    bpy.data.actions.remove(action)
            settings.retarget_status = "已取消" if cancelled else f"失敗：{error}"
            if error:
                self.report({"ERROR"}, settings.retarget_status)
                self._popup(context, "重定向失敗", str(error), "ERROR")
            else:
                self.report({"WARNING"}, "已取消重定向")
            return {"CANCELLED"}
        if settings.output_mode == "MERGED" and settings.key_mode == "SIMPLIFY":
            simplify_action(
                self._merged_action,
                settings.rotation_tolerance,
                settings.location_tolerance,
            )
        assign_action_and_slot(self._target, self._created[-1])
        settings.retarget_status = f"完成 {len(self._jobs_data)} 個輸出片段"
        self.report({"INFO"}, settings.retarget_status)
        self._popup(context, "重定向完成", settings.retarget_status)
        return {"FINISHED"}

    def execute(self, context):
        settings = context.scene.fbr_settings
        target = _target_object(settings)
        if not target:
            self.report({"ERROR"}, "請先選擇主要骨架")
            return {"CANCELLED"}
        jobs = self._jobs(settings)
        if not jobs:
            self.report({"ERROR"}, "沒有啟用的動畫片段")
            return {"CANCELLED"}
        if bpy.app.background:
            return self._run_blocking(context, settings, target, jobs)

        self._target = target
        self._jobs_data = jobs
        self._job_index = 0
        self._created = []
        self._current_iterator = None
        self._current_action = None
        self._merged_action = None
        self._cursor = settings.merged_start
        self._original_frame = context.scene.frame_current
        self._done_steps = 0
        self._total_steps = sum(
            max(1, math.ceil(clip.frame_end - clip.frame_start) + 1)
            for _source, clip, _mirrored in jobs
        )
        if settings.output_mode == "MERGED":
            self._merged_action = bpy.data.actions.new(
                settings.merged_action_name or "Combined_Animation"
            )
            self._merged_action.use_fake_user = settings.fake_user
            self._created.append(self._merged_action)
        settings.retarget_running = True
        settings.retarget_progress = 0.0
        settings.retarget_status = "準備中…"
        context.window_manager.progress_begin(0, self._total_steps)
        self._timer = context.window_manager.event_timer_add(0.01, window=context.window)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type == "ESC":
            return self._finish_modal(context, cancelled=True)
        if event.type != "TIMER":
            return {"PASS_THROUGH"}
        try:
            if self._current_iterator is None and not self._begin_job(context):
                return self._finish_modal(context)
            try:
                next(self._current_iterator)
                self._done_steps += 1
                context.window_manager.progress_update(self._done_steps)
                context.scene.fbr_settings.retarget_progress = min(
                    1.0, self._done_steps / max(1, self._total_steps)
                )
            except StopIteration as finished:
                length = finished.value or 0
                settings = context.scene.fbr_settings
                if settings.output_mode == "MERGED":
                    self._cursor = self._current_start + length + settings.merged_gap
                elif settings.key_mode == "SIMPLIFY":
                    simplify_action(
                        self._current_action,
                        settings.rotation_tolerance,
                        settings.location_tolerance,
                    )
                self._current_iterator = None
                self._job_index += 1
            return {"RUNNING_MODAL"}
        except Exception as exc:
            return self._finish_modal(context, error=exc)


CLASSES = (
    FBR_OT_import_files,
    FBR_OT_import_folder,
    FBR_OT_clear_files,
    FBR_OT_remove_file,
    FBR_OT_reset_all,
    FBR_OT_toggle_file,
    FBR_OT_toggle_clip_option,
    FBR_OT_select_target_bone,
    FBR_OT_clear_target_bone,
    FBR_OT_set_root,
    FBR_OT_align_source_rig,
    FBR_OT_auto_align_axes,
    FBR_OT_preview_animation,
    FBR_OT_clear_target_animation,
    FBR_OT_ik_settings,
    FBR_OT_delete_ik,
    FBR_OT_axis_correction,
    FBR_OT_clip_name,
    FBR_OT_auto_map,
    FBR_OT_set_reuse_mapping,
    FBR_OT_mirror_mapping,
    FBR_OT_retarget,
)
