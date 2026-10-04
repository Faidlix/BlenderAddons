import os
import shutil
import sys

import bpy


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE_BLEND = os.path.join(ROOT, "tests", "_multi_action_source.blend")
SOURCE_TREE = os.path.join(ROOT, "tests", "_animation_tree")
sys.path.insert(0, os.path.dirname(ROOT))

import Faidlix_BoneRemap as addon
from Faidlix_BoneRemap.model import reuse_mapping_items
from Faidlix_BoneRemap.operators import TEMP_COLLECTION_NAME
from Faidlix_BoneRemap.ui import _reused_mapping_sources


def create_rig(name):
    data = bpy.data.armatures.new(name + "Data")
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bone = data.edit_bones.new("Hips")
    bone.head = (0, 0, 0)
    bone.tail = (0, 0, 1)
    bpy.ops.object.mode_set(mode="OBJECT")
    return obj


def add_action(obj, name, distance):
    action = bpy.data.actions.new(name)
    action.use_fake_user = True
    obj.animation_data_create()
    obj.animation_data.action = action
    pose = obj.pose.bones["Hips"]
    pose.location = (0, 0, 0)
    pose.keyframe_insert("location", frame=1)
    pose.location = (0, distance, 0)
    pose.keyframe_insert("location", frame=8)
    return action


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    addon.register()
    source = create_rig("ImportedRig")
    walk = add_action(source, "Walk", 1.0)
    run = add_action(source, "Run", 3.0)
    source.animation_data.action = walk
    bpy.ops.wm.save_as_mainfile(filepath=SOURCE_BLEND)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    target = create_rig("Main_Rig")
    settings = bpy.context.scene.fbr_settings
    settings.target_armature = target.name
    result = bpy.ops.fbr.import_files(
        filepath=SOURCE_BLEND,
        files=[{"name": os.path.basename(SOURCE_BLEND)}],
    )
    assert result == {"FINISHED"}, result
    assert len(settings.files) == 1
    assert hasattr(settings.files[0], "reused_expanded")
    assert not settings.files[0].mapping_expanded
    names = {clip.action_name for clip in settings.files[0].clips}
    assert {"Walk", "Run"}.issubset(names), names
    assert settings.files[0].mappings[0].target_bone == "Hips"
    first_source_name = settings.files[0].source_object
    first_source = bpy.data.objects[first_source_name]
    assert first_source.hide_get()
    assert first_source.users_collection[0].name == TEMP_COLLECTION_NAME
    assert {obj.name for obj in bpy.context.scene.objects if not obj.hide_get()} == {target.name}
    first_uid = settings.files[0].uid
    result = bpy.ops.fbr.import_files(filepath=SOURCE_BLEND)
    assert result == {"FINISHED"}, result
    assert len(settings.files) == 2
    assert settings.files[1].reuse_mapping == first_uid
    assert not settings.files[1].mapping_is_independent
    assert not settings.files[1].mapping_expanded
    assert list(_reused_mapping_sources(settings, settings.files[0])) == [
        settings.files[1]
    ]
    enum_items = reuse_mapping_items(settings.files[1], bpy.context)
    assert enum_items is reuse_mapping_items(settings.files[1], bpy.context)
    assert any(identifier == first_uid and "沿用" in label for identifier, label, _ in enum_items)
    assert len(settings.files[1].mappings) == 0
    assert bpy.ops.fbr.set_reuse_mapping(file_index=1, reuse_uid="SELF") == {"FINISHED"}
    assert settings.files[1].mapping_is_independent
    assert settings.files[1].mapping_expanded
    assert settings.files[1].mappings[0].target_bone == "Hips"
    settings.files[1].reuse_mapping = first_uid
    assert not settings.files[1].mapping_is_independent
    imported_names = {source.source_object for source in settings.files}
    for source_index, source_file in enumerate(settings.files):
        for clip in source_file.clips:
            clip.enabled = source_index == 0 and clip.action_name == "Walk"
    result = bpy.ops.fbr.retarget()
    assert result == {"FINISHED"}, result
    assert len(settings.files) == 2
    assert bpy.data.collections.get(TEMP_COLLECTION_NAME) is not None
    assert all(bpy.data.objects.get(name) is not None for name in imported_names)
    assert bpy.data.objects.get(target.name) == target
    assert target.animation_data.action is not None
    assert target.animation_data.action_slot is not None
    assert any(
        slot == target.animation_data.action_slot
        for slot in target.animation_data.action.slots
    )
    assert bpy.ops.fbr.clear_files() == {"FINISHED"}
    assert len(settings.files) == 0
    assert bpy.data.collections.get(TEMP_COLLECTION_NAME) is None
    assert all(bpy.data.objects.get(name) is None for name in imported_names)
    nested = os.path.join(SOURCE_TREE, "nested")
    os.makedirs(nested, exist_ok=True)
    shutil.copy2(SOURCE_BLEND, os.path.join(SOURCE_TREE, "first.blend"))
    shutil.copy2(SOURCE_BLEND, os.path.join(nested, "second.blend"))
    result = bpy.ops.fbr.import_folder(directory=SOURCE_TREE)
    assert result == {"FINISHED"}, result
    assert len(settings.files) == 2
    imported_files = {os.path.basename(source.filepath) for source in settings.files}
    assert imported_files == {"first.blend", "second.blend"}, imported_files
    assert bpy.ops.fbr.clear_files() == {"FINISHED"}
    print("FBR_MULTI_ACTION_IMPORT_OK")
    addon.unregister()
    if os.path.exists(SOURCE_BLEND):
        os.remove(SOURCE_BLEND)
    if os.path.isdir(SOURCE_TREE):
        shutil.rmtree(SOURCE_TREE)


if __name__ == "__main__":
    main()
