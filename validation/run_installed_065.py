import math
import os
from pathlib import Path

import bpy


PACKAGE = "bl_ext.FaidlixBlenderAdd_ons.faidlix_bone_remap"
installed = __import__(PACKAGE, fromlist=["*"])
test_path = (
    Path(__file__).resolve().parents[1]
    / "addons"
    / "Faidlix_BoneRemap"
    / "tests"
    / "test_project_retarget.py"
)
source = test_path.read_text(encoding="utf-8")
source = source.replace(
    "import Faidlix_BoneRemap as addon",
    "from bl_ext.FaidlixBlenderAdd_ons import faidlix_bone_remap as addon",
)
source = source.replace(
    "from Faidlix_BoneRemap.model",
    f"from {PACKAGE}.model",
)
source = source.replace(
    "from Faidlix_BoneRemap.retarget",
    f"from {PACKAGE}.retarget",
)
source = source.replace(
    "from Faidlix_BoneRemap.operators",
    f"from {PACKAGE}.operators",
)
namespace = {"__file__": str(test_path), "__name__": "__main__"}
exec(
    compile(source, str(test_path), "exec"),
    namespace,
)

from bl_ext.FaidlixBlenderAdd_ons.faidlix_bone_remap.retarget import (
    assign_action_and_slot,
    mapping_source,
)


def sample_rotations(obj, action, bone_names, frames):
    assign_action_and_slot(obj, action)
    samples = []
    for frame in frames:
        bpy.context.scene.frame_set(round(frame))
        bpy.context.view_layer.update()
        evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        samples.append({
            name: evaluated.pose.bones[name].matrix_basis.to_quaternion()
            for name in bone_names
            if name in evaluated.pose.bones
        })
    return samples


def compare_motion(source_file, source_action, output_action, target):
    source_obj = bpy.data.objects[source_file.source_object]
    owner = mapping_source(bpy.context.scene.fbr_settings, source_file)
    pairs = [
        (item.source_bone, item.target_bone)
        for item in owner.mappings
        if item.target_bone
        and item.source_bone in source_obj.pose.bones
        and item.target_bone in target.pose.bones
    ]
    fractions = [index / 8 for index in range(9)]
    source_range = source_action.frame_range
    output_range = output_action.frame_range
    source_frames = [source_range[0] + value * (source_range[1] - source_range[0]) for value in fractions]
    output_frames = [output_range[0] + value * (output_range[1] - output_range[0]) for value in fractions]
    source_samples = sample_rotations(source_obj, source_action, [a for a, _ in pairs], source_frames)
    target_samples = sample_rotations(target, output_action, [b for _, b in pairs], output_frames)
    source_values = []
    target_values = []
    for source_name, target_name in pairs:
        if source_name not in source_samples[0] or target_name not in target_samples[0]:
            continue
        source_zero = source_samples[0][source_name]
        target_zero = target_samples[0][target_name]
        for index in range(1, len(fractions)):
            source_values.append(source_zero.rotation_difference(source_samples[index][source_name]).angle)
            target_values.append(target_zero.rotation_difference(target_samples[index][target_name]).angle)
    dot = sum(a * b for a, b in zip(source_values, target_values))
    source_norm = math.sqrt(sum(value * value for value in source_values))
    target_norm = math.sqrt(sum(value * value for value in target_values))
    cosine = dot / max(source_norm * target_norm, 1.0e-12)
    mean_error = sum(abs(a - b) for a, b in zip(source_values, target_values)) / max(len(source_values), 1)
    return {
        "cosine_similarity": round(cosine, 6),
        "mean_angle_error_degrees": round(math.degrees(mean_error), 6),
        "mapped_bones": len(pairs),
        "samples": len(source_values),
    }


settings = bpy.context.scene.fbr_settings
target = bpy.data.objects[settings.target_armature]
similarity = {}
for source_file in settings.files:
    for clip in source_file.clips:
        if not clip.enabled:
            continue
        source_action = bpy.data.actions.get(clip.action_name)
        output_name = f"{os.path.splitext(source_file.display_name)[0]}_{clip.action_name}"
        output_action = bpy.data.actions.get(output_name)
        if source_action and output_action:
            similarity[output_name] = compare_motion(
                source_file,
                source_action,
                output_action,
                target,
            )
print("FBR_MOTION_SIMILARITY=" + __import__("json").dumps(similarity, sort_keys=True))
print("INSTALLED_PACKAGE_PATH=" + str(next(iter(installed.__path__))))
print("INSTALLED_PACKAGE_VERSION=" + ".".join(map(str, installed.ui.ADDON_VERSION)))
