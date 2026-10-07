import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import bpy
from mathutils import Matrix


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(ROOT))

import Faidlix_BoneRemap as addon
from Faidlix_BoneRemap.model import (
    armature_signature,
    iter_action_fcurves,
    rebuild_animation_rows,
)
from Faidlix_BoneRemap.operators import _mapping_axes_match, _selected_animation_paths
from Faidlix_BoneRemap.retarget import (
    assign_action_and_slot, bake_clip, pose_only_action,
)
from Faidlix_BoneRemap.ui import (
    FBR_UL_animation_rows,
    FBR_UL_mappings,
    _clip_timing_labels,
    _paired_mapping_label,
)


def create_rig(name, length=1.0):
    armature = bpy.data.armatures.new(name + "Data")
    obj = bpy.data.objects.new(name, armature)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    root = armature.edit_bones.new("Hips")
    root.head = (0.0, 0.0, 0.0)
    root.tail = (0.0, 0.0, length)
    arm = armature.edit_bones.new("Arm.L")
    arm.parent = root
    arm.head = root.tail
    arm.tail = (length, 0.0, length)
    left_hand = armature.edit_bones.new("Left_Hand")
    left_hand.parent = arm
    left_hand.head = (length, 0.0, length)
    left_hand.tail = (length * 1.2, 0.0, length)
    right_hand = armature.edit_bones.new("Right_Hand")
    right_hand.parent = root
    right_hand.head = (-length, 0.0, length)
    right_hand.tail = (-length * 1.2, 0.0, length)
    left_finger = armature.edit_bones.new("Left_IndexProximal")
    left_finger.parent = left_hand
    left_finger.head = left_hand.tail
    left_finger.tail = (length * 1.4, 0.0, length)
    right_finger = armature.edit_bones.new("Right_IndexProximal")
    right_finger.parent = right_hand
    right_finger.head = right_hand.tail
    right_finger.tail = (-length * 1.4, 0.0, length)
    unmapped = armature.edit_bones.new("Unmapped")
    unmapped.parent = root
    unmapped.head = (0.0, 0.0, length)
    unmapped.tail = (0.0, length * 0.2, length)
    bpy.ops.object.mode_set(mode="OBJECT")
    obj.select_set(False)
    return obj


def create_axis_variant(name):
    armature = bpy.data.armatures.new(name + "Data")
    obj = bpy.data.objects.new(name, armature)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    root = armature.edit_bones.new("Hips")
    root.head = (0.0, 0.0, 0.0)
    root.tail = (0.0, 1.0, 0.0)
    arm = armature.edit_bones.new("Arm.L")
    arm.parent = root
    arm.head = root.tail
    arm.tail = (0.0, 1.0, 1.0)
    left_hand = armature.edit_bones.new("Left_Hand")
    left_hand.parent = arm
    left_hand.head = (0.0, 1.0, 1.0)
    left_hand.tail = (0.0, 1.0, 1.2)
    right_hand = armature.edit_bones.new("Right_Hand")
    right_hand.parent = root
    right_hand.head = (0.0, -1.0, 1.0)
    right_hand.tail = (0.0, -1.0, 1.2)
    left_finger = armature.edit_bones.new("Left_IndexProximal")
    left_finger.parent = left_hand
    left_finger.head = left_hand.tail
    left_finger.tail = (0.0, 1.0, 1.4)
    right_finger = armature.edit_bones.new("Right_IndexProximal")
    right_finger.parent = right_hand
    right_finger.head = right_hand.tail
    right_finger.tail = (0.0, -1.0, 1.4)
    unmapped = armature.edit_bones.new("Unmapped")
    unmapped.parent = root
    unmapped.head = root.tail
    unmapped.tail = (0.2, 1.0, 0.0)
    bpy.ops.object.mode_set(mode="OBJECT")
    obj.select_set(False)
    return obj


def make_action(source):
    action = bpy.data.actions.new("Walk")
    source.animation_data_create()
    source.animation_data.action = action
    hips = source.pose.bones["Hips"]
    arm = source.pose.bones["Arm.L"]
    hips.location = (0.0, 0.0, 0.0)
    hips.keyframe_insert("location", frame=1, group="Hips")
    hips.location = (0.0, 2.0, 0.0)
    hips.keyframe_insert("location", frame=10, group="Hips")
    arm.rotation_mode = "XYZ"
    arm.rotation_euler = (0.0, 0.0, 0.0)
    arm.keyframe_insert("rotation_euler", frame=1, group="Arm.L")
    arm.rotation_euler.z = 0.75
    arm.keyframe_insert("rotation_euler", frame=10, group="Arm.L")
    return action


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    addon.register()
    version_text = ".".join(str(part) for part in addon.bl_info["version"])
    assert bpy.types.FBR_PT_main.bl_label == "Faidlix_Retarget Motion"
    assert hasattr(bpy.types.FBR_PT_main, "draw_header_preset")
    timing_scene = SimpleNamespace(render=SimpleNamespace(fps=30, fps_base=1.0))
    assert _clip_timing_labels(
        timing_scene,
        SimpleNamespace(frame_start=1.0, frame_end=55.0),
    ) == ("1-55", "( 1.8 秒 )")
    assert _clip_timing_labels(
        timing_scene,
        SimpleNamespace(frame_start=1.0, frame_end=101.0),
    ) == ("1-101", "( 3.3 秒 )")
    assert "DEFAULT_CLOSED" in bpy.types.FBR_PT_main.bl_options
    folder_properties = bpy.ops.fbr.import_folder.get_rna_type().properties
    assert folder_properties["filter_folder"].default
    assert folder_properties["filter_glob"].default == "*.fbx;*.glb;*.gltf;*.blend"
    assert "files" in folder_properties
    assert "filepath" in folder_properties
    assert "filename" in folder_properties
    with tempfile.TemporaryDirectory() as temp_dir:
        selected_folder = Path(temp_dir) / "Locomotion"
        selected_folder.mkdir()
        animation = selected_folder / "walk.blend"
        animation.touch()
        stale_selection = SimpleNamespace(
            directory=str(selected_folder),
            filepath=str(selected_folder / "old-file.blend"),
            files=[SimpleNamespace(name="old-file.blend")],
        )
        assert _selected_animation_paths(stale_selection) == [str(animation)]
    source = create_rig("Source", 1.0)
    source_same_axes = create_rig("SourceTall", 2.0)
    source_different_axes = create_axis_variant("SourceDifferentAxes")
    target = create_rig("Target", 1.5)
    source["_fbr_temp_source"] = True
    source_same_axes["_fbr_temp_source"] = True
    source_different_axes["_fbr_temp_source"] = True
    action = make_action(source)

    assert armature_signature(source) == armature_signature(source_same_axes)
    assert armature_signature(source) == armature_signature(source_different_axes)
    settings = bpy.context.scene.fbr_settings
    settings.target_armature = target.name
    settings.key_mode = "SIMPLIFY"
    entry = settings.files.add()
    entry.uid = "source"
    entry.display_name = "walk.blend"
    entry.file_type = "BLEND"
    entry.source_object = source.name
    entry.signature = armature_signature(source)
    entry.reuse_mapping = "SELF"
    clip = entry.clips.add()
    clip.action_name = action.name
    clip.frame_start, clip.frame_end = action.frame_range
    rebuild_animation_rows(settings)
    assert [(item.file_uid, item.clip_index) for item in settings.animation_rows] == [
        (entry.uid, 0)
    ]
    second_ui_clip = entry.clips.add()
    second_ui_clip.action_name = "Second"
    second_ui_clip.frame_start, second_ui_clip.frame_end = (1.0, 20.0)
    rebuild_animation_rows(settings)
    assert [item.clip_index for item in settings.animation_rows] == [-1, 0, 1]
    animation_list_stub = SimpleNamespace(bitflag_filter_item=1)
    entry.expanded = False
    collapsed_animation_flags, _ = FBR_UL_animation_rows.filter_items(
        animation_list_stub, bpy.context, settings, "animation_rows"
    )
    assert collapsed_animation_flags == [1, 0, 0]
    entry.expanded = True
    entry.clips.remove(1)
    rebuild_animation_rows(settings)
    assert bpy.ops.fbr.set_forward_axis(
        file_index=0, role="SOURCE", axis="+X"
    ) == {"FINISHED"}
    assert entry.source_forward_axis == "+X"
    assert bpy.ops.fbr.set_forward_axis(
        file_index=0, role="TARGET", axis="-Y"
    ) == {"FINISHED"}
    assert entry.target_forward_axis == "-Y"
    assert bpy.ops.fbr.set_forward_axis(
        file_index=0, role="SOURCE", axis="AUTO"
    ) == {"FINISHED"}
    assert bpy.ops.fbr.set_forward_axis(
        file_index=0, role="TARGET", axis="AUTO"
    ) == {"FINISHED"}
    assert bpy.ops.fbr.toggle_clip_option(
        file_index=0,
        clip_index=0,
        option="COPY",
    ) == {"FINISHED"}
    assert clip.mirror_mode == "COPY"
    assert bpy.ops.fbr.toggle_clip_option(
        file_index=0,
        clip_index=0,
        option="COPY",
    ) == {"FINISHED"}
    assert clip.mirror_mode == "NONE"
    root_map = entry.mappings.add()
    root_map.source_bone = "Hips"
    root_map.target_bone = "Hips"
    root_map.is_root = True
    root_map.transfer_location = True
    root_map.reset_is_root = True
    root_map.reset_transfer_location = True
    assert _mapping_axes_match(source_different_axes, target, root_map)
    arm_map = entry.mappings.add()
    arm_map.source_bone = "Arm.L"
    arm_map.target_bone = "Arm.L"
    left_map = entry.mappings.add()
    left_map.source_bone = "Left_Hand"
    left_map.target_bone = "Left_Hand"
    right_map = entry.mappings.add()
    right_map.source_bone = "Right_Hand"
    right_map.target_bone = "Right_Hand"
    hand_pair_index = 2
    left_finger_map = entry.mappings.add()
    left_finger_map.source_bone = "Left_IndexProximal"
    left_finger_map.target_bone = "Left_IndexProximal"
    right_finger_map = entry.mappings.add()
    right_finger_map.source_bone = "Right_IndexProximal"
    right_finger_map.target_bone = "Right_IndexProximal"
    root_map = entry.mappings[0]
    arm_map = entry.mappings[1]
    left_map = entry.mappings[hand_pair_index]
    right_map = entry.mappings[hand_pair_index + 1]
    filter_stub = SimpleNamespace(bitflag_filter_item=1)
    entry.hands_expanded = False
    collapsed_flags, _ = FBR_UL_mappings.filter_items(
        filter_stub, bpy.context, entry, "mappings"
    )
    assert collapsed_flags[len(entry.mappings) - 2] == 0
    assert collapsed_flags[len(entry.mappings) - 1] == 0
    entry.hands_expanded = True
    assert _paired_mapping_label(entry, left_map, "source_bone") == "Left_Hand/Right_Hand"
    assert _paired_mapping_label(entry, left_map, "target_bone") == "Left_Hand/Right_Hand"
    pair_flags, _order = FBR_UL_mappings.filter_items(
        filter_stub,
        bpy.context,
        entry,
        "mappings",
    )
    assert pair_flags[hand_pair_index] == 1
    assert pair_flags[hand_pair_index + 1] == 0
    assert bpy.ops.fbr.select_target_bone(
        file_index=0,
        mapping_index=hand_pair_index,
        target_bone="Right_Hand",
    ) == {"FINISHED"}
    assert left_map.target_bone == "Right_Hand"
    assert right_map.target_bone == "Left_Hand"
    assert bpy.ops.fbr.clear_target_bone(
        file_index=0,
        mapping_index=hand_pair_index,
    ) == {"FINISHED"}
    assert not left_map.target_bone and not right_map.target_bone
    left_map.target_bone = "Left_Hand"
    right_map.target_bone = "Right_Hand"
    left_basis = source.pose.bones["Left_Hand"].matrix_basis.copy()
    right_basis = source.pose.bones["Right_Hand"].matrix_basis.copy()
    pair_index = hand_pair_index
    assert bpy.ops.fbr.axis_correction(
        file_index=0,
        mapping_index=pair_index,
        action="START",
    ) == {"FINISHED"}
    left_base_rotation = tuple(left_map.rotation_offset)
    right_base_rotation = tuple(right_map.rotation_offset)
    left_map.pair_rotation_offset = (0.0, 0.0, 0.35)
    assert all(
        abs(a - b) < 1.0e-6
        for a, b in zip(left_map.pair_rotation_offset, right_map.pair_rotation_offset)
    )
    assert tuple(left_map.rotation_offset) == left_base_rotation
    assert tuple(right_map.rotation_offset) == right_base_rotation
    assert source.pose.bones["Left_Hand"].matrix_basis != left_basis
    assert source.pose.bones["Right_Hand"].matrix_basis != right_basis
    assert bpy.ops.fbr.axis_correction(
        file_index=0,
        mapping_index=pair_index,
        action="CANCEL",
    ) == {"FINISHED"}
    assert all(abs(value) < 1.0e-6 for value in left_map.pair_rotation_offset)
    assert all(abs(value) < 1.0e-6 for value in right_map.pair_rotation_offset)

    entry.source_object = source_different_axes.name
    assert bpy.ops.fbr.auto_align_axes(file_index=0) == {"FINISHED"}
    assert _mapping_axes_match(source_different_axes, target, root_map)
    assert all(abs(value) < 1.0e-6 for value in root_map.rotation_offset)
    assert abs(entry.global_axis_correction[0]) <= 1.0
    root_map.rotation_offset = (0.0, 0.0, 0.0)
    arm_map.rotation_offset = (0.0, 0.0, 0.0)
    entry.source_object = source.name

    bpy.context.view_layer.objects.active = target
    target.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    extra = target.data.edit_bones.new("UnmappedDecoration")
    extra.head = (0.0, 0.0, 0.0)
    extra.tail = (0.0, 0.0, 100.0)
    bpy.ops.object.mode_set(mode="OBJECT")
    assert bpy.ops.fbr.align_source_rig(file_index=0) == {"FINISHED"}
    assert abs(entry.preview_scale - 1.0) < 1.0e-6
    assert abs(source.get("_fbr_alignment_scale", 1.0) - 1.5) < 1.0e-6
    aligned_once = source.matrix_world.copy()
    target_matrix_before_repeat = target.matrix_world.copy()
    assert bpy.ops.fbr.align_source_rig(file_index=0) == {"FINISHED"}
    assert source.matrix_world == aligned_once
    assert target.matrix_world == target_matrix_before_repeat
    bpy.ops.object.mode_set(mode="EDIT")
    target.data.edit_bones.remove(target.data.edit_bones["UnmappedDecoration"])
    bpy.ops.object.mode_set(mode="OBJECT")
    target.select_set(False)

    result = bpy.ops.fbr.select_target_bone(
        file_index=0,
        mapping_index=0,
        target_bone="Arm.L",
    )
    assert result == {"FINISHED"}
    assert root_map.target_bone == "Arm.L"
    assert arm_map.target_bone == "Hips"
    result = bpy.ops.fbr.select_target_bone(
        file_index=0,
        mapping_index=0,
        target_bone="Hips",
    )
    assert result == {"FINISHED"}
    assert root_map.target_bone == "Hips"
    assert arm_map.target_bone == "Arm.L"

    entry.active_mapping_index = 0
    source.hide_set(True)
    bpy.context.view_layer.objects.active = target
    target.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    for edit_bone in target.data.edit_bones:
        edit_bone.head.z += 0.75
        edit_bone.tail.z += 0.75
    bpy.ops.object.mode_set(mode="OBJECT")
    target.select_set(False)
    source_basis = source.pose.bones["Hips"].matrix_basis.copy()
    target_basis = target.pose.bones["Hips"].matrix_basis.copy()
    root_map.rotation_offset = (0.1, 0.2, 0.3)
    assert bpy.ops.fbr.axis_correction(file_index=0, action="START") == {"FINISHED"}
    entry.active_mapping_index = 1
    assert entry.active_mapping_index == 0
    assert not source.hide_get()
    assert source.show_in_front
    assert source.data.show_axes
    assert source.data.display_type == "OCTAHEDRAL"
    assert source.pose.bones["Hips"].select
    assert target.pose.bones["Hips"].select
    source_root_world = source.matrix_world @ source.pose.bones["Hips"].head
    target_root_world = target.matrix_world @ target.pose.bones["Hips"].head
    assert (source_root_world - target_root_world).length < 1.0e-6
    assert source.display_type == "SOLID"
    assert all(abs(a - b) < 1.0e-6 for a, b in zip(source.color, (1.0, 0.70, 0.05, 1.0)))
    preview_color = source.data.bones["Hips"].color.custom.normal
    assert preview_color[0] > preview_color[1] > preview_color[2]
    pose_preview_color = source.pose.bones["Hips"].color.custom.normal
    assert pose_preview_color[0] > pose_preview_color[1] > pose_preview_color[2]
    assert not target.data.show_axes
    preview_basis = source.pose.bones["Hips"].matrix_basis.copy()
    assert any(
        abs(preview_basis[row][column] - source_basis[row][column]) > 1.0e-6
        for row in range(4)
        for column in range(4)
    )
    root_map.rotation_offset = (0.4, 0.3, 0.2)
    root_map.transfer_location = False
    root_map.is_root = False
    assert bpy.ops.fbr.axis_correction(file_index=0, action="RESET") == {"FINISHED"}
    assert all(abs(value) < 1.0e-6 for value in root_map.rotation_offset)
    assert root_map.transfer_location
    assert root_map.is_root
    root_map.rotation_offset = (0.0, 0.0, 0.0)
    assert bpy.ops.fbr.axis_correction(file_index=0, action="CANCEL") == {"FINISHED"}
    assert all(abs(a - b) < 1.0e-6 for a, b in zip(root_map.rotation_offset, (0.1, 0.2, 0.3)))
    assert source.hide_get()
    assert not source.data.show_axes
    assert not target.data.show_axes
    restored_basis = source.pose.bones["Hips"].matrix_basis
    assert all(
        abs(restored_basis[row][column] - source_basis[row][column]) < 1.0e-6
        for row in range(4)
        for column in range(4)
    )

    # Editing a child bone must keep previously confirmed parent corrections
    # visible, so the preview is cumulative instead of returning to the
    # original lying pose.
    arm_source_basis = source.pose.bones["Arm.L"].matrix_basis.copy()
    arm_map.rotation_offset = (0.0, 0.0, 0.25)
    entry.active_mapping_index = 1
    assert bpy.ops.fbr.axis_correction(file_index=0, action="START") == {"FINISHED"}
    stacked_root_basis = source.pose.bones["Hips"].matrix_basis.copy()
    stacked_arm_basis = source.pose.bones["Arm.L"].matrix_basis.copy()
    assert any(
        abs(stacked_root_basis[row][column] - source_basis[row][column]) > 1.0e-6
        for row in range(4)
        for column in range(4)
    )
    assert any(
        abs(stacked_arm_basis[row][column] - arm_source_basis[row][column]) > 1.0e-6
        for row in range(4)
        for column in range(4)
    )
    assert bpy.ops.fbr.axis_correction(file_index=0, action="CANCEL") == {"FINISHED"}
    assert all(
        abs(a - b) < 1.0e-6
        for a, b in zip(arm_map.rotation_offset, (0.0, 0.0, 0.25))
    )

    source.hide_set(True)
    source.matrix_world.translation = (3.0, -2.0, 1.0)
    source_matrix_before_preview = source.matrix_world.copy()
    target_axes_before_preview = target.data.show_axes
    frame_range_before_preview = (bpy.context.scene.frame_start, bpy.context.scene.frame_end)
    entry.preview_clip = "0"
    source_pose_position = source.data.pose_position
    target_pose_position = target.data.pose_position
    target_action_before_tpose = target.animation_data.action if target.animation_data else None
    assert bpy.ops.fbr.preview_tpose(file_index=0, action="SHOW") == {"FINISHED"}
    assert settings.preview_running and settings.preview_mode == "TPOSE"
    assert source.data.pose_position == "REST"
    assert target.data.pose_position == "REST"
    assert bpy.ops.fbr.align_source_rig(file_index=0) == {"FINISHED"}
    assert settings.preview_running and settings.preview_mode == "TPOSE"
    assert source.data.pose_position == "REST"
    assert target.data.pose_position == "REST"
    assert bpy.ops.fbr.preview_tpose(file_index=0, action="HIDE") == {"FINISHED"}
    assert source.data.pose_position == source_pose_position
    assert target.data.pose_position == target_pose_position
    assert (target.animation_data.action if target.animation_data else None) == target_action_before_tpose
    aligned_source_matrix = source.matrix_world.copy()
    preview_actions = {
        item.identifier
        for item in bpy.ops.fbr.preview_animation.get_rna_type().properties["action"].enum_items
    }
    assert {"SHOW", "HIDE", "PLAY", "PAUSE"}.issubset(preview_actions)
    assert bpy.ops.fbr.preview_animation(file_index=0, action="SHOW") == {"FINISHED"}
    assert settings.preview_running and settings.preview_source_uid == entry.uid
    assert not source.hide_get()
    assert source.data.display_type == "OCTAHEDRAL"
    assert source.data.show_axes and not source.data.show_names
    assert target.data.show_axes and not target.data.show_names
    source_root_world = source.matrix_world @ source.pose.bones["Hips"].head
    target_root_world = target.matrix_world @ target.pose.bones["Hips"].head
    assert (source_root_world - target_root_world).length < 1.0e-6
    preview_action = target.animation_data.action
    assert preview_action and preview_action.name.startswith("__FBR_PREVIEW__")
    preview_action_name = preview_action.name
    assert source.animation_data.action == action
    assert bpy.ops.fbr.align_source_rig(file_index=0) == {"FINISHED"}
    assert settings.preview_running and settings.preview_mode == "ANIMATION"
    assert source.animation_data.action == action
    assert target.animation_data.action.name.startswith("__FBR_PREVIEW__")
    bpy.context.scene.frame_set(1)
    source_start_location = source.pose.bones["Hips"].location.copy()
    target_start_location = target.pose.bones["Hips"].location.copy()
    bpy.context.scene.frame_set(10)
    source_end_location = source.pose.bones["Hips"].location.copy()
    target_end_location = target.pose.bones["Hips"].location.copy()
    assert (source_end_location - source_start_location).length > 1.0e-6
    assert (target_end_location - target_start_location).length > 1.0e-6
    assert bpy.ops.fbr.preview_animation(file_index=0, action="PLAY") == {"FINISHED"}
    assert settings.preview_running
    assert bpy.ops.fbr.preview_animation(file_index=0, action="PAUSE") == {"FINISHED"}
    assert settings.preview_running
    assert bpy.ops.fbr.preview_animation(file_index=0, action="HIDE") == {"FINISHED"}
    assert not settings.preview_running and not settings.preview_source_uid
    assert source.hide_get()
    assert source.matrix_world == aligned_source_matrix
    assert target.data.show_axes == target_axes_before_preview
    assert target.animation_data.action is None
    assert preview_action_name not in bpy.data.actions
    assert (bpy.context.scene.frame_start, bpy.context.scene.frame_end) == frame_range_before_preview

    assert bpy.ops.fbr.set_root(file_index=0, mapping_index=1) == {"FINISHED"}
    assert arm_map.is_root and not root_map.is_root
    assert bpy.ops.fbr.set_root(file_index=0, mapping_index=0) == {"FINISHED"}
    assert root_map.is_root and not arm_map.is_root

    hand_index = next(
        index
        for index, item in enumerate(entry.mappings)
        if item.source_bone == "Left_Hand"
    )
    hand_map = entry.mappings[hand_index]
    assert hand_map.ik_chain_count == 2
    assert hand_map.ik_iterations == 500
    assert abs(hand_map.ik_shape_scale - 0.05) < 1.0e-6
    assert hand_map.ik_use_pole
    assert abs(hand_map.ik_pole_length - 0.5) < 1.0e-6
    assert abs(hand_map.ik_pole_size_ratio - 0.7) < 1.0e-6
    assert bpy.ops.fbr.ik_settings(
        "INVOKE_DEFAULT",
        file_index=0, mapping_index=hand_index, action="START"
    ) == {"FINISHED"}
    assert hand_map.ik_control_bone in target.data.bones
    assert hand_map.ik_pole_bone in target.data.bones
    pole_control = target.pose.bones[hand_map.ik_pole_bone]
    assert abs(pole_control.custom_shape_scale_xyz.x - 0.035) < 1.0e-6
    assert target.data.bones[hand_map.ik_pole_bone].get("_fbr_ik_pole")
    hand_constraint = next(
        constraint
        for constraint in target.pose.bones["Arm.L"].constraints
        if constraint.type == "IK" and constraint.name.startswith("FBR IK")
    )
    assert hand_constraint.subtarget == hand_map.ik_control_bone
    assert hand_constraint.pole_subtarget == hand_map.ik_pole_bone
    pole_before = pole_control.matrix.translation.copy()
    hand_map.ik_pole_length = 0.8
    assert (pole_control.matrix.translation - pole_before).length > 1.0e-6
    hand_map.ik_use_pole = False
    assert hand_constraint.pole_target is None
    hand_map.ik_use_pole = True
    assert hand_constraint.pole_subtarget == hand_map.ik_pole_bone
    assert hand_constraint.chain_count == 2
    assert hand_constraint.iterations == 500
    assert bpy.ops.fbr.ik_settings(
        file_index=0, mapping_index=hand_index, action="RESET"
    ) == {"FINISHED"}
    assert hand_map.ik_control_bone == "" and hand_map.ik_pole_bone == ""

    assert bpy.ops.fbr.ik_settings(file_index=0, mapping_index=1, action="START") == {"FINISHED"}
    assert bpy.context.view_layer.objects.active == target
    assert target.mode == "POSE"
    control_name = arm_map.ik_control_bone
    assert arm_map.ik_enabled and control_name in target.data.bones
    constraint = next(
        constraint
        for constraint in target.pose.bones["Arm.L"].constraints
        if constraint.type == "IK" and constraint.name.startswith("FBR IK")
    )
    assert constraint.subtarget == control_name
    arm_map.ik_shape = "SPHERE"
    arm_map.ik_shape_scale = 0.001
    assert abs(arm_map.ik_shape_scale - 0.01) < 1.0e-6
    arm_map.ik_shape_scale = 1.5
    arm_map.ik_shape_wire_width = 4.0
    arm_map.ik_shape_color = (0.2, 0.6, 0.9)
    arm_map.ik_chain_count = 1
    assert target.pose.bones[control_name].custom_shape.name == "FBR_IK_SHAPE_SPHERE"
    shape_object = target.pose.bones[control_name].custom_shape
    shape_collection = bpy.data.collections["__FBR_IK_Shapes__"]
    assert shape_collection.hide_viewport and shape_collection.hide_render
    assert shape_object.hide_viewport and shape_object.hide_get()
    assert shape_object.hide_render
    assert not target.data.bones[control_name].use_deform
    assert target.data.bones[control_name].show_wire
    assert tuple(target.pose.bones[control_name].custom_shape_scale_xyz) == (1.5, 1.5, 1.5)
    assert not target.pose.bones[control_name].use_custom_shape_bone_size
    assert target.pose.bones[control_name].custom_shape_wire_width == 4.0
    control_color = target.data.bones[control_name].color.custom.normal
    assert control_color[2] > control_color[1] > control_color[0]
    assert bpy.ops.fbr.ik_settings(file_index=0, mapping_index=1, action="OK") == {"FINISHED"}
    assert bpy.ops.fbr.ik_settings(file_index=0, mapping_index=1, action="START") == {"FINISHED"}
    assert bpy.ops.fbr.ik_settings(file_index=0, mapping_index=1, action="RESET") == {"FINISHED"}
    assert not arm_map.ik_enabled and control_name not in target.data.bones
    assert bpy.ops.fbr.ik_settings(file_index=0, mapping_index=1, action="CANCEL") == {"FINISHED"}
    control_name = arm_map.ik_control_bone
    assert arm_map.ik_enabled and control_name in target.data.bones

    unmapped_map = entry.mappings.add()
    unmapped_map.source_bone = "Unmapped"
    assert bpy.ops.fbr.ik_settings(
        file_index=0, mapping_index=len(entry.mappings) - 1, action="START"
    ) == {"FINISHED"}
    unmapped_control = unmapped_map.ik_control_bone
    assert unmapped_map.ik_enabled and unmapped_control in source.data.bones
    assert not source.data.bones[unmapped_control].use_deform
    assert bpy.ops.fbr.delete_ik(
        file_index=0, mapping_index=len(entry.mappings) - 1
    ) == {"FINISHED"}
    assert not entry.ik_editing and unmapped_control not in source.data.bones

    root_map = entry.mappings[0]
    arm_map = entry.mappings[1]
    arm_map.ik_chain_count = 0

    batch_clip = entry.clips.add()
    batch_clip.action_name = action.name
    batch_clip.frame_start, batch_clip.frame_end = action.frame_range

    result = bpy.ops.fbr.retarget()
    assert result == {"FINISHED"}, result
    output = bpy.data.actions.get("walk_Walk")
    batch_output = bpy.data.actions.get("walk_Walk.001")
    assert output is not None
    assert batch_output is not None
    assert output.use_fake_user
    assert target.animation_data.action == batch_output
    assert target.animation_data.action_slot is not None
    assert any(slot == target.animation_data.action_slot for slot in batch_output.slots)
    assert bpy.data.objects.get("Source") == source
    assert bpy.data.objects.get("Target") == target
    assert len(settings.files) == 1
    curves = list(iter_action_fcurves(output))
    assert curves
    assert any("Hips" in curve.data_path and "location" in curve.data_path for curve in curves)
    assert not any(
        'pose.bones["Arm.L"].rotation_quaternion' in curve.data_path
        for curve in curves
    )
    assert any(
        control_name in curve.data_path and "rotation_quaternion" in curve.data_path
        for curve in curves
    )
    assert any(control_name in curve.data_path and "location" in curve.data_path for curve in curves)
    assert max(len(curve.keyframe_points) for curve in curves) <= 10
    for baked_action in (output, batch_output):
        root_z_curves = [
            curve
            for curve in iter_action_fcurves(baked_action)
            if 'pose.bones["Hips"].location' in curve.data_path and curve.array_index == 2
        ]
        assert root_z_curves
        assert all(
            abs(point.co.y) < 1.0e-5
            for curve in root_z_curves
            for point in curve.keyframe_points
        )
        control_values = [
            abs(point.co.y)
            for curve in iter_action_fcurves(baked_action)
            if control_name in curve.data_path and "location" in curve.data_path
            for point in curve.keyframe_points
        ]
        assert control_values and max(control_values) < 20.0
    assert bpy.ops.fbr.delete_ik(file_index=0, mapping_index=1) == {"FINISHED"}
    assert control_name not in target.data.bones
    assert not any(
        obj.get("_fbr_ik_shape", False)
        for obj in bpy.data.objects
    )
    target.pose.bones["Hips"].location = (3.0, -2.0, 1.0)
    target.pose.bones["Arm.L"].rotation_mode = "XYZ"
    target.pose.bones["Arm.L"].rotation_euler = (0.2, 0.3, 0.4)
    assert bpy.ops.fbr.clear_target_animation() == {"FINISHED"}
    assert target.animation_data is None
    identity = Matrix.Identity(4)
    assert all(
        pose_bone.matrix_basis == identity
        for pose_bone in target.pose.bones
    )
    leader = settings.files.add()
    leader.uid = "leader"
    leader.display_name = "leader.blend"
    leader.source_object = source_same_axes.name
    leader.signature = armature_signature(source_same_axes)
    leader.reuse_mapping = "SELF"
    follower = settings.files.add()
    follower.uid = "follower"
    follower.display_name = "follower.blend"
    follower.source_object = source_different_axes.name
    follower.signature = armature_signature(source_different_axes)
    follower.reuse_mapping = leader.uid
    assert not follower.mapping_is_independent
    assert bpy.ops.fbr.remove_file(file_index=1) == {"FINISHED"}
    assert settings.files[1].uid == "follower"
    assert settings.files[1].reuse_mapping == entry.uid
    assert not settings.files[1].mapping_is_independent
    # FBX object-scale keys must not override the aligned source armature,
    # and fractional source keys must be sampled with a scene subframe.
    fractional = action.copy()
    fractional.name = "FractionalSource"
    for curve in iter_action_fcurves(fractional):
        if curve.keyframe_points and 'pose.bones["Hips"]' in curve.data_path:
            curve.keyframe_points[-1].co.x = 10.5
            curve.update()
    source_matrix = source.matrix_world.copy()
    assign_action_and_slot(source, fractional)
    source.scale = (0.000049,) * 3
    source.keyframe_insert(data_path="scale", frame=1.25)
    source.scale = (0.0001,) * 3
    source.keyframe_insert(data_path="scale", frame=10.5)
    source.matrix_world = source_matrix
    filtered = pose_only_action(fractional)
    assert filtered != fractional
    assert all(
        curve.data_path.startswith('pose.bones[')
        for curve in iter_action_fcurves(filtered)
    )
    bpy.data.actions.remove(filtered)
    fractional_clip = SimpleNamespace(
        action_name=fractional.name,
        in_place=False,
    )
    settings.key_mode = "SOURCE"
    fractional_output = bpy.data.actions.new("FractionalOutput")
    baked_count = bake_clip(
        bpy.context, settings, entry, fractional_clip,
        target, fractional_output, 1.0,
    )
    assert baked_count > 0
    assert source.matrix_world == source_matrix
    assert any(
        abs(point.co.x - 1.25) < 1.0e-5
        for curve in iter_action_fcurves(fractional_output)
        for point in curve.keyframe_points
    )
    fractional_entry = entry.clips.add()
    fractional_entry.action_name = fractional.name
    fractional_entry.frame_start, fractional_entry.frame_end = fractional.frame_range
    entry.preview_clip = str(len(entry.clips) - 1)
    assert bpy.ops.fbr.preview_animation(file_index=0, action="SHOW") == {"FINISHED"}
    assert source.display_type == "SOLID"
    assert source.animation_data.action != fractional
    bpy.context.scene.frame_set(1)
    preview_matrix = source.matrix_world.copy()
    bpy.context.scene.frame_set(10)
    assert source.matrix_world == preview_matrix
    assert bpy.ops.fbr.auto_align_axes(file_index=0) == {"FINISHED"}
    assert settings.preview_running and settings.preview_mode == "ANIMATION"
    assert bpy.ops.fbr.auto_map(file_index=0) == {"FINISHED"}
    assert settings.preview_running and settings.preview_mode == "ANIMATION"
    assert source.matrix_world == preview_matrix
    entry.source_forward_axis = "+X"
    assert settings.preview_running and settings.preview_mode == "ANIMATION"
    assert source.animation_data.action != fractional
    assert min(source.matrix_world.to_scale()) > 0.1
    entry.target_forward_axis = "-Y"
    assert settings.preview_running and settings.preview_mode == "ANIMATION"
    assert min(source.matrix_world.to_scale()) > 0.1
    assert bpy.ops.fbr.preview_animation(file_index=0, action="HIDE") == {"FINISHED"}
    assert bpy.ops.fbr.preview_tpose(file_index=0, action="SHOW") == {"FINISHED"}
    assert bpy.ops.fbr.auto_align_axes(file_index=0) == {"FINISHED"}
    assert settings.preview_running and settings.preview_mode == "TPOSE"
    assert bpy.ops.fbr.auto_map(file_index=0) == {"FINISHED"}
    assert settings.preview_running and settings.preview_mode == "TPOSE"
    assert source.data.pose_position == "REST"
    assert min(source.matrix_world.to_scale()) > 0.1
    assert bpy.ops.fbr.preview_tpose(file_index=0, action="HIDE") == {"FINISHED"}
    entry.clips.remove(len(entry.clips) - 1)
    assign_action_and_slot(source, action)
    bpy.data.actions.remove(fractional)
    # Reset must remove all add-on IK controls and hidden Custom Shape data,
    # not just clear the mapping collection that referenced them.
    entry = settings.files[0]
    assert bpy.ops.fbr.ik_settings(file_index=0, mapping_index=1, action="START") == {"FINISHED"}
    reset_control = entry.mappings[1].ik_control_bone
    assert reset_control in target.data.bones
    assert bpy.ops.fbr.reset_all() == {"FINISHED"}
    assert bpy.data.objects.get("Source") is None
    assert len(settings.files) == 0
    assert reset_control not in target.data.bones
    assert "__FBR_IK_Shapes__" not in bpy.data.collections
    assert not any(obj.get("_fbr_ik_shape", False) for obj in bpy.data.objects)
    print("FBR_HEADLESS_OK")
    addon.unregister()


if __name__ == "__main__":
    main()
