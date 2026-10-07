import json
import math
import os
import sys
from pathlib import Path

import bpy


ADDON_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ADDON_ROOT.parents[1]
ASSET_ROOT = PROJECT_ROOT.parent
sys.path.insert(0, str(ADDON_ROOT.parent))

import Faidlix_BoneRemap as addon
from Faidlix_BoneRemap.model import iter_action_fcurves
from Faidlix_BoneRemap.retarget import _clear_target_pose, assign_action_and_slot, bake_clip, mapping_source
from Faidlix_BoneRemap.operators import _character_basis


def _import(path):
    result = bpy.ops.fbr.import_files(filepath=str(path))
    assert result == {"FINISHED"}, (path, result)


def _foot_mapping_index(source):
    preferred = []
    fallback = []
    for index, mapping in enumerate(source.mappings):
        name = mapping.source_bone.casefold()
        if "foot" not in name or "toe" in name or not mapping.target_bone:
            continue
        fallback.append(index)
        if "left" in name or name.endswith((".l", "_l")):
            preferred.append(index)
    candidates = preferred or fallback
    assert candidates, f"{source.display_name} 找不到已映射的腳骨"
    return candidates[0]


def _curve_values(action):
    values = []
    for curve in iter_action_fcurves(action):
        values.extend(point.co.y for point in curve.keyframe_points)
    return values


def _dynamic_curve_count(action):
    return sum(
        1
        for curve in iter_action_fcurves(action)
        if curve.keyframe_points
        and max(point.co.y for point in curve.keyframe_points)
        - min(point.co.y for point in curve.keyframe_points)
        > 1.0e-5
    )


def _matrix_distance(left, right):
    return max(
        abs(left[row][column] - right[row][column])
        for row in range(4)
        for column in range(4)
    )


def _sample_pose_motion(settings, source_file, action):
    obj = bpy.data.objects[source_file.source_object]
    owner = mapping_source(settings, source_file)
    names = [
        mapping.source_bone
        for mapping in owner.mappings
        if mapping.target_bone and mapping.source_bone in obj.pose.bones
    ]
    previous_hidden = obj.hide_get()
    previous_hide_viewport = obj.hide_viewport
    obj.hide_viewport = False
    obj.hide_set(False)
    assign_action_and_slot(obj, action)
    start, end = action.frame_range
    samples = []
    for frame in (start, (start + end) * 0.5, end):
        bpy.context.scene.frame_set(round(frame))
        bpy.context.view_layer.update()
        evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        samples.append([
            value
            for name in names
            for row in evaluated.pose.bones[name].matrix_basis
            for value in row
        ])
    obj.hide_viewport = previous_hide_viewport
    obj.hide_set(previous_hidden)
    return max(
        abs(value - samples[0][index])
        for sample in samples[1:]
        for index, value in enumerate(sample)
    )


def main():
    if not hasattr(bpy.types.Scene, "fbr_settings"):
        addon.register()
    settings = bpy.context.scene.fbr_settings
    target = bpy.data.objects.get("Armature")
    assert target and target.type == "ARMATURE"
    settings.target_armature = target.name
    settings.naming_mode = "FILE_ACTION"
    settings.key_mode = "SIMPLIFY"

    paths = (
        ASSET_ROOT / "fairy-new-model.blend",
        ASSET_ROOT / "Walk.fbx",
        ASSET_ROOT / "Idle.fbx",
        ASSET_ROOT / "Run.fbx",
    )
    for path in paths:
        assert path.exists(), path
        _import(path)

    assert len(settings.files) == 4
    for imported in settings.files:
        armature = bpy.data.objects[imported.source_object]
        assert not armature.animation_data or armature.animation_data.action is None
        assert all(bpy.data.actions[clip.action_name].use_fake_user for clip in imported.clips)
    enabled = []
    source_dynamic = {}
    for source in settings.files:
        for clip in source.clips:
            if source.display_name == "fairy-new-model.blend":
                clip.enabled = clip.action_name in {"Fairy_Idle", "Fairy_Run"}
            else:
                clip.enabled = True
            if clip.enabled:
                enabled.append((source.display_name, clip.action_name))
                source_dynamic[
                    f"{os.path.splitext(source.display_name)[0]}_{clip.action_name}"
                ] = _dynamic_curve_count(bpy.data.actions[clip.action_name])
    assert enabled == [
        ("fairy-new-model.blend", "Fairy_Idle"),
        ("fairy-new-model.blend", "Fairy_Run"),
        ("Walk.fbx", "Walk_N"),
        ("Idle.fbx", "Idle"),
        ("Run.fbx", "Run"),
    ], enabled

    ik_controls = []
    for file_index, source in enumerate(settings.files):
        if not source.mapping_is_independent:
            continue
        target_matrix = target.matrix_world.copy()
        assert bpy.ops.fbr.auto_map(file_index=file_index) == {"FINISHED"}
        aligned_source_matrix = bpy.data.objects[source.source_object].matrix_world.copy()
        assert bpy.ops.fbr.auto_map(file_index=file_index) == {"FINISHED"}
        assert _matrix_distance(
            bpy.data.objects[source.source_object].matrix_world,
            aligned_source_matrix,
        ) < 1.0e-6, f"{source.display_name} 第二次自動配骨架造成累乘"
        assert _matrix_distance(target.matrix_world, target_matrix) < 1.0e-6, (
            f"{source.display_name} 自動配骨架改動 Target 物件矩陣"
        )
        if source.display_name == "Run.fbx":
            run_obj = bpy.data.objects[source.source_object]
            expected_scale = min(run_obj.matrix_world.to_scale())
            assert bpy.ops.fbr.preview_tpose(file_index=file_index, action="SHOW") == {"FINISHED"}
            assert bpy.ops.fbr.auto_map(file_index=file_index) == {"FINISHED"}
            assert settings.preview_mode == "TPOSE"
            assert min(run_obj.matrix_world.to_scale()) > expected_scale * 0.9
            source.source_forward_axis = "+X"
            assert min(run_obj.matrix_world.to_scale()) > expected_scale * 0.9
            source.source_forward_axis = "AUTO"
            assert bpy.ops.fbr.preview_tpose(file_index=file_index, action="HIDE") == {"FINISHED"}
            source.preview_clip = "0"
            assert bpy.ops.fbr.preview_animation(file_index=file_index, action="SHOW") == {"FINISHED"}
            assert bpy.ops.fbr.auto_map(file_index=file_index) == {"FINISHED"}
            assert settings.preview_mode == "ANIMATION"
            assert min(run_obj.matrix_world.to_scale()) > expected_scale * 0.9
            assert bpy.ops.fbr.preview_animation(file_index=file_index, action="HIDE") == {"FINISHED"}
        mapping_index = _foot_mapping_index(source)
        assert bpy.ops.fbr.ik_settings(
            file_index=file_index,
            mapping_index=mapping_index,
            action="START",
        ) == {"FINISHED"}
        assert bpy.ops.fbr.ik_settings(
            file_index=file_index,
            mapping_index=mapping_index,
            action="OK",
        ) == {"FINISHED"}
        mapping = source.mappings[mapping_index]
        control_owner = next(
            (
                obj
                for obj in bpy.data.objects
                if obj.type == "ARMATURE" and mapping.ik_control_bone in obj.data.bones
            ),
            None,
        )
        control = (
            control_owner.data.bones.get(mapping.ik_control_bone)
            if control_owner
            else None
        )
        pole = (
            control_owner.data.bones.get(mapping.ik_pole_bone)
            if control_owner
            else None
        )
        print(
            "IK_SETUP",
            source.display_name,
            mapping.source_bone,
            mapping.target_bone,
            mapping.ik_control_bone,
            mapping.ik_pole_bone,
            control_owner.name if control_owner else None,
        )
        assert control and not control.use_deform
        assert pole and not pole.use_deform and pole.get("_fbr_ik_pole")
        lower = target.data.bones[mapping.target_bone].parent
        assert (pole.head_local - lower.head_local).length <= lower.length * 1.1 + 1.0e-4
        solver = target.pose.bones[mapping.target_bone].parent
        constraint = next(
            item
            for item in solver.constraints
            if item.type == "IK" and item.name.startswith("FBR IK")
        )
        assert constraint.subtarget == mapping.ik_control_bone
        assert constraint.pole_subtarget == mapping.ik_pole_bone
        assert constraint.chain_count == 2 and constraint.iterations == 500
        # The calibrated angle must place the knee nearer its own FK rest
        # direction than the opposite (180-degree flipped) pole angle.
        original_angle = constraint.pole_angle
        desired_joint = target.data.bones[solver.name].head_local.copy()
        original_error = (solver.head - desired_joint).length
        constraint.pole_angle = original_angle + math.pi
        bpy.context.view_layer.update()
        flipped_error = (solver.head - desired_joint).length
        constraint.pole_angle = original_angle
        bpy.context.view_layer.update()
        assert original_error < flipped_error, (original_error, flipped_error)
        ik_controls.append(
            {
                "name": mapping.ik_control_bone,
                "pole": mapping.ik_pole_bone,
                "owner": control_owner.name,
                "source": mapping.source_bone,
                "target": mapping.target_bone,
            }
        )

    hand_source = settings.files[0]
    left_hand_index = next(
        index for index, item in enumerate(hand_source.mappings)
        if item.target_bone == "Left_Hand"
    )
    assert bpy.ops.fbr.ik_settings(
        file_index=0, mapping_index=left_hand_index, action="START"
    ) == {"FINISHED"}
    assert bpy.ops.fbr.ik_settings(
        file_index=0, mapping_index=left_hand_index, action="OK"
    ) == {"FINISHED"}
    for hand_name in ("Left_Hand", "Right_Hand"):
        hand_mapping = next(
            item for item in hand_source.mappings if item.target_bone == hand_name
        )
        hand_solver = target.pose.bones[hand_name].parent
        hand_constraint = next(
            item for item in hand_solver.constraints
            if item.type == "IK" and item.name.startswith("FBR IK")
        )
        expected_elbow = target.data.bones[hand_solver.name].head_local.copy()
        calibrated_angle = hand_constraint.pole_angle
        calibrated_error = (hand_solver.head - expected_elbow).length
        hand_constraint.pole_angle = calibrated_angle + math.pi
        bpy.context.view_layer.update()
        flipped_error = (hand_solver.head - expected_elbow).length
        hand_constraint.pole_angle = calibrated_angle
        bpy.context.view_layer.update()
        print("IK_HAND_POLE", hand_name, calibrated_angle,
              calibrated_error, flipped_error)
        assert calibrated_error < flipped_error, hand_name
    assert bpy.ops.fbr.ik_settings(
        file_index=0, mapping_index=left_hand_index, action="RESET"
    ) == {"FINISHED"}

    run_index = next(
        index for index, item in enumerate(settings.files)
        if item.display_name == "Run.fbx"
    )
    run_source = settings.files[run_index]
    run_obj = bpy.data.objects[run_source.source_object]
    run_scale = min(run_obj.matrix_world.to_scale())
    assert bpy.ops.fbr.preview_tpose(file_index=run_index, action="SHOW") == {"FINISHED"}
    assert bpy.ops.fbr.auto_map(file_index=run_index) == {"FINISHED"}
    assert settings.preview_mode == "TPOSE"
    assert min(run_obj.matrix_world.to_scale()) > run_scale * 0.9
    assert bpy.ops.fbr.preview_tpose(file_index=run_index, action="HIDE") == {"FINISHED"}
    run_source.preview_clip = "0"
    assert bpy.ops.fbr.preview_animation(file_index=run_index, action="SHOW") == {"FINISHED"}
    assert bpy.ops.fbr.auto_map(file_index=run_index) == {"FINISHED"}
    assert settings.preview_mode == "ANIMATION"
    assert min(run_obj.matrix_world.to_scale()) > run_scale * 0.9
    assert bpy.ops.fbr.preview_animation(file_index=run_index, action="HIDE") == {"FINISHED"}
    run_foot_index = _foot_mapping_index(run_source)
    assert bpy.ops.fbr.ik_settings(
        file_index=run_index, mapping_index=run_foot_index, action="START"
    ) == {"FINISHED"}
    assert bpy.ops.fbr.ik_settings(
        file_index=run_index, mapping_index=run_foot_index, action="OK"
    ) == {"FINISHED"}

    for source in settings.files:
        for clip in source.clips:
            if clip.enabled:
                print(
                    "SOURCE_POSE_MOTION",
                    source.display_name,
                    clip.action_name,
                    _sample_pose_motion(settings, source, bpy.data.actions[clip.action_name]),
                    source.source_object,
                    [slot.identifier for slot in bpy.data.actions[clip.action_name].slots],
                )
        if source.mapping_is_independent:
            source_obj = bpy.data.objects[source.source_object]
            print(
                "AXIS_BASIS",
                source.display_name,
                tuple(round(value, 6) for value in _character_basis(source_obj)),
                tuple(round(value, 6) for value in _character_basis(target)),
                tuple(round(value, 6) for value in source.global_axis_correction),
            )

    before_actions = {action.as_pointer() for action in bpy.data.actions}
    assert bpy.ops.fbr.retarget() == {"FINISHED"}
    outputs = [
        action
        for action in bpy.data.actions
        if action.as_pointer() not in before_actions
    ]
    assert len(outputs) == 5, [action.name for action in outputs]

    target_height = max(target.dimensions.length, 1.0)
    report = {
        "enabled": enabled,
        "ik_controls": ik_controls,
        "outputs": [],
    }
    static_failures = []
    for action in outputs:
        assert not any(
            'pose.bones["Left_Foot"].' in curve.data_path
            for curve in iter_action_fcurves(action)
        ), f"{action.name} 的腳仍保留直接 FK Key"
        values = _curve_values(action)
        assert values and all(math.isfinite(value) for value in values)
        dynamic_curve_count = _dynamic_curve_count(action)
        if source_dynamic.get(action.name, 0):
            if not dynamic_curve_count:
                static_failures.append(action.name)
        control_values = [
            point.co.y
            for curve in iter_action_fcurves(action)
            if any(item["name"] in curve.data_path for item in ik_controls)
            and "location" in curve.data_path
            for point in curve.keyframe_points
        ]
        assert control_values
        assert max(abs(value) for value in control_values) < target_height * 20.0
        assign_action_and_slot(target, action)
        control_distances = []
        for frame in (
            action.frame_range[0],
            sum(action.frame_range) * 0.5,
            action.frame_range[1],
        ):
            bpy.context.scene.frame_set(round(frame))
            bpy.context.view_layer.update()
            for item in ik_controls:
                control = target.pose.bones.get(item["name"])
                foot = target.pose.bones.get(item["target"])
                if control and foot:
                    control_distances.append(
                        min(
                            (control.matrix.translation - foot.head).length,
                            (control.matrix.translation - foot.tail).length,
                        )
                    )
        assert control_distances
        print("IK_FOOT_DISTANCE", action.name, max(control_distances), target_height)
        assert max(control_distances) < target_height * 0.12
        root_z = [
            point.co.y
            for curve in iter_action_fcurves(action)
            if "location" in curve.data_path and curve.array_index == 2
            and any(token in curve.data_path.casefold() for token in ("hip", "root"))
            for point in curve.keyframe_points
        ]
        if root_z:
            assert max(root_z) - min(root_z) < target_height * 2.0
        report["outputs"].append(
            {
                "name": action.name,
                "frames": [float(value) for value in action.frame_range],
                "curve_count": sum(1 for _curve in iter_action_fcurves(action)),
                "source_dynamic_curve_count": source_dynamic.get(action.name, 0),
                "dynamic_curve_count": dynamic_curve_count,
                "max_control_abs": max(abs(value) for value in control_values),
                "max_control_to_foot": max(control_distances),
                "root_z_range": (max(root_z) - min(root_z)) if root_z else None,
            }
        )

    print("FBR_PROJECT_RETARGET=" + json.dumps(report, ensure_ascii=False, sort_keys=True))
    assert not static_failures, f"輸出被烘焙成靜止姿勢：{static_failures}"

    # Compare the IK result with the same Run clip baked without IK. The
    # control following the foot alone does not prove the knee was preserved.
    run_mapping_owner = mapping_source(settings, run_source)
    run_mapping = run_mapping_owner.mappings[_foot_mapping_index(run_mapping_owner)]
    run_output = next(action for action in outputs if action.name == "Run_Run")
    baseline = bpy.data.actions.new("FBR_Test_Run_NoIK")
    solver = target.pose.bones[run_mapping.target_bone].parent
    constraint = next(
        item for item in solver.constraints
        if item.type == "IK" and item.name.startswith("FBR IK")
    )
    run_mapping.ik_enabled = False
    constraint.mute = True
    try:
        bake_clip(
            bpy.context, settings, run_source, run_source.clips[0],
            target, baseline, 1,
        )
    finally:
        run_mapping.ik_enabled = True
        constraint.mute = False
    samples = {}
    for label, action, muted in (
        ("no_ik", baseline, True), ("ik", run_output, False),
    ):
        _clear_target_pose(target)
        constraint.mute = muted
        assign_action_and_slot(target, action)
        samples[label] = []
        for frame in (1, 5, 10, 15, 20):
            bpy.context.scene.frame_set(frame)
            bpy.context.view_layer.update()
            lower = target.pose.bones[run_mapping.target_bone].parent
            foot = target.pose.bones[run_mapping.target_bone]
            samples[label].append((lower.head.copy(), foot.head.copy()))
    constraint.mute = False
    joint_errors = [
        (ik[0] - fk[0]).length
        for fk, ik in zip(samples["no_ik"], samples["ik"])
    ]
    foot_errors = [
        (ik[1] - fk[1]).length
        for fk, ik in zip(samples["no_ik"], samples["ik"])
    ]
    print("FBR_IK_FK_FRAMES", [
        (round(joint, 5), round(foot, 5))
        for joint, foot in zip(joint_errors, foot_errors)
    ])
    print("FBR_IK_FK_COMPARISON", max(joint_errors), max(foot_errors), target_height)
    assert max(joint_errors) < target_height * 0.02
    assert max(foot_errors) < target_height * 0.01


if __name__ == "__main__":
    main()
