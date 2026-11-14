"""Register BakeMap from source and verify its core UI and data helpers.

Run with Blender 5.2 in background mode and set FAIDLIX_BAKEMAP_SOURCE to the
add-on's __init__.py path.
"""

import importlib.util
import os

import bpy


source = os.environ["FAIDLIX_BAKEMAP_SOURCE"]
spec = importlib.util.spec_from_file_location("faidlix_bakemap_source_test", source)
addon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(addon)

assert addon.ADDON_VERSION == (2, 3, 22)
assert 'UV' in bpy.types.SpaceImageEditor.bl_rna.properties['mode'].enum_items.keys()
assert hasattr(addon.FAIDLIX_PT_bakemap, "draw_header_preset")
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
    assert hasattr(bpy.types, "FAIDLIX_OT_uv_material_map_select")
    assert hasattr(bpy.types, "FAIDLIX_MT_uv_material_maps")
    assert hasattr(bpy.types, "FAIDLIX_OT_uv_merge_self_to_nearest")
    assert hasattr(bpy.types, "FAIDLIX_OT_uv_merge_island_to_nearest")
    assert hasattr(bpy.types, "FAIDLIX_MT_uv_merge_to_nearest")
    assert addon._UV_COUNTERPART_DRAW_HANDLE is not None
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

    linked_a = bpy.data.images.new("FaidlixLinkedA", 1, 1)
    linked_b = bpy.data.images.new("FaidlixLinkedB", 1, 1)
    unlinked = bpy.data.images.new("FaidlixUnlinked", 1, 1)
    mesh = bpy.data.meshes.new("FaidlixMaterialMapMesh")
    material_object = bpy.data.objects.new("FaidlixMaterialMapObject", mesh)
    bpy.context.scene.collection.objects.link(material_object)
    materials = []
    for index, image in enumerate((linked_a, linked_b)):
        material = bpy.data.materials.new(f"FaidlixMaterial{index}")
        material.use_nodes = True
        principled = next(node for node in material.node_tree.nodes if node.type == 'BSDF_PRINCIPLED')
        image_node = material.node_tree.nodes.new('ShaderNodeTexImage')
        image_node.image = image
        material.node_tree.links.new(image_node.outputs['Color'], principled.inputs['Base Color'])
        if index == 0:
            unused_node = material.node_tree.nodes.new('ShaderNodeTexImage')
            unused_node.image = unlinked
        mesh.materials.append(material)
        materials.append(material)
    material_object.active_material_index = 1
    assert addon._linked_material_images(material_object) == [linked_b, linked_a]
    bpy.ops.object.select_all(action='DESELECT')
    material_object.select_set(True)
    bpy.context.view_layer.objects.active = material_object
    bpy.ops.object.mode_set(mode='EDIT')
    assert addon._leave_edit_mode(bpy.context)
    assert material_object.mode == 'OBJECT'
    bpy.data.objects.remove(material_object, do_unlink=True)
    bpy.data.meshes.remove(mesh)
    for material in materials:
        bpy.data.materials.remove(material)
    for image in (linked_a, linked_b, unlinked):
        bpy.data.images.remove(image)

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
    assert settings.show_uv_counterparts
    assert len(settings.references) == 0
    bpy.data.images.remove(preserved_image)
    bpy.data.materials.remove(preserved_material)
finally:
    addon.unregister()

assert not hasattr(bpy.types.Scene, "faidlix_bakemap")
assert addon._UV_COUNTERPART_DRAW_HANDLE is None
print("FAIDLIX_BAKEMAP_SOURCE_TEST=PASS")
