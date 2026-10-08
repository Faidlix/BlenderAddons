"""Run with Blender --background --factory-startup --python test_disconnected_source.py."""

import importlib
import os
import sys
from pathlib import Path

import bpy
from mathutils import Vector

if os.environ.get("FBR_TEST_INSTALLED"):
    addon = importlib.import_module("bl_ext.user_default.faidlix_bone_remap")
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    addon = importlib.import_module("Faidlix_BoneRemap")


def make_rig(name, disconnected=False):
    data = bpy.data.armatures.new(name + "Data")
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")

    def bone(name, head, tail, parent=None):
        item = data.edit_bones.new(name)
        item.head, item.tail = head, tail
        if parent:
            item.parent = data.edit_bones[parent]
        return item

    bone("Hips", (0, 0, 1), (0, 0.2, 1))
    bone("Head", (0, 1.8, 1), (0, 2, 1), "Hips")
    bone("Left_Eye", (0.1, 1.9, 1.2), (0.1, 1.9, 1.3), "Head")
    bone("Right_Eye", (-0.1, 1.9, 1.2), (-0.1, 1.9, 1.3), "Head")
    for side, sign in (("Left", 1), ("Right", -1)):
        upper_head = (sign * 0.2, 0, 1)
        upper_tail = (sign * 0.2, 0.1, 0.6)
        lower_head = (sign * 1.2, 0.1, 0.6) if disconnected and sign < 0 else upper_tail
        lower_tail = (lower_head[0], 0, 0.2)
        foot_head = (sign * 0.2, 0, 0.2) if disconnected and sign < 0 else lower_tail
        bone(side + "_UpperLeg", upper_head, upper_tail, "Hips")
        bone(side + "_LowerLeg", lower_head, lower_tail, side + "_UpperLeg")
        bone(side + "_Foot", foot_head, (foot_head[0], 0.2, 0.15), side + "_LowerLeg")
    bone("IK_Control", (-0.2, 0, 0.2), (-0.2, 0.2, 0.2))
    bpy.ops.object.mode_set(mode="OBJECT")
    obj.select_set(False)
    ik = obj.pose.bones["Right_LowerLeg"].constraints.new("IK")
    ik.target, ik.subtarget, ik.chain_count = obj, "IK_Control", 2
    return obj


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    addon.register()
    operators = addon.operators
    retarget = addon.retarget
    source = make_rig("Source", disconnected=True)
    target = make_rig("Target")
    settings = bpy.context.scene.fbr_settings
    settings.target_armature = target.name
    entry = settings.files.add()
    entry.uid = "disconnected-source-test"
    entry.source_object = source.name
    mapping = entry.mappings.add()
    mapping.source_bone = "Right_Foot"
    mapping.target_bone = "Right_Foot"

    axis_items = settings.files[0].bl_rna.properties["source_forward_axis"].enum_items
    assert {"+Z", "-Z"}.issubset({item.identifier for item in axis_items})
    assert (operators._character_basis(source, "+Z") @ Vector((0, -1, 0))).dot(Vector((0, 0, 1))) > 0.999
    assert (operators._character_basis(source, "-Z") @ Vector((0, -1, 0))).dot(Vector((0, 0, -1))) > 0.999
    assert bpy.ops.fbr.set_forward_axis(file_index=0, role="SOURCE", axis="+Z") == {"FINISHED"}
    assert entry.source_forward_axis == "+Z"
    assert bpy.ops.fbr.set_forward_axis(file_index=0, role="TARGET", axis="-Z") == {"FINISHED"}
    assert entry.target_forward_axis == "-Z"
    source_facing = source.matrix_world.to_3x3() @ (
        operators._character_basis(source, "+Z") @ Vector((0, -1, 0))
    )
    target_facing = target.matrix_world.to_3x3() @ (
        operators._character_basis(target, "-Z") @ Vector((0, -1, 0))
    )
    assert source_facing.normalized().dot(target_facing.normalized()) > 0.999

    assert retarget._source_chain_disconnected(source, "Right_Foot")
    assert not retarget._source_chain_disconnected(source, "Left_Foot")
    assert retarget._source_ik_bend_direction(source, target, "Right_Foot") is None
    assert retarget._source_ik_bend_direction(source, target, "Left_Foot") is not None
    assert not retarget.source_has_ik(source, entry.mappings)

    solver = target.pose.bones["Right_LowerLeg"]
    target_direction = retarget._ik_bend_direction(
        solver.parent.head, solver.head, solver.tail,
    )
    _position, fallback_direction = retarget._ik_pole_position(solver)
    assert target_direction is not None
    assert fallback_direction.dot(target_direction) > 0.999

    connected = make_rig("ConnectedSource")
    assert retarget.source_has_ik(connected, entry.mappings)
    print("FBR_DISCONNECTED_SOURCE_OK")


if __name__ == "__main__":
    main()
