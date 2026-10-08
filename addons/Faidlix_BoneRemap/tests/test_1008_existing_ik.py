"""Background-only check on a copy of character 1008; does not save the blend."""

import json
import importlib
import os
import sys
from pathlib import Path

import bpy

if os.environ.get("FBR_TEST_INSTALLED"):
    addon = importlib.import_module("bl_ext.user_default.faidlix_bone_remap")
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    addon = importlib.import_module("Faidlix_BoneRemap")
assign_action_and_slot = addon.retarget.assign_action_and_slot
bake_clip = addon.retarget.bake_clip


if not hasattr(bpy.types.Scene, "fbr_settings"):
    addon.register()
settings = bpy.context.scene.fbr_settings
settings.ik_bake_mode = "EXISTING"
target = bpy.data.objects[settings.target_armature]
source_file = next(item for item in settings.files if item.display_name == "fairy-new-model.blend")
source = bpy.data.objects[source_file.source_object]
source.hide_viewport = False
source.hide_set(False)
action = bpy.data.actions["Fairy_Dive"]
clip = next(item for item in source_file.clips if item.action_name == action.name)
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
    first, last = (round(value) for value in action.frame_range)
    results = {}
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
finally:
    for constraint, muted in saved_mutes:
        constraint.mute = muted
