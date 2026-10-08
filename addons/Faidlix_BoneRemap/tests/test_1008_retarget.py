"""Run on a copy loaded in background; never saves the user's 1008 blend."""

import json
import math
import sys
from pathlib import Path

import bpy

ADDON_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ADDON_ROOT.parent))

import Faidlix_BoneRemap as addon  # noqa: E402
from Faidlix_BoneRemap.retarget import (  # noqa: E402
    _clear_target_pose,
    assign_action_and_slot,
    bake_clip,
)


def _positions(obj, names, action, frame):
    assign_action_and_slot(obj, action)
    obj.animation_data.use_nla = False
    if obj.name == "Armature":
        _clear_target_pose(obj)
    bpy.context.scene.frame_set(frame)
    bpy.context.view_layer.update()
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    return {
        name: (
            evaluated.matrix_world @ evaluated.pose.bones[name].head.copy(),
            (evaluated.matrix_world.to_3x3() @
             (evaluated.pose.bones[name].tail - evaluated.pose.bones[name].head)).normalized(),
        )
        for name in names
    }


def main():
    if not hasattr(bpy.types.Scene, "fbr_settings"):
        addon.register()
    settings = bpy.context.scene.fbr_settings
    target = bpy.data.objects[settings.target_armature]
    source_file = next(
        item for item in settings.files if item.display_name == "fairy-new-model.blend"
    )
    source_obj = bpy.data.objects[source_file.source_object]
    source_obj.hide_viewport = False
    source_obj.hide_set(False)
    target.data.use_mirror_x = False
    names = ("Left_Hand", "Right_Hand", "Left_Foot", "Right_Foot")
    all_constraints = [
        constraint for bone in target.pose.bones for constraint in bone.constraints
        if constraint.type == "IK" and constraint.name.startswith("FBR IK")
    ]
    ik_mappings = [item for item in source_file.mappings if item.ik_enabled]
    report = []
    for action_name in ("Fairy_Dive", "Fairy_Run", "Fairy_CoverEars"):
        clip = next(item for item in source_file.clips if item.action_name == action_name)
        source_action = bpy.data.actions[action_name]
        outputs = {}
        for use_ik in (False, True):
            for mapping in ik_mappings:
                mapping.ik_enabled = use_ik
            for constraint in all_constraints:
                constraint.mute = not use_ik
            output = bpy.data.actions.new(f"FBR_1008_Test_{action_name}_{use_ik}")
            bake_clip(
                bpy.context, settings, source_file, clip,
                target, output, 1,
            )
            outputs[use_ik] = output
        for mapping in ik_mappings:
            mapping.ik_enabled = True
        for constraint in all_constraints:
            constraint.mute = False
        start, end = (round(value) for value in source_action.frame_range)
        frames = sorted({start, (start + end) // 2, end})
        errors = {"no_ik": {name: 0.0 for name in names},
                  "ik": {name: 0.0 for name in names}}
        direction_errors = {"no_ik": {name: 0.0 for name in names},
                            "ik": {name: 0.0 for name in names}}
        for source_frame in frames:
            source_positions = _positions(source_obj, names, source_action, source_frame)
            for use_ik, label in ((False, "no_ik"), (True, "ik")):
                for constraint in all_constraints:
                    constraint.mute = not use_ik
                output_positions = _positions(
                    target, names, outputs[use_ik],
                    source_frame - start + 1,
                )
                for name in names:
                    errors[label][name] = max(
                        errors[label][name],
                        (source_positions[name][0] - output_positions[name][0]).length,
                    )
                    direction_errors[label][name] = max(
                        direction_errors[label][name],
                        math.degrees(source_positions[name][1].angle(output_positions[name][1])),
                    )
        report.append({
            "action": action_name,
            "frames": frames,
            "errors": {
                mode: {name: round(value, 6) for name, value in values.items()}
                for mode, values in errors.items()
            },
            "direction_errors_deg": {
                mode: {name: round(value, 3) for name, value in values.items()}
                for mode, values in direction_errors.items()
            },
        })
    print("FBR_1008_RETARGET=" + json.dumps(report, ensure_ascii=False))
    assert max(
        item["errors"][mode][name]
        for item in report for mode in ("no_ik", "ik")
        for name in ("Left_Hand", "Right_Hand")
    ) < 0.05, "Hand endpoint deviated from source pose"
    assert max(
        item["errors"][mode][name]
        for item in report for mode in ("no_ik", "ik")
        for name in ("Left_Foot", "Right_Foot")
    ) < 0.02, "Foot endpoint deviated from source pose"
    assert max(
        item["direction_errors_deg"][mode][name]
        for item in report for mode in ("no_ik", "ik")
        for name in names
    ) < 5.0, "Hand or foot direction deviated from source pose"


if __name__ == "__main__":
    main()
