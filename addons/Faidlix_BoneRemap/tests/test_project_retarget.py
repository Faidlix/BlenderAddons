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
    for source in settings.files:
        for clip in source.clips:
            if source.display_name == "fairy-new-model.blend":
                clip.enabled = clip.action_name in {"Fairy_Idle", "Fairy_Run"}
            else:
                clip.enabled = True
            if clip.enabled:
                enabled.append((source.display_name, clip.action_name))
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
    for action in outputs:
        values = _curve_values(action)
        assert values and all(math.isfinite(value) for value in values)
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
                "max_control_abs": max(abs(value) for value in control_values),
                "root_z_range": (max(root_z) - min(root_z)) if root_z else None,
            }
        )

    print("FBR_PROJECT_RETARGET=" + json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
