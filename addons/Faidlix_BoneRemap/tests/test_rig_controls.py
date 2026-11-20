# Run with Blender --background --factory-startup --python-exit-code 1 --python this file.
# Set FBR_TEST_MODULE to test an installed package instead of the source tree.
import importlib
import os
from pathlib import Path
import sys

import bpy


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
addon = importlib.import_module(os.environ.get("FBR_TEST_MODULE", "Faidlix_BoneRemap"))
if not hasattr(bpy.types.Scene, "fbr_settings"):
    addon.register()

rig = bpy.data.objects.new("Test Rig", bpy.data.armatures.new("Test Armature"))
bpy.context.collection.objects.link(rig)
bpy.context.view_layer.objects.active = rig
rig.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")
parent = None
for name, head, tail in (
    ("Thigh", (0, 0, 2), (0, -0.2, 1)),
    ("Shin", (0, -0.2, 1), (0, 0, 0)),
    ("Foot", (0, 0, 0), (0, -0.4, 0)),
):
    bone = rig.data.edit_bones.new(name)
    bone.head, bone.tail, bone.parent = head, tail, parent
    parent = bone
bpy.ops.object.mode_set(mode="OBJECT")
settings = bpy.context.scene.fbr_settings
settings.target_armature = rig.name
assert not settings.files

assert bpy.ops.fbr.rig_bone(bone_name="Shin", action="SELECT") == {"FINISHED"}
assert rig.mode == "POSE" and rig.data.bones.active.name == "Shin"
assert bpy.ops.fbr.rig_bone(bone_name="Shin", action="TWIST") == {"FINISHED"}
original, twist = rig.data.bones["Shin"], rig.data.bones["Shin_Twist"]
assert twist.parent == original and not twist.use_connect
assert (twist.head_local - original.head_local).length < 1e-6
assert (twist.tail_local - original.tail_local).length < 1e-6
assert twist.matrix_local.to_quaternion().rotation_difference(
    original.matrix_local.to_quaternion()
).angle < 1e-5

assert bpy.ops.fbr.rig_bone(bone_name="Shin_Twist", action="ROTATION") == {"FINISHED"}
rotation = rig.pose.bones["Shin_Twist"].constraints[0]
assert rotation.type == "COPY_ROTATION" and rotation.target == rig and rotation.subtarget == "Shin"
assert (rotation.use_x, rotation.use_y, rotation.use_z) == (True, False, False)
assert not (rotation.invert_x or rotation.invert_y or rotation.invert_z)
assert rotation.mix_mode == "REPLACE" and rotation.influence == 1.0
assert rotation.target_space == rotation.owner_space == "LOCAL"
assert bpy.ops.fbr.rig_bone(bone_name="Shin_Twist", action="CLEAR_TARGET") == {"FINISHED"}
assert rotation.subtarget == ""
rotation.subtarget = "Thigh"
assert bpy.ops.fbr.rig_bone(bone_name="Shin_Twist", action="ROTATION") == {"FINISHED"}
assert rotation.subtarget == "Thigh" and len(rig.pose.bones["Shin_Twist"].constraints) == 1
assert bpy.ops.fbr.rig_bone(action="CONFIRM") == {"FINISHED"}
rotation.name = "Existing rotation"
assert bpy.ops.fbr.rig_bone(bone_name="Shin_Twist", action="ROTATION") == {"FINISHED"}
rotation.influence = 0.3
assert bpy.ops.fbr.rig_bone(action="CANCEL") == {"FINISHED"}
assert rotation.influence == 1.0
assert bpy.ops.fbr.rig_bone(bone_name="Shin_Twist", action="ROTATION") == {"FINISHED"}
assert bpy.ops.fbr.rig_bone(action="DELETE") == {"FINISHED"}
assert not rig.pose.bones["Shin_Twist"].constraints
assert bpy.ops.fbr.rig_bone(bone_name="Shin_Twist", action="ROTATION") == {"FINISHED"}
assert bpy.ops.fbr.rig_bone(action="CANCEL") == {"FINISHED"}
assert not rig.pose.bones["Shin_Twist"].constraints

assert bpy.ops.fbr.ik_settings(file_index=-1, bone_name="Foot", action="START") == {"FINISHED"}
group = settings.rig_controls[0]
mapping = group.mappings[group.active_mapping_index]
assert group.ik_editing and mapping.target_bone == "Foot"
assert mapping.ik_control_bone in rig.pose.bones and mapping.ik_pole_bone in rig.pose.bones
assert bpy.ops.fbr.set_ik_shape(file_index=-1, mapping_index=group.active_mapping_index, shape="CIRCLE") == {"FINISHED"}
assert mapping.ik_shape == "CIRCLE"
assert bpy.ops.fbr.ik_settings(file_index=-1, action="OK") == {"FINISHED"}
assert not group.ik_editing and not settings.files
assert addon.operators.rig_ik_bindings(rig)["Thigh"][0].name == "Foot"
assert bpy.ops.fbr.ik_settings(file_index=-1, bone_name="Thigh", action="START") == {"FINISHED"}
assert group.mappings[group.active_mapping_index].target_bone == "Foot"
assert bpy.ops.fbr.ik_settings(file_index=-1, action="CANCEL") == {"FINISHED"}
assert bpy.ops.fbr.ik_settings(file_index=-1, bone_name="Foot", action="START") == {"FINISHED"}
assert bpy.ops.fbr.delete_ik(file_index=-1) == {"FINISHED"}
assert not any(bone.get("_fbr_ik_control") for bone in rig.data.bones)

signature = (
    ("Hand.L", ""), ("Hand.R", ""),
    ("Index01.L", "Hand.L"), ("Index02.L", "Index01.L"),
    ("Index01.R", "Hand.R"), ("Index02.R", "Index01.R"),
)
representative, parents, children, ordered = addon.ui._rig_tree(signature)
assert representative["Index02.R"] == "Index02.L"
assert parents["Index02.L"] == "Index01.L" and children["Hand.L"] == ["Index01.L"]
assert ordered[:3] == ["Hand.L", "Index01.L", "Index02.L"]
bpy.ops.object.mode_set(mode="POSE")
rig.data.bones.active = rig.data.bones["Foot"]
addon.ui.sync_rig_bone_selection(settings, rig)
assert rig.pose.bones[settings.rig_bone_index].name == "Foot"
assert bpy.ops.fbr.rig_bone(bone_name="Foot", action="VISIBILITY") == {"FINISHED"}
visibility = rig.pose.bones["Foot"]
assert (visibility if hasattr(visibility, "hide") else visibility.bone).hide
print("FBR_RIG_CONTROLS_OK")
