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
from Faidlix_BoneRemap.retarget import assign_action_and_slot, mapping_source
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
        assert bpy.ops.fbr.auto_map(file_index=file_index) == {"FINISHED"}
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
        print(
            "IK_SETUP",
            source.display_name,
            mapping.source_bone,
            mapping.target_bone,
            mapping.ik_control_bone,
            control_owner.name if control_owner else None,
        )
        assert control and not control.use_deform
        ik_controls.append(
            {
                "name": mapping.ik_control_bone,
                "owner": control_owner.name,
                "source": mapping.source_bone,
                "target": mapping.target_bone,
            }
        )

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
                "root_z_range": (max(root_z) - min(root_z)) if root_z else None,
            }
        )

    print("FBR_PROJECT_RETARGET=" + json.dumps(report, ensure_ascii=False, sort_keys=True))
    assert not static_failures, f"輸出被烘焙成靜止姿勢：{static_failures}"


if __name__ == "__main__":
    main()
