"""Background-only check on a copy of character 1008; does not save the blend."""

import json
import importlib
import os
import sys
from pathlib import Path

import bpy

if os.environ.get("FBR_TEST_INSTALLED"):
    addon = importlib.import_module("bl_ext.user_default.faidlix_bone_remap")
elif os.environ.get("FBR_TEST_BASELINE"):
    sys.path.insert(0, os.environ["FBR_TEST_BASELINE"])
    addon = importlib.import_module("faidlix_bone_remap")
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    addon = importlib.import_module("Faidlix_BoneRemap")
assign_action_and_slot = addon.retarget.assign_action_and_slot
bake_clip = addon.retarget.bake_clip


if not hasattr(bpy.types.Scene, "fbr_settings"):
    addon.register()
settings = bpy.context.scene.fbr_settings
settings.ik_bake_mode = "EXISTING"
if hasattr(settings, "use_source_ik"):
    settings.use_source_ik = True
target = bpy.data.objects[settings.target_armature]
target.data.use_mirror_x = False
if os.environ.get("FBR_TEST_BASELINE") and target.mode == "EDIT":
    bpy.ops.object.mode_set(mode="OBJECT")
source_file = next(item for item in settings.files if item.display_name == "fairy-new-model.blend")
source = bpy.data.objects[source_file.source_object]
assert not addon.retarget.source_has_ik(source, source_file.mappings)
source.hide_viewport = False
source.hide_set(False)
clip = next(item for item in source_file.clips if item.action_name == "Fairy_Dive")
settings.naming_mode = "ACTION"
addon.operators._reserve_source_action_names(settings, [(source_file, clip, False)])
action = addon.retarget.source_action_for_clip(clip)
assert action.name == "Org_Fairy_Dive"
assert bpy.data.actions.get("Fairy_Dive") is not action
constraints = tuple(
    constraint for bone in target.pose.bones for constraint in bone.constraints
    if constraint.type == "IK"
)
saved_mutes = tuple((constraint, constraint.mute) for constraint in constraints)
try:
    for constraint in constraints:
        if constraint.name.startswith("FBR IK"):
            constraint.mute = False
    output = bpy.data.actions.new("FBR_1008_Existing_IK_Test")
    bake_clip(bpy.context, settings, source_file, clip, target, output, 1)
    assert any(
        curve.data_path == 'pose.bones["FBR_IK_Foot.L"].location'
        and any(abs(point.co.y) > 1.0e-4 for point in curve.keyframe_points)
        for curve in addon.model.iter_action_fcurves(output)
    )
    first, last = (round(value) for value in action.frame_range)
    results = {}
    source.animation_data.use_nla = False
    target.animation_data.use_nla = False
    for source_frame in (first, (first + last) // 2, last):
        assign_action_and_slot(source, action)
        bpy.context.scene.frame_set(source_frame)
        bpy.context.view_layer.update()
        source_eval = source.evaluated_get(bpy.context.evaluated_depsgraph_get())
        source_positions = {
            name: source_eval.matrix_world @ source_eval.pose.bones[name].head.copy()
            for name in ("Left_Foot", "Right_Foot")
        }
        assign_action_and_slot(target, output)
        addon.retarget._clear_target_pose(target)
        bpy.context.scene.frame_set(source_frame - first + 1)
        bpy.context.view_layer.update()
        target_eval = target.evaluated_get(bpy.context.evaluated_depsgraph_get())
        results[source_frame] = {
            name: round((source_positions[name] - (
                target_eval.matrix_world @ target_eval.pose.bones[name].head
            )).length, 6)
            for name in source_positions
        }
    print("FBR_1008_EXISTING_IK=" + json.dumps(results))
    assert max(value for values in results.values() for value in values.values()) < 0.04
    foot_index = next(
        index for index, mapping in enumerate(source_file.mappings)
        if mapping.target_bone == "Left_Foot"
    )
    assert bpy.ops.fbr.ik_settings(file_index=0, mapping_index=foot_index, action="START") == {"FINISHED"}
    assert source_file.ik_existing_view
    assert bpy.ops.fbr.delete_ik(file_index=0, mapping_index=foot_index) == {"FINISHED"}
    assert not any(c.type == "IK" for c in target.pose.bones["Left_LowerLeg"].constraints)
    assert "FBR_IK_Foot.L" not in target.data.bones
finally:
    for constraint, muted in saved_mutes:
        constraint.mute = muted
