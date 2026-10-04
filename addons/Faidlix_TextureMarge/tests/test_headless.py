import importlib.util
import os
import tempfile

import bpy


ROOT = os.path.dirname(os.path.dirname(__file__))
ADDON_PATH = os.path.join(ROOT, "__init__.py")
SPEC = importlib.util.spec_from_file_location("blander_texture_marge", ADDON_PATH)
ADDON = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ADDON)
ADDON.register()

try:
    scene = bpy.context.scene
    settings = scene.ftm_settings
    bpy.ops.ftm.reset_all()
    assert ADDON.FTM_OT_online_update.bl_idname == "ftm.online_update"
    assert ADDON.bl_info['version'] == (1, 5, 7)
    assert ADDON.ADDON_VERSION == (1, 5, 7)
    assert hasattr(ADDON.FTM_PT_panel, "draw_header")
    assert ADDON.PACKAGE_ID == "blander_texture_marge"
    assert ADDON.GITHUB_REPOSITORY_URL.endswith("Faidlix/BlenderAddons/main/repository/index.json")
    assert ADDON._latest_version_from_index({"data": [
        {"id": "blander_texture_marge", "version": "1.5.7"},
        {"id": "faidlix_paint", "version": "0.4.8"},
    ]}) == (1, 5, 7)
    assert ADDON.FTM_PT_panel.bl_options == {'DEFAULT_CLOSED'}
    assert not hasattr(ADDON, "_reload_updated_addon")
    assert settings.update_status == ""
    settings.source_mode = 'MANUAL'
    settings.sources_expanded = False
    assert bpy.ops.ftm.add_source() == {'FINISHED'}
    assert settings.sources_expanded

    normal = bpy.data.images.new("Test_Normal", width=2, height=2, alpha=True)
    normal.pixels = [0.2, 0.4, 0.6, 1.0] * 4
    packed = bpy.data.images.new("Test_Packed", width=2, height=2, alpha=True)
    packed.pixels = [0.1, 0.3, 0.7, 1.0] * 4

    settings.sources[0].image = normal
    settings.sources[0].source_type = 'NORMAL'
    settings.sources[1].image = packed
    settings.sources[1].source_type = 'PACKED'
    assert bpy.ops.ftm.clear_source_image(index=1) == {'FINISHED'}
    assert settings.sources[1].image is None
    assert settings.sources[1].source_type == 'CUSTOM'
    settings.sources[1].image = packed
    settings.sources[1].source_type = 'PACKED'

    assert bpy.ops.ftm.edit_channel(target_channel='R') == {'FINISHED'}
    assert settings.editing_channel == 'R'
    cancel_term = next(term for term in next(item for item in settings.channels if item.channel == 'R').terms if term.source_uid == settings.sources[0].uid and term.source_channel == 'R')
    cancel_term.enabled = True
    assert bpy.ops.ftm.cancel_channel() == {'FINISHED'}
    assert settings.editing_channel == ''
    assert not any(term.enabled for term in next(item for item in settings.channels if item.channel == 'R').terms)
    assert bpy.ops.ftm.edit_channel(target_channel='R') == {'FINISHED'}
    confirm_term = next(term for term in next(item for item in settings.channels if item.channel == 'R').terms if term.source_uid == settings.sources[0].uid and term.source_channel == 'R')
    confirm_term.enabled = True
    assert bpy.ops.ftm.confirm_channel() == {'FINISHED'}
    assert settings.editing_channel == ''
    assert confirm_term.enabled

    mappings = {
        'R': [(settings.sources[0].uid, 'R')],
        'G': [(settings.sources[0].uid, 'G')],
        'B': [(settings.sources[1].uid, 'B')],
        'A': [(settings.sources[0].uid, 'B'), (settings.sources[1].uid, 'G')],
    }
    usages = {'R': 'NORMAL_X', 'G': 'NORMAL_Y', 'B': 'METALLIC', 'A': 'ROUGHNESS'}
    for channel_item in settings.channels:
        ADDON._sync_terms(settings, channel_item)
        enabled = set(mappings[channel_item.channel])
        for term in channel_item.terms:
            term.enabled = (term.source_uid, term.source_channel) in enabled
        channel_item.usage = usages[channel_item.channel]
        channel_item.blend_mode = 'ADD'

    assert settings.sources_expanded
    r_channel = next(item for item in settings.channels if item.channel == 'R')
    r_extra = next(term for term in r_channel.terms if term.source_uid == settings.sources[0].uid and term.source_channel == 'B')
    r_extra.enabled = True
    assert ADDON._term_summary(settings, r_channel) == "Test_Normal(R)(B)"
    r_extra.enabled = False
    original_r_terms = {(term.source_uid, term.source_channel) for term in r_channel.terms if term.enabled}
    assert bpy.ops.ftm.edit_channel(target_channel='R') == {'FINISHED'}
    assert bpy.ops.ftm.reset_channel() == {'FINISHED'}
    assert not any(term.enabled for term in r_channel.terms)
    assert bpy.ops.ftm.cancel_channel() == {'FINISHED'}
    assert {(term.source_uid, term.source_channel) for term in r_channel.terms if term.enabled} == original_r_terms

    assert settings.output_format == 'TARGA'
    settings.output_format = 'PNG'
    assert settings.alpha_content_active

    b_channel = next(item for item in settings.channels if item.channel == 'B')
    b_channel.usage = 'ROUGHNESS'
    settings.sources[1].source_type = 'NORMAL'
    assert b_channel.usage == 'NORMAL_Z'
    settings.sources[1].source_type = 'PACKED'
    for channel_item in settings.channels:
        channel_item.usage = usages[channel_item.channel]

    assert settings.output_name.endswith("RG_Nor_B_Met_A_Rou")
    settings.output_size = '256'
    settings.output_color_type = 'DATA'
    settings.output_name = 'Character_Body_RG_Nor_B_Met_A_Rou'
    assert bpy.ops.ftm.merge_texture() == {'FINISHED'}
    assert settings.operation_status == "貼圖合併成功"
    image = bpy.data.images[settings.generated_image_name]
    assert image.size[:] == (256, 256)
    assert image.source == 'GENERATED'
    assert image.name.startswith("Character_Body_RG_Nor_B_Met_A_Rou")
    pixel = list(image.pixels[:4])
    assert abs(pixel[0] - 0.2) < 0.01
    assert abs(pixel[1] - 0.4) < 0.01
    assert abs(pixel[2] - 0.7) < 0.01
    assert abs(pixel[3] - 0.9) < 0.01

    assert bpy.ops.ftm.connect_material() == {'FINISHED'}
    assert not ADDON.FTM_OT_connect_material.poll(bpy.context)
    material = bpy.data.materials[settings.generated_material_name]
    assert any(node.type == 'TEX_IMAGE' and node.image == image for node in material.node_tree.nodes)
    assert any(node.type == 'NORMAL_MAP' for node in material.node_tree.nodes)

    obj = bpy.context.object
    original_material = bpy.data.materials.new("Original_Material")
    obj.data.materials.clear()
    obj.data.materials.append(original_material)
    settings.source_material_name = original_material.name
    assert bpy.ops.ftm.apply_material() == {'FINISHED'}
    assert not ADDON.FTM_OT_apply_material.poll(bpy.context)
    assert obj.data.materials[0] == material
    assert original_material not in [slot.material for slot in obj.material_slots]

    output_path = os.path.join(tempfile.mkdtemp(prefix="ftm_export_"), "packed.png")
    assert bpy.ops.ftm.export_texture('EXEC_DEFAULT', filepath=output_path) == {'FINISHED'}
    assert os.path.isfile(output_path)
    assert settings.last_export_path == output_path
    assert settings.operation_status == "貼圖輸出成功"
    assert ADDON.FTM_OT_open_export_location.poll(bpy.context)

    model_image_a = bpy.data.images.new("Model_A_Normal", width=2, height=2)
    model_material_a = bpy.data.materials.new("Model_A_Material")
    model_material_a.use_nodes = True
    node_a = model_material_a.node_tree.nodes.new('ShaderNodeTexImage')
    node_a.image = model_image_a
    obj.material_slots[0].material = model_material_a
    assert bpy.ops.ftm.scan_material() == {'FINISHED'}
    assert any(source.image == model_image_a and source.from_material for source in settings.sources)
    assert normal in [source.image for source in settings.sources]
    assert packed in [source.image for source in settings.sources]

    model_image_b = bpy.data.images.new("Model_B_Normal", width=2, height=2)
    model_material_b = bpy.data.materials.new("Model_B_Material")
    model_material_b.use_nodes = True
    node_b = model_material_b.node_tree.nodes.new('ShaderNodeTexImage')
    node_b.image = model_image_b
    obj.material_slots[0].material = model_material_b
    assert bpy.ops.ftm.scan_material() == {'FINISHED'}
    source_images = [source.image for source in settings.sources]
    assert model_image_a not in source_images
    assert model_image_b in source_images
    assert normal in source_images and packed in source_images

    assert bpy.ops.ftm.clear_sources() == {'FINISHED'}
    assert len(settings.sources) == 1
    assert all(source.image is None for source in settings.sources)
    assert bpy.ops.ftm.remove_source(index=0) == {'FINISHED'}
    assert len(settings.sources) == 1

    image_name = image.name
    material_name = material.name
    assert bpy.ops.ftm.reset_all() == {'FINISHED'}
    assert bpy.data.images.get(image_name) is not None
    assert bpy.data.materials.get(material_name) is not None
    assert len(settings.sources) == 1
    assert len(settings.channels) == 4
    assert settings.last_export_path == ""

    print("BLANDER_TEXTURE_MARGE_HEADLESS_OK")
finally:
    ADDON.unregister()
