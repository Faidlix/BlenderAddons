import importlib.util
import os

import bpy


source = os.environ["FAIDLIX_BAKEMAP_SOURCE"]
spec = importlib.util.spec_from_file_location("faidlix_bakemap_source_test", source)
addon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(addon)

assert addon.ADDON_VERSION == (2, 3, 9)
assert addon._version_tuple("2.3") == (2, 3, 0)
assert addon._version_tuple("bad") == ()
assert [label for _value, label, _description in addon.SIZE_ITEMS] == [
    "256", "512", "1024", "2048", "4096", "Custom",
]
assert hasattr(bpy.ops.wm, "context_set_enum")

addon.register()
try:
    assert hasattr(bpy.types.Scene, "faidlix_bakemap")
    assert hasattr(bpy.types, "FAIDLIX_OT_online_update")
    assert not hasattr(bpy.types, "FAIDLIX_PT_bakemap_updates")
    assert 'DEFAULT_CLOSED' in addon.FAIDLIX_PT_bakemap.bl_options
    assert hasattr(addon, "_schedule_online_update_install")
    assert not hasattr(addon, "_schedule_updated_addon_reload")
    assert bpy.ops.faidlix.online_update.poll()
    if not bpy.app.online_access:
        online_preference = bpy.context.preferences.system.use_online_access
        try:
            bpy.ops.faidlix.online_update()
        except RuntimeError as exc:
            assert "Enable Allow Online Access" in str(exc)
        else:
            raise AssertionError("Offline update check should be cancelled")
        assert bpy.context.preferences.system.use_online_access == online_preference
        assert bpy.context.scene.faidlix_bakemap.update_status == "需開啟網路權限"

    settings = bpy.context.scene.faidlix_bakemap
    assert bpy.ops.wm.context_set_enum(
        data_path="scene.faidlix_bakemap.diffuse_size",
        value="256",
    ) == {'FINISHED'}
    assert settings.diffuse_size == "256"
    reference = settings.references.add()
    assert bpy.ops.wm.context_set_enum(
        data_path=f"scene.{reference.path_from_id()}.source_scope",
        value="VERTEX_GROUP",
    ) == {'FINISHED'}
    assert reference.source_scope == "VERTEX_GROUP"
    mapping = settings.material_mappings.add()
    output = mapping.outputs.add()
    assert bpy.ops.wm.context_set_enum(
        data_path=f"scene.{output.path_from_id()}.size",
        value="4096",
    ) == {'FINISHED'}
    assert output.size == "4096"
    preserved_image = bpy.data.images.new("FaidlixResetPreservedImage", 1, 1)
    preserved_material = bpy.data.materials.new("FaidlixResetPreservedMaterial")
    settings.bake_emit = True
    settings.texture_name = "TemporaryName"
    assert bpy.ops.faidlix.reset_all() == {'FINISHED'}
    assert preserved_image.name in bpy.data.images
    assert preserved_material.name in bpy.data.materials
    assert not settings.bake_emit
    assert settings.bake_diffuse
    assert settings.texture_name == ""
    assert settings.update_status == ""
    assert len(settings.references) == 0
    bpy.data.images.remove(preserved_image)
    bpy.data.materials.remove(preserved_material)
finally:
    addon.unregister()

assert not hasattr(bpy.types.Scene, "faidlix_bakemap")
print("FAIDLIX_BAKEMAP_SOURCE_TEST=PASS")
