"""Run with Blender --background --factory-startup --python test_existing_ik.py."""

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
iter_action_fcurves = addon.model.iter_action_fcurves
_existing_ik_for_mapping = addon.retarget._existing_ik_for_mapping
assign_action_and_slot = addon.retarget.assign_action_and_slot
bake_clip = addon.retarget.bake_clip


def rig(name):
    data = bpy.data.armatures.new(name + "Data")
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bones = (
        ("Root", None, (0, 0, 0), (0, 0, 1)),
        ("Upper", "Root", (0, 0, 1), (0.1, 0, 0.6)),
        ("Lower", "Upper", (0.1, 0, 0.6), (0.1, 0, 0.2)),
        ("Foot", "Lower", (0.1, 0, 0.2), (0.1, -0.2, 0.1)),
        ("IK_Control", None, (0.1, 0, 0.2), (0.1, -0.1, 0.2)),
        ("Pole", None, (0.1, -0.5, 0.6), (0.1, -0.6, 0.6)),
    )
    for bone_name, parent_name, head, tail in bones:
        bone = data.edit_bones.new(bone_name)
        bone.head, bone.tail = head, tail
        if parent_name:
            bone.parent = data.edit_bones[parent_name]
        if bone_name in {"IK_Control", "Pole"}:
            bone.use_deform = False
    bpy.ops.object.mode_set(mode="OBJECT")
    obj.select_set(False)
    ik = obj.pose.bones["Lower"].constraints.new("IK")
    ik.name = "Existing Rig IK"
    ik.target, ik.subtarget = obj, "IK_Control"
    ik.pole_target, ik.pole_subtarget = obj, "Pole"
    ik.chain_count = 2
    ik.pole_angle = 0.25
    return obj, ik


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    addon.register()
    source, source_ik = rig("Source")
    target, target_ik = rig("Target")
    settings = bpy.context.scene.fbr_settings
    settings.target_armature = target.name
    settings.ik_bake_mode = "EXISTING"
    settings.key_mode = "BAKE"
    entry = settings.files.add()
    entry.uid = "existing-ik"
    entry.display_name = "ik.blend"
    entry.source_object = source.name
    for name in ("Root", "Upper", "Lower", "Foot"):
        mapping = entry.mappings.add()
        mapping.source_bone = mapping.target_bone = name
        if name == "Root":
            mapping.is_root = True
            mapping.transfer_location = True
    foot_mapping = entry.mappings[3]
    assert _existing_ik_for_mapping(target, foot_mapping)[1] == target_ik
    before_bones = tuple(target.data.bones.keys())
    assert bpy.ops.fbr.ik_settings(file_index=0, mapping_index=3, action="START") == {"FINISHED"}
    assert entry.ik_existing_view and not foot_mapping.ik_enabled
    assert tuple(target.data.bones.keys()) == before_bones
    assert bpy.ops.fbr.ik_settings(file_index=0, mapping_index=3, action="OK") == {"FINISHED"}
    assert not entry.ik_existing_view
    clip = entry.clips.add()
    action = bpy.data.actions.new("Source IK Movement")
    assign_action_and_slot(source, action)
    control = source.pose.bones["IK_Control"]
    for frame, y in ((1, 0.0), (10, -0.15)):
        control.location.y = y
        control.keyframe_insert("location", frame=frame, group=control.name)
    clip.action_name = action.name
    clip.frame_start, clip.frame_end = action.frame_range
    output = bpy.data.actions.new("Retarget Existing IK")
    before_constraints = tuple(target.pose.bones["Lower"].constraints.keys())
    original = (target_ik.target, target_ik.subtarget, target_ik.pole_target,
                target_ik.pole_subtarget, target_ik.chain_count, target_ik.pole_angle)
    bake_clip(bpy.context, settings, entry, clip, target, output, 1)
    assert tuple(target.data.bones.keys()) == before_bones
    assert tuple(target.pose.bones["Lower"].constraints.keys()) == before_constraints
    assert original == (target_ik.target, target_ik.subtarget, target_ik.pole_target,
                        target_ik.pole_subtarget, target_ik.chain_count, target_ik.pole_angle)
    assert any(
        curve.data_path == 'pose.bones["IK_Control"].location'
        for curve in iter_action_fcurves(output)
    )
    assert any(
        curve.data_path == 'pose.bones["Pole"].location'
        for curve in iter_action_fcurves(output)
    )
    positions = {}
    for frame in (1, 10):
        assign_action_and_slot(source, action)
        bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        source_position = source.evaluated_get(bpy.context.evaluated_depsgraph_get()).pose.bones["Foot"].head.copy()
        assign_action_and_slot(target, output)
        bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        target_position = target.evaluated_get(bpy.context.evaluated_depsgraph_get()).pose.bones["Foot"].head.copy()
        error = (source_position - target_position).length
        positions[frame] = (source_position, target_position, error)
        assert error < 0.1, (frame, source_position, target_position)
    assert (positions[1][0] - positions[10][0]).length > 0.05
    assert (positions[1][1] - positions[10][1]).length > 0.05
    print("FBR_EXISTING_IK_ERRORS", positions[1][2], positions[10][2])
    duplicate = target.pose.bones["Lower"].constraints.new("IK")
    duplicate.name = "Ambiguous IK"
    duplicate.target, duplicate.subtarget = target, "IK_Control"
    try:
        _existing_ik_for_mapping(target, foot_mapping)
    except RuntimeError as exc:
        assert "多組" in str(exc)
    else:
        raise AssertionError("Ambiguous IK should fail safely")
    target.pose.bones["Lower"].constraints.remove(duplicate)
    external = bpy.data.objects.new("External IK", None)
    bpy.context.collection.objects.link(external)
    target_ik.target = external
    try:
        _existing_ik_for_mapping(target, foot_mapping)
    except RuntimeError as exc:
        assert "外部" in str(exc)
    else:
        raise AssertionError("External IK should not be keyed silently")
    try:
        bpy.ops.fbr.ik_settings(file_index=0, mapping_index=3, action="START")
    except RuntimeError as exc:
        assert "外部" in str(exc)
    else:
        raise AssertionError("External IK editor should fail safely")
    assert tuple(target.data.bones.keys()) == before_bones
    target_ik.target = target
    print("FBR_EXISTING_IK_OK")


if __name__ == "__main__":
    main()
