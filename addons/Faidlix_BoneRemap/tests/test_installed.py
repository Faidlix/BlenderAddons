import bpy


def create_rig(name):
    armature = bpy.data.armatures.new(name + "Data")
    obj = bpy.data.objects.new(name, armature)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bone = armature.edit_bones.new("Hips")
    bone.head = (0.0, 0.0, 0.0)
    bone.tail = (0.0, 0.0, 1.0)
    bpy.ops.object.mode_set(mode="OBJECT")
    obj.select_set(False)
    return obj


def main():
    assert hasattr(bpy.ops.fbr, "retarget")
    assert hasattr(bpy.ops.fbr, "preview_animation")
    assert hasattr(bpy.ops.fbr, "ik_settings")
    assert hasattr(bpy.ops.fbr, "clear_target_animation")
    assert hasattr(bpy.types, "FBR_PT_main")
    source = create_rig("InstalledSource")
    target = create_rig("InstalledTarget")
    action = bpy.data.actions.new("InstalledWalk")
    source.animation_data_create()
    source.animation_data.action = action
    pose = source.pose.bones["Hips"]
    pose.location = (0.0, 0.0, 0.0)
    pose.keyframe_insert("location", frame=1)
    pose.location = (0.0, 1.0, 0.0)
    pose.keyframe_insert("location", frame=5)

    settings = bpy.context.scene.fbr_settings
    settings.target_armature = target.name
    entry = settings.files.add()
    entry.uid = "installed-source"
    entry.display_name = "installed.blend"
    entry.source_object = source.name
    entry.reuse_mapping = "SELF"
    clip = entry.clips.add()
    clip.action_name = action.name
    clip.frame_start, clip.frame_end = action.frame_range
    mapping = entry.mappings.add()
    mapping.source_bone = "Hips"
    mapping.target_bone = "Hips"
    mapping.is_root = True
    mapping.transfer_location = True

    assert bpy.ops.fbr.retarget() == {"FINISHED"}
    output = bpy.data.actions.get("installed_InstalledWalk")
    assert output is not None and output.use_fake_user
    assert len(settings.files) == 1
    print("FBR_INSTALLED_PACKAGE_OK")


if __name__ == "__main__":
    main()
