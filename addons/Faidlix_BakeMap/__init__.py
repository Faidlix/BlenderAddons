bl_info = {
    "name": "Faidlix_BakeMap",
    "author": "Faidlix",
    "version": (2, 3, 10),
    "blender": (5, 2, 0),
    "location": "3D Viewport > Sidebar > Faidlix",
    "description": "Bake maps from a ReferenceObject to a TargetObject",
    "doc_url": "https://github.com/Faidlix/BlenderAddons",
    "category": "Material",
}

import hashlib
import json
import math
import os
import signal
import subprocess
import tempfile
import time
import uuid
from array import array

import bmesh
import bpy
from mathutils.bvhtree import BVHTree
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import Operator, Panel, PropertyGroup
from bpy.app.handlers import persistent
from bpy_extras.io_utils import ImportHelper
from bpy_extras import view3d_utils


ADDON_TAG = "Faidlix_BakeMap"
ADDON_VERSION = (2, 3, 10)
PACKAGE_ID = "faidlix_bakemap"
GITHUB_REPOSITORY_URL = (
    "https://raw.githubusercontent.com/"
    "Faidlix/BlenderAddons/main/repository/index.json"
)
IMPORT_COLLECTION = "Faidlix_Imports"
BACKGROUND_ROOT = os.path.join(tempfile.gettempdir(), "Faidlix_BakeMap")
_BACKGROUND_PROCESSES = {}
BAKE_PASSES = (
    ('Diffuse', 'DIFFUSE', 'bake_diffuse'),
    ('Normal', 'NORMAL', 'bake_normal'),
    ('Emit', 'EMIT', 'bake_emit'),
    ('Combined', 'COMBINED', 'bake_combined'),
    ('Metallic', 'FAIDLIX_METALLIC', 'bake_metallic'),
    ('Roughness', 'FAIDLIX_ROUGHNESS', 'bake_roughness'),
)
SIZE_ITEMS = [
    ('256', "256", "256 x 256"),
    ('512', "512", "512 x 512"),
    ('1024', "1024", "1024 x 1024"),
    ('2048', "2048", "2048 x 2048"),
    ('4096', "4096", "4096 x 4096"),
    ('CUSTOM', "Custom", "Set width and height manually"),
]
SOURCE_SCOPE_ITEMS = [
    ('AUTOMATIC', "Automatic", "Use the target surface to determine the projected area"),
    ('MATERIAL', "Material Slot", "Use only faces assigned to one source material"),
    ('VERTEX_GROUP', "Vertex Group", "Use only faces inside one source vertex group"),
]
ROUGHNESS_OUTPUT_ITEMS = [
    ('SEPARATE', "Separate Map", "Create a standalone Roughness texture"),
    ('METALLIC_ALPHA', "Metallic Alpha", "Pack Roughness into the Metallic texture alpha channel"),
]
SMART_UV_SETTINGS = {
    "angle_limit": math.radians(30.0),
    "margin_method": 'SCALED',
    "rotate_method": 'AXIS_ALIGNED',
    "island_margin": 0.003,
    "area_weight": 0.030,
    "correct_aspect": True,
    "scale_to_bounds": False,
}
LIGHTMAP_UV_SETTINGS = {
    "PREF_CONTEXT": 'ALL_FACES',
    "PREF_PACK_IN_ONE": True,
    "PREF_NEW_UVLAYER": False,
    "PREF_BOX_DIV": 20,
    "PREF_MARGIN_DIV": 0.22,
}
PACK_UV_SETTINGS = {
    "rotate": True,
    "scale": True,
    "margin_method": 'SCALED',
    "margin": 0.002,
}


def _is_mesh(_self, obj):
    return obj is not None and obj.type == 'MESH'


def _mesh_items(_self, _context):
    items = []
    for index, obj in enumerate(sorted(bpy.context.scene.objects, key=lambda item: item.name.lower())):
        if obj.type == 'MESH':
            items.append((obj.name, obj.name, "", 'MESH_DATA', index))
    return items or [('__NONE__', "No mesh objects", "", 'ERROR', 0)]


def _get_settings(context):
    return context.scene.faidlix_bakemap


def _get_target_uv(settings):
    target = settings.target_object
    if not target or target.type != 'MESH' or not target.data.uv_layers:
        return None
    if settings.target_uv_name and settings.target_uv_name in target.data.uv_layers:
        return target.data.uv_layers[settings.target_uv_name]
    return target.data.uv_layers.active


def _uv_items(self, _context):
    target = self.target_object
    if not target or target.type != 'MESH' or not target.data.uv_layers:
        return [('__NONE__', "No UV Map", "Create a UV map before baking")]
    return [(layer.name, layer.name, "Use this UV map for baking") for layer in target.data.uv_layers]


def _update_uv_selection(self, _context):
    target = self.target_object
    if not target or target.type != 'MESH' or self.target_uv_name == '__NONE__':
        return
    layer = target.data.uv_layers.get(self.target_uv_name)
    if layer:
        target.data.uv_layers.active = layer
        layer.active_render = True


def _update_target_object(self, _context):
    target = self.target_object
    self.texture_name = target.name if target else ""
    if target and target.type == 'MESH' and target.data.uv_layers:
        active = target.data.uv_layers.active
        if active:
            self.target_uv_name = active.name


def _uv_status(settings):
    target = settings.target_object
    if target is None:
        return ('ERROR', "Select TargetObject")
    if target.type != 'MESH':
        return ('ERROR', "TargetObject must be a Mesh")
    layer = _get_target_uv(settings)
    if layer is None:
        return ('ERROR', "No UV Map")
    if len(layer.data) == 0:
        return ('ERROR', f"{layer.name}: empty UV data")
    outside = any(
        loop.uv.x < 0.0 or loop.uv.x > 1.0 or loop.uv.y < 0.0 or loop.uv.y > 1.0
        for loop in layer.data
    )
    if outside:
        return ('INFO', f"{layer.name}: usable, some UVs are outside 0-1")
    return ('CHECKMARK', f"{layer.name}: UV Map ready")


def _remember_context(context):
    return {
        'active': context.view_layer.objects.active,
        'selected': list(context.selected_objects),
        'mode': context.object.mode if context.object else 'OBJECT',
    }


def _restore_context(context, state):
    try:
        if context.object and context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='DESELECT')
        for obj in state['selected']:
            if obj.name in bpy.data.objects:
                obj.select_set(True)
        if state['active'] and state['active'].name in bpy.data.objects:
            context.view_layer.objects.active = state['active']
        active = context.view_layer.objects.active
        if active and state['mode'] != 'OBJECT':
            bpy.ops.object.mode_set(mode=state['mode'])
    except Exception:
        pass


def _remember_visibility(context, objects):
    view_layer = context.view_layer
    return {
        'view_layer': view_layer,
        'objects': [
            {
                'object': obj,
                'hide_viewport': obj.hide_viewport,
                'hide_render': obj.hide_render,
                'hidden': obj.hide_get(view_layer=view_layer),
            }
            for obj in objects
        ],
    }


def _show_for_bake(context, objects):
    for obj in objects:
        obj.hide_viewport = False
        obj.hide_render = False
        obj.hide_set(False, view_layer=context.view_layer)


def _remember_local_view(context):
    space = context.space_data if context.area and context.area.type == 'VIEW_3D' else None
    return {'space': space, 'objects': {}} if space and space.local_view else None


def _show_in_local_view(context, objects, state):
    if state is None:
        return
    space = state['space']
    for obj in objects:
        pointer = obj.as_pointer()
        if pointer not in state['objects']:
            state['objects'][pointer] = (obj, obj.local_view_get(space))
        obj.local_view_set(space, True)
    context.view_layer.update()


def _restore_local_view(state):
    if state is None:
        return
    space = state['space']
    for obj, was_visible in state['objects'].values():
        if obj.name in bpy.data.objects:
            obj.local_view_set(space, was_visible)


def _restore_visibility(state):
    view_layer = state['view_layer']
    for item in state['objects']:
        obj = item['object']
        if obj.name not in bpy.data.objects:
            continue
        # Restore the per-view-layer eye state while the global viewport switch
        # is temporarily enabled, then restore the global switches.
        obj.hide_viewport = False
        obj.hide_set(item['hidden'], view_layer=view_layer)
        obj.hide_viewport = item['hide_viewport']
        obj.hide_render = item['hide_render']


def _activate_target(context, target, edit=False):
    if context.object and context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='DESELECT')
    target.hide_set(False)
    target.select_set(True)
    context.view_layer.objects.active = target
    if edit:
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')


def _find_bake_material(target):
    if not target or target.type != 'MESH':
        return None
    return next(
        (
            slot.material
            for slot in target.material_slots
            if slot.material and slot.material.get('faidlix_bake_material')
        ),
        None,
    )


def _disconnect_bake_inputs(material):
    material.use_nodes = True
    principled = _principled_node(material)
    for input_name in ('Base Color', 'Normal', 'Metallic', 'Roughness', 'Emission Color'):
        socket = principled.inputs.get(input_name)
        if socket:
            for link in list(socket.links):
                material.node_tree.links.remove(link)


def _bake_material_name(target, source=None, slot_index=None):
    parts = [target.name]
    if slot_index is not None:
        parts.append(f"Slot{slot_index}")
    if source:
        parts.append(source.name)
    parts.append("Bake")
    return "_".join(parts)


def _bake_image_name(target, base_name, pass_name, slot_index=None):
    parts = [target.name]
    if slot_index is not None:
        parts.append(f"Slot{slot_index}")
    if base_name and base_name.casefold() != target.name.casefold():
        parts.append(base_name)
    parts.append(pass_name)
    return "_".join(parts)


def _claim_datablock_name(collection, datablock, desired_name, tag_property):
    conflict = collection.get(desired_name)
    if conflict and conflict != datablock and conflict.get(tag_property):
        if conflict.users == 0:
            collection.remove(conflict)
        else:
            archive_base = f"{desired_name}_Previous"
            archive_name = archive_base
            index = 1
            existing_archive = collection.get(archive_name)
            while existing_archive is not None and existing_archive != conflict:
                archive_name = f"{archive_base}.{index:03d}"
                index += 1
                existing_archive = collection.get(archive_name)
            conflict.name = archive_name
            conflict['faidlix_desired_name'] = archive_name
    datablock.name = desired_name
    datablock[tag_property] = True
    datablock['faidlix_desired_name'] = desired_name
    return datablock.name


def _create_bake_material(reference, target, source_material=None, workflow='PARTIAL'):
    source = source_material or reference.active_material or next(
        (slot.material for slot in reference.material_slots if slot.material),
        None,
    )
    desired_name = _bake_material_name(target, source)
    if source:
        material = source.copy()
        _claim_datablock_name(
            bpy.data.materials,
            material,
            desired_name,
            'faidlix_bake_material',
        )
        material['faidlix_source_material'] = source.name
    else:
        material = bpy.data.materials.new(name=desired_name)
        material.use_nodes = True
    material['faidlix_bake_material'] = True
    material['faidlix_desired_name'] = desired_name
    material['faidlix_workflow'] = workflow
    material['faidlix_reference_object'] = reference.name
    material['faidlix_target_object'] = target.name
    _disconnect_bake_inputs(material)
    if target.data.users > 1:
        target.data = target.data.copy()
    target.data.materials.clear()
    target.data.materials.append(material)
    for polygon in target.data.polygons:
        polygon.material_index = 0
    return material


def _existing_bake_image(material, pass_name):
    if not material or not material.use_nodes:
        return None
    tag = f"{ADDON_TAG}:{pass_name}"
    node = next(
        (node for node in material.node_tree.nodes if node.get('faidlix_tag') == tag),
        None,
    )
    return node.image if node and node.type == 'TEX_IMAGE' else None


def _image_node(material, image, pass_name):
    material.use_nodes = True
    nodes = material.node_tree.nodes
    tag = f"{ADDON_TAG}:{pass_name}"
    node = next((item for item in nodes if item.get('faidlix_tag') == tag), None)
    if node is None:
        node = nodes.new('ShaderNodeTexImage')
        node['faidlix_tag'] = tag
    node.name = f"Faidlix {pass_name}"
    node.label = f"Faidlix {pass_name}"
    node.image = image
    node.select = True
    nodes.active = node
    return node


def _principled_node(material):
    material.use_nodes = True
    tree = material.node_tree
    nodes = tree.nodes
    output = next((node for node in nodes if node.type == 'OUTPUT_MATERIAL' and node.is_active_output), None)
    if output is None:
        output = nodes.new('ShaderNodeOutputMaterial')
        output.is_active_output = True

    tagged = next(
        (
            node for node in nodes
            if node.type == 'BSDF_PRINCIPLED'
            and node.get('faidlix_tag') == f"{ADDON_TAG}:Principled"
        ),
        None,
    )
    if tagged is not None:
        surface = output.inputs['Surface']
        if not surface.is_linked or surface.links[0].from_node != tagged:
            for link in list(surface.links):
                tree.links.remove(link)
            tree.links.new(tagged.outputs['BSDF'], surface)
        return tagged

    if output and output.inputs['Surface'].is_linked:
        shader = output.inputs['Surface'].links[0].from_node
        if shader.type == 'BSDF_PRINCIPLED':
            shader['faidlix_tag'] = f"{ADDON_TAG}:Principled"
            return shader
    principled = next((node for node in nodes if node.type == 'BSDF_PRINCIPLED'), None)
    if principled is None:
        principled = nodes.new('ShaderNodeBsdfPrincipled')
    principled['faidlix_tag'] = f"{ADDON_TAG}:Principled"
    for link in list(output.inputs['Surface'].links):
        tree.links.remove(link)
    tree.links.new(principled.outputs['BSDF'], output.inputs['Surface'])
    return principled


def _prepare_scalar_as_diffuse_materials(reference, channel):
    originals = [slot.material for slot in reference.material_slots]
    temporary_by_original = {}
    temporary_materials = []
    default_value = 0.0 if channel == 'Metallic' else 0.5
    for index, original in enumerate(originals):
        if original is None:
            continue
        temporary = temporary_by_original.get(original)
        if temporary is None:
            temporary = original.copy()
            temporary.name = f"__Faidlix_{channel}_{original.name}"
            temporary.use_nodes = True
            tree = temporary.node_tree
            nodes = tree.nodes
            links = tree.links
            principled = next((node for node in nodes if node.type == 'BSDF_PRINCIPLED'), None)
            if principled is None:
                principled = nodes.new('ShaderNodeBsdfPrincipled')
            source_socket = principled.inputs.get(channel) if principled else None
            source_link = source_socket.links[0].from_socket if source_socket and source_socket.is_linked else None
            source_value = float(source_socket.default_value) if source_socket else default_value
            output = next(
                (node for node in nodes if node.type == 'OUTPUT_MATERIAL' and node.is_active_output),
                None,
            )
            if output is None:
                output = nodes.new('ShaderNodeOutputMaterial')
            base_color = principled.inputs['Base Color']
            for link in list(base_color.links):
                links.remove(link)
            if source_link:
                links.new(source_link, base_color)
            else:
                base_color.default_value = (source_value, source_value, source_value, 1.0)
            metallic = principled.inputs['Metallic']
            for link in list(metallic.links):
                links.remove(link)
            metallic.default_value = 0.0
            roughness = principled.inputs['Roughness']
            for link in list(roughness.links):
                links.remove(link)
            roughness.default_value = 1.0
            for link in list(output.inputs['Surface'].links):
                links.remove(link)
            links.new(principled.outputs['BSDF'], output.inputs['Surface'])
            temporary_by_original[original] = temporary
            temporary_materials.append(temporary)
        reference.data.materials[index] = temporary
    return originals, temporary_materials


def _restore_source_materials(reference, originals, temporary_materials):
    for index, material in enumerate(originals):
        if index < len(reference.data.materials):
            reference.data.materials[index] = material
    for material in temporary_materials:
        if material.users == 0:
            bpy.data.materials.remove(material)


def _replace_input_link(tree, output_socket, input_socket):
    for link in list(input_socket.links):
        tree.links.remove(link)
    tree.links.new(output_socket, input_socket)


def _connect_results(materials, images, settings=None):
    for material in materials:
        tree = material.node_tree
        principled = _principled_node(material)
        managed_tags = {f"{ADDON_TAG}:{name}" for name, _bake_type, _property in BAKE_PASSES}
        for node in tree.nodes:
            if node.get('faidlix_tag') in managed_tags:
                for output in node.outputs:
                    for link in list(output.links):
                        tree.links.remove(link)
        for input_name in ('Base Color', 'Normal', 'Metallic', 'Roughness', 'Emission Color'):
            socket = principled.inputs.get(input_name)
            if socket:
                for link in list(socket.links):
                    tree.links.remove(link)

        diffuse_node = _image_node(material, images['Diffuse'], 'Diffuse') if 'Diffuse' in images else None
        combined_node = _image_node(material, images['Combined'], 'Combined') if 'Combined' in images else None
        if diffuse_node and combined_node:
            color_mix = next(
                (node for node in tree.nodes if node.get('faidlix_tag') == f"{ADDON_TAG}:ColorMix"),
                None,
            )
            if color_mix is None:
                color_mix = tree.nodes.new('ShaderNodeMixRGB')
                color_mix['faidlix_tag'] = f"{ADDON_TAG}:ColorMix"
            color_mix.name = "Faidlix Diffuse / Combined"
            color_mix.label = "Diffuse (Visible) / Combined"
            color_mix.blend_type = 'MIX'
            color_mix.inputs['Fac'].default_value = 0.0
            _replace_input_link(tree, diffuse_node.outputs['Color'], color_mix.inputs['Color1'])
            _replace_input_link(tree, combined_node.outputs['Color'], color_mix.inputs['Color2'])
            _replace_input_link(tree, color_mix.outputs['Color'], principled.inputs['Base Color'])
        elif diffuse_node or combined_node:
            color_node = diffuse_node or combined_node
            _replace_input_link(tree, color_node.outputs['Color'], principled.inputs['Base Color'])
        if 'Normal' in images:
            texture = _image_node(material, images['Normal'], 'Normal')
            normal = next((node for node in tree.nodes if node.get('faidlix_tag') == f"{ADDON_TAG}:NormalMap"), None)
            if normal is None:
                normal = tree.nodes.new('ShaderNodeNormalMap')
                normal['faidlix_tag'] = f"{ADDON_TAG}:NormalMap"
            normal.name = "Faidlix Normal Map"
            normal.label = "Faidlix Normal Map"
            _replace_input_link(tree, texture.outputs['Color'], normal.inputs['Color'])
            _replace_input_link(tree, normal.outputs['Normal'], principled.inputs['Normal'])
        if 'Emit' in images:
            emit = _image_node(material, images['Emit'], 'Emit')
            emission = principled.inputs.get('Emission Color')
            if emission:
                _replace_input_link(tree, emit.outputs['Color'], emission)
                strength = principled.inputs.get('Emission Strength')
                if strength:
                    strength.default_value = 1.0
        if 'Metallic' in images:
            metallic = _image_node(material, images['Metallic'], 'Metallic')
            _replace_input_link(tree, metallic.outputs['Color'], principled.inputs['Metallic'])
        if 'Roughness' in images:
            roughness = _image_node(material, images['Roughness'], 'Roughness')
            if settings and settings.roughness_output == 'METALLIC_ALPHA' and 'Metallic' in images:
                _pack_roughness_alpha(images['Metallic'], images['Roughness'])
                images['Roughness']['faidlix_intermediate_map'] = True
                roughness.label = "Roughness Bake Source (packed to Metallic Alpha)"
                roughness.hide = True
                _replace_input_link(tree, metallic.outputs['Alpha'], principled.inputs['Roughness'])
            else:
                if 'faidlix_intermediate_map' in images['Roughness']:
                    del images['Roughness']['faidlix_intermediate_map']
                roughness.hide = False
                roughness.label = "Faidlix Roughness"
                _replace_input_link(tree, roughness.outputs['Color'], principled.inputs['Roughness'])


def _pack_roughness_alpha(metallic_image, roughness_image):
    width, height = map(int, roughness_image.size)
    if tuple(map(int, metallic_image.size)) != (width, height):
        metallic_image.scale(width, height)
    count = width * height
    metallic_pixels = array('f', [0.0]) * (count * 4)
    roughness_pixels = array('f', [0.0]) * (count * 4)
    metallic_image.pixels.foreach_get(metallic_pixels)
    roughness_image.pixels.foreach_get(roughness_pixels)
    for offset in range(0, count * 4, 4):
        metallic_pixels[offset + 3] = roughness_pixels[offset]
    metallic_image.pixels.foreach_set(metallic_pixels)
    metallic_image.update()


def _selected_material_images(material, settings):
    images = {}
    selected = {
        pass_name
        for pass_name, _bake_type, property_name in BAKE_PASSES
        if getattr(settings, property_name)
    }
    if settings.bake_roughness and settings.roughness_output == 'METALLIC_ALPHA':
        selected.add('Metallic')
    for pass_name, _bake_type, property_name in BAKE_PASSES:
        if pass_name not in selected:
            continue
        image = _existing_bake_image(material, pass_name)
        if image is not None:
            images[pass_name] = image
    return images


def _connect_selected_results(materials, settings):
    for material in materials:
        _connect_results([material], _selected_material_images(material, settings), settings)


def _output_size(settings):
    if settings.output_size == 'CUSTOM':
        return settings.custom_width, settings.custom_height
    size = int(settings.output_size)
    return size, size


def _import_collection(scene):
    collection = bpy.data.collections.get(IMPORT_COLLECTION)
    if collection is None:
        collection = bpy.data.collections.new(IMPORT_COLLECTION)
        scene.collection.children.link(collection)
    return collection


def _move_to_collection(obj, collection):
    if obj.name not in collection.objects:
        collection.objects.link(obj)
    for current in list(obj.users_collection):
        if current != collection:
            current.objects.unlink(obj)


class FaidlixReferenceItem(PropertyGroup):
    enabled: BoolProperty(name="Enabled", default=True)
    object: PointerProperty(name="ReferenceObject", type=bpy.types.Object, poll=_is_mesh)
    source_scope: EnumProperty(
        name="Source Scope",
        items=SOURCE_SCOPE_ITEMS,
        default='AUTOMATIC',
    )
    source_material_name: StringProperty(name="Material")
    vertex_group_name: StringProperty(name="Vertex Group")


class FaidlixMapOutputItem(PropertyGroup):
    pass_name: StringProperty(name="Map")
    size: EnumProperty(name="Size", items=SIZE_ITEMS, default='1024')
    width: IntProperty(name="Width", default=1024, min=1, max=16384)
    height: IntProperty(name="Height", default=1024, min=1, max=16384)


class FaidlixMaterialMappingItem(PropertyGroup):
    enabled: BoolProperty(name="Enabled", default=True)
    source_object: PointerProperty(name="Source Object", type=bpy.types.Object, poll=_is_mesh)
    source_material: PointerProperty(name="Source Material", type=bpy.types.Material)
    target_material_index: IntProperty(name="Target Slot", default=0, min=0)
    target_uv_name: StringProperty(name="Target UV")
    texture_name: StringProperty(name="Texture Name", default="BakeMap")
    outputs: CollectionProperty(type=FaidlixMapOutputItem)


class FaidlixBakeMapSettings(PropertyGroup):
    references: CollectionProperty(type=FaidlixReferenceItem)
    active_reference_index: IntProperty(default=0, min=0)
    reference_object: PointerProperty(name="ReferenceObject", type=bpy.types.Object, poll=_is_mesh)
    initial_source_scope: EnumProperty(
        name="Source Scope",
        items=SOURCE_SCOPE_ITEMS,
        default='AUTOMATIC',
    )
    initial_source_material_name: StringProperty(name="Material")
    initial_vertex_group_name: StringProperty(name="Vertex Group")
    target_object: PointerProperty(
        name="TargetObject",
        type=bpy.types.Object,
        poll=_is_mesh,
        update=_update_target_object,
    )
    workflow: EnumProperty(
        name="Workflow",
        items=[
            ('PARTIAL', "Partial Bake", "Bake selected source surfaces to one target material"),
            ('MULTI', "Multi Material", "Keep separate target material slots and images"),
            ('ATLAS', "Single Atlas", "Combine all sources into one target material and UV atlas"),
        ],
        default='PARTIAL',
    )
    material_mappings: CollectionProperty(type=FaidlixMaterialMappingItem)
    active_mapping_index: IntProperty(default=0, min=0)
    target_uv_name: EnumProperty(name="UV Map", items=_uv_items, update=_update_uv_selection)
    new_uv_name: StringProperty(name="New UV Name", default="FaidlixUV")
    texture_name: StringProperty(name="Texture Name", default="")
    output_size: EnumProperty(
        name="Size",
        items=SIZE_ITEMS,
        default='1024',
    )
    custom_width: IntProperty(name="Width", default=1024, min=1, max=16384)
    custom_height: IntProperty(name="Height", default=1024, min=1, max=16384)
    diffuse_size: EnumProperty(name="Diffuse Size", items=SIZE_ITEMS, default='1024')
    diffuse_width: IntProperty(name="Width", default=1024, min=1, max=16384)
    diffuse_height: IntProperty(name="Height", default=1024, min=1, max=16384)
    normal_size: EnumProperty(name="Normal Size", items=SIZE_ITEMS, default='1024')
    normal_width: IntProperty(name="Width", default=1024, min=1, max=16384)
    normal_height: IntProperty(name="Height", default=1024, min=1, max=16384)
    emit_size: EnumProperty(name="Emit Size", items=SIZE_ITEMS, default='1024')
    emit_width: IntProperty(name="Width", default=1024, min=1, max=16384)
    emit_height: IntProperty(name="Height", default=1024, min=1, max=16384)
    combined_size: EnumProperty(name="Combined Size", items=SIZE_ITEMS, default='1024')
    combined_width: IntProperty(name="Width", default=1024, min=1, max=16384)
    combined_height: IntProperty(name="Height", default=1024, min=1, max=16384)
    metallic_size: EnumProperty(name="Metallic Size", items=SIZE_ITEMS, default='1024')
    metallic_width: IntProperty(name="Width", default=1024, min=1, max=16384)
    metallic_height: IntProperty(name="Height", default=1024, min=1, max=16384)
    roughness_size: EnumProperty(name="Roughness Size", items=SIZE_ITEMS, default='1024')
    roughness_width: IntProperty(name="Width", default=1024, min=1, max=16384)
    roughness_height: IntProperty(name="Height", default=1024, min=1, max=16384)
    roughness_output: EnumProperty(
        name="Roughness Output",
        description="Store roughness as its own map or in the Metallic map alpha channel",
        items=ROUGHNESS_OUTPUT_ITEMS,
        default='SEPARATE',
    )
    bake_diffuse: BoolProperty(name="Diffuse", default=True)
    bake_normal: BoolProperty(name="Normal", default=True)
    bake_emit: BoolProperty(name="Emit", default=False)
    bake_combined: BoolProperty(name="Combined", default=False)
    bake_metallic: BoolProperty(name="Metallic", default=False)
    bake_roughness: BoolProperty(name="Roughness", default=False)
    diffuse_color: BoolProperty(name="Color", default=True)
    diffuse_direct: BoolProperty(name="Direct", default=False)
    diffuse_indirect: BoolProperty(name="Indirect", default=False)
    selected_to_active: BoolProperty(name="Selected to Active", default=True)
    cage_extrusion: FloatProperty(name="Extrusion", default=0.01, min=0.0, subtype='DISTANCE', unit='LENGTH')
    max_ray_distance: FloatProperty(name="Max Ray Distance", default=0.0, min=0.0, subtype='DISTANCE', unit='LENGTH')
    margin: IntProperty(name="Margin", default=16, min=0, max=32767, subtype='PIXEL')
    normal_space: EnumProperty(
        name="Normal Space",
        items=[('TANGENT', "Tangent", ""), ('OBJECT', "Object", "")],
        default='TANGENT',
    )
    match_target_normals: BoolProperty(
        name="Match Target Normals to Reference",
        description="Flip Target faces whose normals point opposite the nearest Reference surface",
        default=False,
    )
    background_running: BoolProperty(default=False, options={'HIDDEN'})
    background_job_file: StringProperty(default="", options={'HIDDEN'})
    background_status: StringProperty(default="IDLE", options={'HIDDEN'})
    background_message: StringProperty(default="", options={'HIDDEN'})
    background_current_pass: StringProperty(default="", options={'HIDDEN'})
    background_completed: IntProperty(default=0, min=0, options={'HIDDEN'})
    background_total: IntProperty(default=0, min=0, options={'HIDDEN'})
    background_pid: IntProperty(default=0, min=0, options={'HIDDEN'})
    update_status: StringProperty(default="", options={'HIDDEN'})
    update_status_token: IntProperty(default=0, min=0, options={'HIDDEN'})


def _ensure_reference_row(settings):
    if not settings.references:
        item = settings.references.add()
        item.object = settings.reference_object
        item.source_scope = settings.initial_source_scope
        item.source_material_name = settings.initial_source_material_name
        item.vertex_group_name = settings.initial_vertex_group_name
    elif settings.reference_object and not settings.references[0].object:
        settings.references[0].object = settings.reference_object
    if settings.references and settings.references[0].object:
        settings.reference_object = settings.references[0].object


def _valid_reference_items(settings):
    _ensure_reference_row(settings)
    return [item for item in settings.references if item.enabled and item.object and item.object.type == 'MESH']


def _scope_materials(item):
    obj = item.object
    if not obj:
        return []
    materials = [slot.material for slot in obj.material_slots if slot.material]
    if item.source_scope == 'MATERIAL' and item.source_material_name:
        material = bpy.data.materials.get(item.source_material_name)
        return [material] if material and material in materials else []
    unique = []
    for material in materials:
        if material not in unique:
            unique.append(material)
    return unique or [None]


def _missing_source_images(reference_items):
    """Find missing files used by the active shader of each selected source."""
    missing = []
    checked = set()
    for item in reference_items:
        for material in _scope_materials(item):
            if not material or not material.use_nodes:
                continue
            output = next(
                (node for node in material.node_tree.nodes
                 if node.type == 'OUTPUT_MATERIAL' and node.is_active_output),
                None,
            )
            if output is None:
                continue
            pending = [output]
            visited = set()
            while pending:
                node = pending.pop()
                if node.as_pointer() in visited:
                    continue
                visited.add(node.as_pointer())
                if node.type == 'TEX_IMAGE' and node.image:
                    image = node.image
                    key = (item.object.as_pointer(), image.as_pointer())
                    if key not in checked:
                        checked.add(key)
                        if image.source == 'FILE' and not image.packed_file:
                            path = bpy.path.abspath(image.filepath, library=image.library)
                            if not os.path.isfile(path):
                                missing.append((item.object.name, image.name))
                for socket in node.inputs:
                    pending.extend(link.from_node for link in socket.links)
    return missing


def _report_missing_source_images(operator, reference_items):
    missing = _missing_source_images(reference_items)
    if not missing:
        return False
    names = ', '.join(f"{obj}: {image}" for obj, image in missing[:3])
    if len(missing) > 3:
        names += f" (+{len(missing) - 3} more)"
    operator.report(
        {'ERROR'},
        f"Missing source image(s): {names}. Relink them with File > External Data > Find Missing Files, then bake again",
    )
    return True


def _supports_multi_workflows(settings):
    items = [
        item for item in settings.references
        if item.enabled and item.object and item.object.type == 'MESH'
    ]
    if not settings.references and settings.reference_object:
        if settings.initial_source_scope == 'MATERIAL':
            return False
        materials = {
            slot.material for slot in settings.reference_object.material_slots if slot.material
        }
        return len(materials) > 1
    if len(items) > 1:
        return True
    return bool(items and len(_scope_materials(items[0])) > 1)


def _selected_passes(settings):
    selected = {name for name, _bake_type, prop in BAKE_PASSES if getattr(settings, prop)}
    if settings.bake_roughness and settings.roughness_output == 'METALLIC_ALPHA':
        selected.add('Metallic')
    return [(name, bake_type) for name, bake_type, _prop in BAKE_PASSES if name in selected]


def _settings_map_size(settings, pass_name):
    if settings.bake_roughness and settings.roughness_output == 'METALLIC_ALPHA' and pass_name in {'Metallic', 'Roughness'}:
        prefix = 'roughness'
        value = getattr(settings, f"{prefix}_size")
        if value == 'CUSTOM':
            return getattr(settings, f"{prefix}_width"), getattr(settings, f"{prefix}_height")
        size = int(value)
        return size, size
    prefix = pass_name.lower()
    value = getattr(settings, f"{prefix}_size")
    if value == 'CUSTOM':
        return getattr(settings, f"{prefix}_width"), getattr(settings, f"{prefix}_height")
    size = int(value)
    return size, size


def _ensure_mapping_outputs(mapping, settings=None):
    existing = {item.pass_name: item for item in mapping.outputs}
    for pass_name, _bake_type, _prop in BAKE_PASSES:
        if pass_name in existing:
            continue
        output = mapping.outputs.add()
        output.pass_name = pass_name
        if settings:
            prefix = pass_name.lower()
            output.size = getattr(settings, f"{prefix}_size")
            output.width = getattr(settings, f"{prefix}_width")
            output.height = getattr(settings, f"{prefix}_height")


def _mapping_map_size(mapping, pass_name, settings=None):
    target_pass = pass_name
    if settings and settings.bake_roughness and settings.roughness_output == 'METALLIC_ALPHA' and pass_name in {'Metallic', 'Roughness'}:
        target_pass = 'Roughness'
    output = next((item for item in mapping.outputs if item.pass_name == target_pass), None)
    if output is None:
        return 1024, 1024
    if output.size == 'CUSTOM':
        return output.width, output.height
    size = int(output.size)
    return size, size


def _snapshot_mapping(mapping):
    return {
        'enabled': mapping.enabled,
        'target_material_index': mapping.target_material_index,
        'target_uv_name': mapping.target_uv_name,
        'texture_name': mapping.texture_name,
        'outputs': {
            output.pass_name: (output.size, output.width, output.height)
            for output in mapping.outputs
        },
    }


def _sync_material_mappings(settings):
    target = settings.target_object
    old = {}
    for mapping in settings.material_mappings:
        key = (
            mapping.source_object.name if mapping.source_object else "",
            mapping.source_material.name if mapping.source_material else "",
        )
        old[key] = _snapshot_mapping(mapping)
    settings.material_mappings.clear()
    if not target:
        return
    target_slots = [slot.material for slot in target.material_slots]
    used_groups = set()
    fallback_index = 0
    for reference in _valid_reference_items(settings):
        for material in _scope_materials(reference):
            exact = next((i for i, candidate in enumerate(target_slots) if candidate is material), None)
            named = next(
                (
                    i for i, candidate in enumerate(target_slots)
                    if material and candidate and candidate.name == material.name
                ),
                None,
            )
            target_index = exact if exact is not None else named
            if target_index is None:
                target_index = fallback_index
                fallback_index += 1
            group_key = (material.as_pointer() if material else 0, target_index)
            if group_key in used_groups:
                continue
            used_groups.add(group_key)
            mapping = settings.material_mappings.add()
            mapping.source_object = reference.object
            mapping.source_material = material
            mapping.target_material_index = target_index
            mapping.target_uv_name = settings.target_uv_name if settings.target_uv_name != '__NONE__' else ""
            material_name = material.name if material else reference.object.name
            mapping.texture_name = f"{settings.texture_name}_{material_name}"
            key = (reference.object.name, material.name if material else "")
            saved = old.get(key)
            if saved:
                mapping.enabled = saved['enabled']
                mapping.target_material_index = saved['target_material_index']
                mapping.target_uv_name = saved['target_uv_name']
                mapping.texture_name = saved['texture_name']
            _ensure_mapping_outputs(mapping, settings)
            if saved:
                for output in mapping.outputs:
                    values = saved['outputs'].get(output.pass_name)
                    if values:
                        output.size, output.width, output.height = values


def _make_scoped_source(context, item):
    source = item.object
    if item.source_scope == 'AUTOMATIC':
        return source, None
    keep_faces = None
    if item.source_scope == 'MATERIAL':
        material_index = next(
            (
                index for index, slot in enumerate(source.material_slots)
                if slot.material and slot.material.name == item.source_material_name
            ),
            None,
        )
        if material_index is None:
            raise RuntimeError(f"{source.name}: choose a valid Source Material")
        keep_faces = {poly.index for poly in source.data.polygons if poly.material_index == material_index}
    elif item.source_scope == 'VERTEX_GROUP':
        group = source.vertex_groups.get(item.vertex_group_name)
        if group is None:
            raise RuntimeError(f"{source.name}: choose a valid Vertex Group")
        weighted = {
            vertex.index
            for vertex in source.data.vertices
            if any(link.group == group.index and link.weight > 0.0 for link in vertex.groups)
        }
        keep_faces = {
            poly.index for poly in source.data.polygons
            if all(vertex_index in weighted for vertex_index in poly.vertices)
        }
    duplicate = source.copy()
    duplicate.data = source.data.copy()
    duplicate.name = f"__FaidlixScope_{source.name}"
    context.scene.collection.objects.link(duplicate)
    bm = bmesh.new()
    bm.from_mesh(duplicate.data)
    bm.faces.ensure_lookup_table()
    remove = [face for face in bm.faces if face.index not in keep_faces]
    bmesh.ops.delete(bm, geom=remove, context='FACES')
    bm.to_mesh(duplicate.data)
    bm.free()
    duplicate.hide_viewport = False
    duplicate.hide_render = False
    duplicate.hide_set(False, view_layer=context.view_layer)
    return duplicate, duplicate


def _prepare_sources(context, reference_items):
    sources = []
    temporary = []
    try:
        for item in reference_items:
            source, created = _make_scoped_source(context, item)
            sources.append(source)
            if created:
                temporary.append(created)
    except Exception:
        _remove_temporary_sources(temporary)
        raise
    return sources, temporary


def _remove_temporary_sources(objects):
    for obj in objects:
        mesh = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)


def _make_target_slot_proxy(context, target, material_index, bake_material):
    duplicate = target.copy()
    duplicate.data = target.data.copy()
    duplicate.name = f"__FaidlixTargetSlot_{target.name}_{material_index}"
    context.scene.collection.objects.link(duplicate)
    bm = bmesh.new()
    bm.from_mesh(duplicate.data)
    remove = [face for face in bm.faces if face.material_index != material_index]
    bmesh.ops.delete(bm, geom=remove, context='FACES')
    bm.to_mesh(duplicate.data)
    bm.free()
    duplicate.data.materials.clear()
    duplicate.data.materials.append(bake_material)
    for polygon in duplicate.data.polygons:
        polygon.material_index = 0
    duplicate.hide_viewport = False
    duplicate.hide_render = False
    duplicate.hide_set(False, view_layer=context.view_layer)
    return duplicate


class FAIDLIX_OT_reset_all(Operator):
    bl_idname = "faidlix.reset_all"
    bl_label = "Reset All"
    bl_description = "Reset every Faidlix BakeMap setting to its default without deleting scene objects or materials"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        settings = getattr(context.scene, 'faidlix_bakemap', None)
        return bool(settings and not settings.background_running)

    def execute(self, context):
        settings = _get_settings(context)
        for prop in settings.bl_rna.properties:
            name = prop.identifier
            if name == 'rna_type' or prop.is_readonly:
                continue
            try:
                if prop.type == 'COLLECTION':
                    getattr(settings, name).clear()
                elif prop.type == 'POINTER':
                    setattr(settings, name, None)
                else:
                    settings.property_unset(name)
            except Exception:
                pass
        settings.references.clear()
        settings.material_mappings.clear()
        settings.reference_object = None
        settings.target_object = None
        settings.texture_name = ""
        self.report({'INFO'}, "Faidlix BakeMap settings reset to defaults")
        return {'FINISHED'}


def _repository_url_base(url):
    return str(url).split('?', 1)[0].rstrip('/')


def _fresh_github_repository_url():
    # The Manager identifies the shared repository by this exact URL.
    return GITHUB_REPOSITORY_URL


def _github_update_repo(context=None):
    preferences = (context or bpy.context).preferences
    for index, repo in enumerate(preferences.extensions.repos):
        if _repository_url_base(repo.remote_url) == _repository_url_base(GITHUB_REPOSITORY_URL):
            return index, repo
    return None, None


def _ensure_github_update_repo(context):
    index, repo = _github_update_repo(context)
    if repo is not None:
        repo.enabled = True
        repo.use_sync_on_startup = True
        return index, repo

    result = bpy.ops.preferences.extension_repo_add(
        name="Faidlix Blender Add-ons",
        remote_url=_fresh_github_repository_url(),
        use_sync_on_startup=True,
        type='REMOTE',
    )
    if result != {'FINISHED'}:
        return None, None
    return _github_update_repo(context)


def _version_tuple(value):
    try:
        parts = tuple(int(part) for part in str(value).split('.'))
    except (TypeError, ValueError):
        return ()
    return (parts + (0, 0, 0))[:3]


def _github_remote_version(repo):
    index_path = os.path.join(repo.directory, ".blender_ext", "index.json")
    with open(index_path, 'r', encoding='utf8') as handle:
        repository = json.load(handle)
    versions = [
        _version_tuple(item.get('version'))
        for item in repository.get('data', ())
        if item.get('id') == PACKAGE_ID
    ]
    version = max((item for item in versions if item), default=())
    if not version:
        raise RuntimeError("GitHub repository does not contain Faidlix BakeMap")
    return version


def _tag_view3d_redraw():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def _set_update_status(settings, message, clear_after=3.0):
    settings.update_status_token += 1
    token = settings.update_status_token
    scene_name = settings.id_data.name
    settings.update_status = message
    _tag_view3d_redraw()
    if clear_after is None:
        return

    def clear_status():
        scene = bpy.data.scenes.get(scene_name)
        current = getattr(scene, 'faidlix_bakemap', None) if scene else None
        if current and current.update_status_token == token:
            current.update_status = ""
            _tag_view3d_redraw()
        return None

    bpy.app.timers.register(clear_status, first_interval=clear_after)


def _schedule_online_update_install(repo_index, remote_version):
    remote = '.'.join(map(str, remote_version))

    def start_install():
        settings = _get_settings()
        if settings:
            _set_update_status(settings, "下載更新中…", clear_after=None)
        try:
            result = bpy.ops.extensions.package_install(
                'INVOKE_DEFAULT',
                repo_index=repo_index,
                pkg_id=PACKAGE_ID,
                enable_on_install=True,
            )
        except Exception as exc:
            # Installing this extension may unregister its RNA while this
            # callback is still on the stack. Do not touch bpy properties,
            # operators, or this add-on's settings after package_install.
            print(f"Faidlix BakeMap update failed: {exc}")
            return None
        if result not in ({'RUNNING_MODAL'}, {'FINISHED'}):
            print(f"Faidlix BakeMap update did not start: {result}")
            return None
        print(f"Faidlix BakeMap {remote} update started; restart Blender after it finishes")
        return None

    bpy.app.timers.register(start_install, first_interval=0.2)


class FAIDLIX_OT_online_update(Operator):
    bl_idname = "faidlix.online_update"
    bl_label = "線上更新"
    bl_description = "從 Faidlix/BlenderAddons GitHub main 分支檢查並安裝最新版"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        settings = getattr(context.scene, 'faidlix_bakemap', None)
        return bool(settings and not settings.background_running and not settings.update_status)

    def execute(self, context):
        settings = _get_settings(context)
        if not bpy.app.tempdir or not os.path.isdir(bpy.app.tempdir):
            _set_update_status(settings, "請重啟 Blender")
            self.report({'ERROR'}, "Blender update session is invalid. Restart Blender and try again")
            return {'CANCELLED'}

        if not getattr(bpy.app, 'online_access', False):
            _set_update_status(settings, "需開啟網路權限")
            self.report({'ERROR'}, "Enable Allow Online Access in Preferences > System")
            return {'CANCELLED'}

        _set_update_status(settings, "檢查更新中…", clear_after=None)
        repo_index, repo = _ensure_github_update_repo(context)
        if repo is None:
            _set_update_status(settings, "更新失敗")
            self.report({'ERROR'}, "Could not create the Faidlix BakeMap GitHub repository")
            return {'CANCELLED'}

        try:
            sync_result = bpy.ops.extensions.repo_sync(repo_index=repo_index)
            if sync_result != {'FINISHED'}:
                raise RuntimeError("GitHub repository sync did not finish")
            remote_version = _github_remote_version(repo)
        except Exception as exc:
            _set_update_status(settings, "更新失敗")
            self.report({'ERROR'}, f"Update check failed: {exc}")
            return {'CANCELLED'}

        remote = '.'.join(map(str, remote_version))
        if remote_version <= ADDON_VERSION:
            bpy.ops.wm.save_userpref()
            _set_update_status(settings, "已是最新版")
            self.report({'INFO'}, f"Faidlix BakeMap {'.'.join(map(str, ADDON_VERSION))} is already up to date")
            return {'FINISHED'}

        if bpy.app.background:
            _set_update_status(settings, "背景模式不可更新")
            self.report({'ERROR'}, "Online Update must run from the interactive Blender window")
            return {'CANCELLED'}

        bpy.ops.wm.save_userpref()
        _set_update_status(settings, "準備更新…", clear_after=None)
        _schedule_online_update_install(repo_index, remote_version)
        self.report({'INFO'}, f"Faidlix BakeMap {remote} update scheduled")
        return {'FINISHED'}


class FAIDLIX_OT_reference_add(Operator):
    bl_idname = "faidlix.reference_add"
    bl_label = "Add ReferenceObject"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        settings = _get_settings(context)
        if not settings.references:
            _ensure_reference_row(settings)
        settings.references.add()
        settings.active_reference_index = len(settings.references) - 1
        return {'FINISHED'}


class FAIDLIX_OT_reference_remove(Operator):
    bl_idname = "faidlix.reference_remove"
    bl_label = "Remove ReferenceObject"
    bl_options = {'REGISTER', 'UNDO'}

    index: IntProperty(default=-1)

    def execute(self, context):
        settings = _get_settings(context)
        index = self.index if self.index >= 0 else settings.active_reference_index
        if 0 <= index < len(settings.references):
            settings.references.remove(index)
        _ensure_reference_row(settings)
        settings.active_reference_index = min(settings.active_reference_index, len(settings.references) - 1)
        settings.reference_object = settings.references[0].object
        return {'FINISHED'}


class FAIDLIX_OT_reference_reset(Operator):
    bl_idname = "faidlix.reference_reset"
    bl_label = "Reset ReferenceObjects"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        settings = _get_settings(context)
        settings.references.clear()
        settings.material_mappings.clear()
        settings.reference_object = None
        settings.references.add()
        settings.active_reference_index = 0
        settings.workflow = 'PARTIAL'
        return {'FINISHED'}


class FAIDLIX_OT_set_workflow(Operator):
    bl_idname = "faidlix.set_workflow"
    bl_label = "Set Bake Workflow"

    workflow: EnumProperty(items=[
        ('PARTIAL', "Partial Bake", ""),
        ('MULTI', "Multi Material", ""),
        ('ATLAS', "Single Atlas", ""),
    ])

    def execute(self, context):
        settings = _get_settings(context)
        if self.workflow != 'PARTIAL' and not _supports_multi_workflows(settings):
            settings.workflow = 'PARTIAL'
            self.report({'WARNING'}, "Multi Material and Single Atlas need multiple objects or materials")
        else:
            settings.workflow = self.workflow
        return {'FINISHED'}


class FAIDLIX_OT_sync_material_mappings(Operator):
    bl_idname = "faidlix.sync_material_mappings"
    bl_label = "Sync Material Mapping"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        settings = _get_settings(context)
        _sync_material_mappings(settings)
        self.report({'INFO'}, f"Synced {len(settings.material_mappings)} material mapping(s)")
        return {'FINISHED'}


class FAIDLIX_OT_choose_scene_object(Operator):
    bl_idname = "faidlix.choose_scene_object"
    bl_label = "Choose Scene Mesh"
    bl_property = "object_name"

    role: EnumProperty(items=[('REFERENCE', "Reference", ""), ('TARGET', "Target", "")])
    reference_index: IntProperty(default=0, min=0)
    object_name: EnumProperty(name="Mesh", items=_mesh_items)

    def invoke(self, context, _event):
        context.window_manager.invoke_search_popup(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        if self.object_name == '__NONE__':
            return {'CANCELLED'}
        obj = bpy.data.objects.get(self.object_name)
        _assign_object_selection(_get_settings(context), self.role, self.reference_index, obj)
        return {'FINISHED'}


def _assign_object_selection(settings, role, reference_index, obj):
    if role == 'REFERENCE':
        _ensure_reference_row(settings)
        while len(settings.references) <= reference_index:
            settings.references.add()
        settings.references[reference_index].object = obj
        if reference_index == 0:
            settings.reference_object = obj
    else:
        settings.target_object = obj


class FAIDLIX_OT_pick_viewport_object(Operator):
    bl_idname = "faidlix.pick_viewport_object"
    bl_label = "Pick Mesh from Viewport"
    bl_description = "Pick a mesh from the 3D Viewport or select it in the Outliner"
    bl_options = {'REGISTER', 'UNDO', 'BLOCKING'}

    role: EnumProperty(items=[('REFERENCE', "Reference", ""), ('TARGET', "Target", "")])
    reference_index: IntProperty(default=0, min=0)

    def _finish(self, context):
        context.window.cursor_modal_restore()
        area = getattr(self, '_origin_area', None)
        if area:
            area.header_text_set(None)

    def invoke(self, context, _event):
        if not context.area or context.area.type != 'VIEW_3D':
            self.report({'ERROR'}, "Viewport picker must be started from the 3D Viewport")
            return {'CANCELLED'}
        self._origin_area = context.area
        context.window.cursor_modal_set('EYEDROPPER')
        context.area.header_text_set("Click a mesh in the viewport, or select it in the Outliner; Esc or Right Click to cancel")
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    @staticmethod
    def _area_under_mouse(context, event):
        screen = context.window.screen if context.window else None
        if screen:
            for area in screen.areas:
                if (area.x <= event.mouse_x < area.x + area.width
                        and area.y <= event.mouse_y < area.y + area.height):
                    return area
        return context.area

    @staticmethod
    def _selected_mesh(context):
        view_layer = context.view_layer
        active = view_layer.objects.active
        if active and active.type == 'MESH' and active.select_get():
            return active
        selected = [obj for obj in context.selected_objects if obj.type == 'MESH']
        return selected[0] if len(selected) == 1 else None

    def _assign_picked_object(self, context, obj):
        _assign_object_selection(
            _get_settings(context), self.role, self.reference_index, obj
        )
        self._finish(context)
        return {'FINISHED'}

    def modal(self, context, event):
        if event.type in {'ESC', 'RIGHTMOUSE'}:
            self._finish(context)
            return {'CANCELLED'}
        if event.type != 'LEFTMOUSE':
            return {'RUNNING_MODAL'}

        area = self._area_under_mouse(context, event)
        if area and area.type == 'OUTLINER' and event.value == 'RELEASE':
            obj = self._selected_mesh(context)
            if obj is None:
                self.report({'WARNING'}, "Select one mesh object in the Outliner")
                return {'RUNNING_MODAL'}
            return self._assign_picked_object(context, obj)
        if not area or area.type != 'VIEW_3D' or event.value != 'PRESS':
            return {'RUNNING_MODAL'}

        region = next((item for item in area.regions if item.type == 'WINDOW'), None)
        region_3d = getattr(area.spaces.active, 'region_3d', None)
        if region is None or region_3d is None:
            self._finish(context)
            return {'CANCELLED'}
        x = event.mouse_x - region.x
        y = event.mouse_y - region.y
        if x < 0 or y < 0 or x >= region.width or y >= region.height:
            return {'RUNNING_MODAL'}

        coordinate = (x, y)
        origin = view3d_utils.region_2d_to_origin_3d(region, region_3d, coordinate)
        direction = view3d_utils.region_2d_to_vector_3d(region, region_3d, coordinate)
        hit, _location, _normal, _face, obj, _matrix = context.scene.ray_cast(
            context.evaluated_depsgraph_get(), origin, direction
        )
        if not hit or obj is None:
            self.report({'WARNING'}, "No mesh was found under the cursor")
            return {'RUNNING_MODAL'}
        obj = getattr(obj, 'original', obj)
        if obj.type != 'MESH':
            self.report({'WARNING'}, "Choose a mesh object")
            return {'RUNNING_MODAL'}

        return self._assign_picked_object(context, obj)


class FAIDLIX_OT_import_external(Operator, ImportHelper):
    bl_idname = "faidlix.import_external"
    bl_label = "Import External Mesh"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ""
    filter_glob: StringProperty(default="*.blend;*.fbx;*.obj;*.glb;*.gltf", options={'HIDDEN'})
    role: EnumProperty(items=[('REFERENCE', "Reference", ""), ('TARGET', "Target", "")])
    reference_index: IntProperty(default=0, min=0)

    def execute(self, context):
        before = set(bpy.data.objects)
        extension = os.path.splitext(self.filepath)[1].lower()
        try:
            if extension == '.blend':
                with bpy.data.libraries.load(self.filepath, link=False) as (data_from, data_to):
                    data_to.objects = list(data_from.objects)
                imported = [obj for obj in data_to.objects if obj and obj.type == 'MESH']
                collection = _import_collection(context.scene)
                for obj in imported:
                    if not obj.users_collection:
                        collection.objects.link(obj)
            elif extension == '.fbx':
                bpy.ops.wm.fbx_import(filepath=self.filepath)
                imported = [obj for obj in set(bpy.data.objects) - before if obj.type == 'MESH']
            elif extension == '.obj':
                bpy.ops.wm.obj_import(filepath=self.filepath)
                imported = [obj for obj in set(bpy.data.objects) - before if obj.type == 'MESH']
            elif extension in {'.glb', '.gltf'}:
                bpy.ops.import_scene.gltf(filepath=self.filepath)
                imported = [obj for obj in set(bpy.data.objects) - before if obj.type == 'MESH']
            else:
                self.report({'ERROR'}, "Supported: .blend, .fbx, .obj, .glb, .gltf")
                return {'CANCELLED'}
        except Exception as exc:
            self.report({'ERROR'}, f"Import failed: {exc}")
            return {'CANCELLED'}
        if not imported:
            self.report({'ERROR'}, "No mesh object found in the selected file")
            return {'CANCELLED'}
        collection = _import_collection(context.scene)
        for obj in imported:
            _move_to_collection(obj, collection)
        selected = imported[0]
        settings = _get_settings(context)
        if self.role == 'REFERENCE':
            _ensure_reference_row(settings)
            while len(settings.references) <= self.reference_index:
                settings.references.add()
            settings.references[self.reference_index].object = selected
            if self.reference_index == 0:
                settings.reference_object = selected
        else:
            settings.target_object = selected
        if len(imported) > 1:
            self.report({'INFO'}, f"Imported {len(imported)} meshes; assigned {selected.name}. Use + to choose another")
        return {'FINISHED'}


class FAIDLIX_OT_add_uv(Operator):
    bl_idname = "faidlix.add_uv"
    bl_label = "Add UV Map"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        settings = _get_settings(context)
        target = settings.target_object
        if not target or target.type != 'MESH':
            self.report({'ERROR'}, "Select a mesh TargetObject first")
            return {'CANCELLED'}
        name = settings.new_uv_name.strip()
        if not name:
            self.report({'ERROR'}, "Enter a UV Map name")
            return {'CANCELLED'}
        layer = target.data.uv_layers.get(name)
        if layer is None:
            layer = target.data.uv_layers.new(name=name)
            self.report({'INFO'}, f"Created UV Map: {name}")
        else:
            self.report({'INFO'}, f"UV Map already exists; activated: {name}")
        target.data.uv_layers.active = layer
        layer.active_render = True
        settings.target_uv_name = layer.name
        return {'FINISHED'}


class FAIDLIX_OT_uv_action(Operator):
    bl_idname = "faidlix.uv_action"
    bl_label = "UV Action"
    bl_options = {'REGISTER', 'UNDO'}

    action: EnumProperty(items=[
        ('SMART', "Smart UV Project", ""),
        ('LIGHTMAP', "Lightmap Pack", ""),
        ('PACK', "Pack Islands", ""),
    ])

    def execute(self, context):
        settings = _get_settings(context)
        target = settings.target_object
        if not target or target.type != 'MESH':
            self.report({'ERROR'}, "Select a mesh TargetObject first")
            return {'CANCELLED'}
        if not target.data.uv_layers:
            name = settings.new_uv_name.strip() or "FaidlixUV"
            layer = target.data.uv_layers.new(name=name)
            settings.target_uv_name = layer.name
        state = _remember_context(context)
        try:
            _activate_target(context, target, edit=True)
            if self.action == 'SMART':
                bpy.ops.uv.smart_project(**SMART_UV_SETTINGS)
            elif self.action == 'LIGHTMAP':
                bpy.ops.uv.lightmap_pack(**LIGHTMAP_UV_SETTINGS)
            else:
                bpy.ops.uv.pack_islands(**PACK_UV_SETTINGS)
        except Exception as exc:
            self.report({'ERROR'}, f"UV operation failed: {exc}")
            return {'CANCELLED'}
        finally:
            _restore_context(context, state)
        self.report({'INFO'}, "UV operation completed")
        return {'FINISHED'}


def _unique_objects(objects):
    result = []
    for obj in objects:
        if obj and obj not in result:
            result.append(obj)
    return result


def _source_material_for_reference(item):
    if item.source_scope == 'MATERIAL' and item.source_material_name:
        material = bpy.data.materials.get(item.source_material_name)
        if material:
            return material
    return item.object.active_material or next(
        (slot.material for slot in item.object.material_slots if slot.material),
        None,
    )


def _ensure_multi_bake_materials(settings):
    target = settings.target_object
    if target.data.users > 1:
        target.data = target.data.copy()
    result = []
    for mapping in settings.material_mappings:
        if not mapping.enabled:
            continue
        index = mapping.target_material_index
        existing = None
        if index < len(target.material_slots):
            candidate = target.material_slots[index].material
            if candidate and candidate.get('faidlix_bake_material') and candidate.get('faidlix_workflow') == 'MULTI':
                existing = candidate
        if existing is None:
            source = mapping.source_material
            desired_name = _bake_material_name(target, source, index)
            if source:
                material = source.copy()
                _claim_datablock_name(
                    bpy.data.materials,
                    material,
                    desired_name,
                    'faidlix_bake_material',
                )
                material['faidlix_source_material'] = source.name
            else:
                material = bpy.data.materials.new(desired_name)
                material.use_nodes = True
            material['faidlix_bake_material'] = True
            material['faidlix_desired_name'] = desired_name
            material['faidlix_workflow'] = 'MULTI'
            material['faidlix_target_object'] = target.name
            material['faidlix_reference_object'] = mapping.source_object.name if mapping.source_object else ""
            material['faidlix_target_slot'] = index
            _disconnect_bake_inputs(material)
            if index < len(target.data.materials):
                target.data.materials[index] = material
            else:
                while len(target.data.materials) < index:
                    placeholder = bpy.data.materials.new(f"{target.name}_UnusedSlot{len(target.data.materials)}")
                    target.data.materials.append(placeholder)
                target.data.materials.append(material)
            existing = material
        else:
            desired_name = _bake_material_name(target, mapping.source_material, index)
            _claim_datablock_name(
                bpy.data.materials,
                existing,
                desired_name,
                'faidlix_bake_material',
            )
        _ensure_mapping_outputs(mapping, settings)
        result.append((mapping, existing))
    return result


def _resize_or_create_image(material, pass_name, image_name, width, height):
    image = _existing_bake_image(material, pass_name)
    if image is None:
        image = bpy.data.images.new(image_name, width=width, height=height, alpha=True)
        image.generated_color = (0.0, 0.0, 0.0, 0.0)
        if pass_name in {'Normal', 'Metallic', 'Roughness'}:
            image.colorspace_settings.name = 'Non-Color'
    elif tuple(image.size) != (width, height):
        image.scale(width, height)
    _claim_datablock_name(
        bpy.data.images,
        image,
        image_name,
        'faidlix_bake_image',
    )
    image['faidlix_pass_name'] = pass_name
    return image


def _normalize_bake_image_names(material, target, base_name, slot_index=None):
    if not material or not material.use_nodes:
        return
    valid_passes = {name for name, _bake_type, _property_name in BAKE_PASSES}
    prefix = f"{ADDON_TAG}:"
    for node in material.node_tree.nodes:
        tag = str(node.get('faidlix_tag', ''))
        if node.type != 'TEX_IMAGE' or not node.image or not tag.startswith(prefix):
            continue
        pass_name = tag[len(prefix):]
        if pass_name not in valid_passes:
            continue
        desired_name = _bake_image_name(target, base_name, pass_name, slot_index)
        _claim_datablock_name(
            bpy.data.images,
            node.image,
            desired_name,
            'faidlix_bake_image',
        )
        node.image['faidlix_pass_name'] = pass_name


def _bake_operator_kwargs(settings, uv_name, bake_type, scalar_channel=None):
    actual_bake_type = 'DIFFUSE' if scalar_channel else bake_type
    kwargs = {
        'type': actual_bake_type,
        'use_selected_to_active': settings.selected_to_active,
        'cage_extrusion': settings.cage_extrusion,
        'max_ray_distance': settings.max_ray_distance,
        'margin': settings.margin,
        'target': 'IMAGE_TEXTURES',
        'save_mode': 'INTERNAL',
        'use_clear': True,
        'uv_layer': uv_name,
    }
    if actual_bake_type == 'DIFFUSE':
        contribution = set()
        if scalar_channel or settings.diffuse_color:
            contribution.add('COLOR')
        if not scalar_channel and settings.diffuse_direct:
            contribution.add('DIRECT')
        if not scalar_channel and settings.diffuse_indirect:
            contribution.add('INDIRECT')
        kwargs['pass_filter'] = contribution
    if bake_type == 'NORMAL':
        kwargs['normal_space'] = settings.normal_space
    return kwargs


def _prepare_scalar_sources(sources, channel):
    states = []
    for source in _unique_objects(sources):
        originals, temporary_materials = _prepare_scalar_as_diffuse_materials(source, channel)
        states.append((source, originals, temporary_materials))
    return states


def _restore_scalar_sources(states):
    for source, originals, temporary_materials in states:
        _restore_source_materials(source, originals, temporary_materials)


def _select_for_bake(context, sources, target, uv_layer, local_view_state=None):
    if context.object and context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='DESELECT')
    _show_for_bake(context, [*sources, target])
    _show_in_local_view(context, [*sources, target], local_view_state)
    for source in sources:
        source.select_set(True)
    target.select_set(True)
    context.view_layer.objects.active = target
    missing_selection = [obj.name for obj in [*sources, target] if obj not in context.selected_objects]
    if missing_selection:
        raise RuntimeError(
            f"Bake objects are not selectable in the current View Layer: {', '.join(missing_selection)}"
        )
    target.data.uv_layers.active = uv_layer
    uv_layer.active_render = True


def _align_target_normals(reference_items, target):
    if not target or target.type != 'MESH':
        return 0, 0
    sources = _unique_objects([item.object for item in reference_items if item.object])
    depsgraph = bpy.context.evaluated_depsgraph_get()
    source_records = []
    for source in sources:
        if source.type != 'MESH':
            continue
        bvh = BVHTree.FromObject(source, depsgraph)
        if bvh is None:
            continue
        source_records.append((
            bvh,
            source.matrix_world,
            source.matrix_world.inverted(),
            source.matrix_world.to_3x3().inverted().transposed(),
        ))
    if not source_records:
        raise RuntimeError("ReferenceObject has no usable surface for normal matching")
    if target.data.users > 1:
        target.data = target.data.copy()
    mesh = target.data
    mesh.update()
    target_world = target.matrix_world
    target_normal_matrix = target_world.to_3x3().inverted().transposed()
    flip_indices = []
    matched = 0
    for polygon in mesh.polygons:
        center_world = target_world @ polygon.center
        target_normal_world = (target_normal_matrix @ polygon.normal).normalized()
        closest = None
        for bvh, source_world, source_inverse, source_normal_matrix in source_records:
            nearest = bvh.find_nearest(source_inverse @ center_world)
            if nearest is None:
                continue
            location, source_normal, _index, _distance = nearest
            location_world = source_world @ location
            distance_world = (location_world - center_world).length_squared
            if closest is None or distance_world < closest[0]:
                closest = (
                    distance_world,
                    (source_normal_matrix @ source_normal).normalized(),
                )
        if closest is None:
            continue
        matched += 1
        if target_normal_world.dot(closest[1]) < 0.0:
            flip_indices.append(polygon.index)
    if flip_indices:
        mesh_bmesh = bmesh.new()
        try:
            mesh_bmesh.from_mesh(mesh)
            mesh_bmesh.faces.ensure_lookup_table()
            bmesh.ops.reverse_faces(
                mesh_bmesh,
                faces=[mesh_bmesh.faces[index] for index in flip_indices],
            )
            mesh_bmesh.to_mesh(mesh)
        finally:
            mesh_bmesh.free()
        mesh.update()
    return len(flip_indices), matched


def _triangles_overlap_2d(first, second, epsilon=1e-8):
    for triangle in (first, second):
        for index in range(3):
            start = triangle[index]
            end = triangle[(index + 1) % 3]
            axis = (-(end[1] - start[1]), end[0] - start[0])
            first_projection = [point[0] * axis[0] + point[1] * axis[1] for point in first]
            second_projection = [point[0] * axis[0] + point[1] * axis[1] for point in second]
            if max(first_projection) <= min(second_projection) + epsilon:
                return False
            if max(second_projection) <= min(first_projection) + epsilon:
                return False
    return True


def _uv_has_overlap(target, uv_layer, material_index=None):
    mesh = target.data
    mesh.calc_loop_triangles()
    uv_data = uv_layer.data
    triangles = []
    for triangle in mesh.loop_triangles:
        if material_index is not None and mesh.polygons[triangle.polygon_index].material_index != material_index:
            continue
        points = [tuple(uv_data[loop_index].uv) for loop_index in triangle.loops]
        area = abs(
            (points[1][0] - points[0][0]) * (points[2][1] - points[0][1])
            - (points[1][1] - points[0][1]) * (points[2][0] - points[0][0])
        )
        if area <= 1e-12:
            continue
        bounds = (
            min(point[0] for point in points),
            max(point[0] for point in points),
            min(point[1] for point in points),
            max(point[1] for point in points),
        )
        triangles.append((bounds, points))
    triangles.sort(key=lambda item: item[0][0])
    active = []
    for bounds, points in triangles:
        active = [candidate for candidate in active if candidate[0][1] > bounds[0] + 1e-8]
        for other_bounds, other_points in active:
            if other_bounds[3] <= bounds[2] + 1e-8 or bounds[3] <= other_bounds[2] + 1e-8:
                continue
            if _triangles_overlap_2d(points, other_points):
                return True
        active.append((bounds, points))
    return False


def _write_job(job_file, job):
    os.makedirs(os.path.dirname(job_file), exist_ok=True)
    temporary = f"{job_file}.tmp"
    with open(temporary, 'w', encoding='utf-8') as handle:
        json.dump(job, handle, ensure_ascii=False, indent=2)
    os.replace(temporary, job_file)


def _read_job(job_file):
    try:
        with open(job_file, 'r', encoding='utf-8') as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _hash_update(digest, *values):
    digest.update(repr(values).encode('utf-8', errors='replace'))


def _background_fingerprint(settings):
    digest = hashlib.sha256()
    items = _valid_reference_items(settings)
    objects = _unique_objects([item.object for item in items] + [settings.target_object])
    for obj in sorted(objects, key=lambda item: item.name):
        _hash_update(digest, obj.name, obj.type, tuple(round(value, 9) for row in obj.matrix_world for value in row))
        if obj.type != 'MESH':
            continue
        mesh = obj.data
        _hash_update(digest, mesh.name, len(mesh.vertices), len(mesh.polygons), len(mesh.loops))
        for vertex in mesh.vertices:
            _hash_update(
                digest,
                vertex.index,
                tuple(round(value, 9) for value in vertex.co),
                tuple(sorted((group.group, round(group.weight, 9)) for group in vertex.groups)),
            )
        for polygon in mesh.polygons:
            _hash_update(digest, polygon.index, tuple(polygon.vertices), polygon.material_index)
        for layer in mesh.uv_layers:
            _hash_update(digest, layer.name, layer.active_render, len(layer.data))
            for loop in layer.data:
                _hash_update(digest, round(loop.uv.x, 9), round(loop.uv.y, 9))
        for modifier in obj.modifiers:
            _hash_update(digest, modifier.name, modifier.type, modifier.show_render, modifier.show_viewport)
        for slot_index, slot in enumerate(obj.material_slots):
            material = slot.material
            _hash_update(digest, slot_index, material.name if material else None)
            if not material or not material.use_nodes:
                continue
            tree = material.node_tree
            for node in sorted(tree.nodes, key=lambda item: item.name):
                _hash_update(digest, node.name, node.type, node.mute)
                if node.type == 'TEX_IMAGE' and node.image:
                    image = node.image
                    _hash_update(
                        digest,
                        image.name,
                        image.filepath,
                        tuple(image.size),
                        image.colorspace_settings.name,
                    )
                for socket in node.inputs:
                    if not hasattr(socket, 'default_value'):
                        continue
                    value = socket.default_value
                    try:
                        value = tuple(round(float(item), 9) for item in value)
                    except TypeError:
                        try:
                            value = round(float(value), 9)
                        except (TypeError, ValueError):
                            value = repr(value)
                    _hash_update(digest, socket.name, value)
            for link in sorted(
                tree.links,
                key=lambda item: (
                    item.from_node.name,
                    item.from_socket.name,
                    item.to_node.name,
                    item.to_socket.name,
                ),
            ):
                _hash_update(
                    digest,
                    link.from_node.name,
                    link.from_socket.name,
                    link.to_node.name,
                    link.to_socket.name,
                )
    _hash_update(
        digest,
        settings.workflow,
        settings.target_uv_name,
        settings.roughness_output,
        tuple(_selected_passes(settings)),
        tuple((name, _settings_map_size(settings, name)) for name, _bake_type in _selected_passes(settings)),
        tuple(
            (
                mapping.enabled,
                mapping.target_material_index,
                mapping.target_uv_name,
                tuple((item.pass_name, item.size, item.width, item.height) for item in mapping.outputs),
            )
            for mapping in settings.material_mappings
        ),
        tuple(
            (item.object.name, item.source_scope, item.source_material_name, item.vertex_group_name)
            for item in items
        ),
    )
    return digest.hexdigest()


def _background_lock_objects(context, reference_items, target):
    protected = _unique_objects([item.object for item in reference_items] + [target])
    protected_data = {obj.data for obj in protected if obj.type == 'MESH'}
    protected_materials = {
        slot.material
        for obj in protected
        for slot in obj.material_slots
        if slot.material
    }
    for obj in context.scene.objects:
        if obj.type != 'MESH' or obj in protected:
            continue
        shares_data = obj.data in protected_data
        shares_material = any(slot.material in protected_materials for slot in obj.material_slots if slot.material)
        if shares_data or shares_material:
            protected.append(obj)
    if context.object in protected and context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    records = []
    for obj in protected:
        records.append({'name': obj.name, 'hide_select': bool(obj.hide_select)})
        obj.select_set(False)
        obj.hide_select = True
    if context.view_layer.objects.active in protected:
        context.view_layer.objects.active = None
    return records


def _background_unlock(job):
    for record in job.get('locks', []):
        obj = bpy.data.objects.get(record.get('name', ''))
        if obj:
            obj.hide_select = bool(record.get('hide_select', False))


def _pid_alive(pid):
    if not pid:
        return False
    if os.name == 'nt':
        try:
            import ctypes
            process_query_limited_information = 0x1000
            still_active = 259
            handle = ctypes.windll.kernel32.OpenProcess(
                process_query_limited_information,
                False,
                int(pid),
            )
            if not handle:
                return False
            try:
                exit_code = ctypes.c_ulong()
                if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return False
                return exit_code.value == still_active
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        except (OSError, ValueError):
            return False
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def _set_background_settings(settings, job_file, job):
    settings.background_job_file = job_file
    settings.background_status = job.get('status', 'UNKNOWN')
    settings.background_message = job.get('message', '')
    settings.background_current_pass = job.get('current_pass', '')
    settings.background_completed = int(job.get('completed', 0))
    settings.background_total = int(job.get('total', 0))
    settings.background_pid = int(job.get('pid', 0) or 0)
    settings.background_running = job.get('status') in {'STARTING', 'RUNNING', 'CANCEL_REQUESTED'}


def _apply_background_result(scene, job_file, allow_partial=False):
    job = _read_job(job_file)
    if not job:
        raise RuntimeError("Background job record is missing")
    settings = scene.faidlix_bakemap
    accepted = {'COMPLETE'} | ({'CANCELLED', 'INTERRUPTED'} if allow_partial else set())
    if job.get('status') not in accepted:
        raise RuntimeError(f"Background result is not ready: {job.get('status', 'UNKNOWN')}")
    if not job.get('material_names'):
        raise RuntimeError("No completed background maps are available")
    current_fingerprint = _background_fingerprint(settings)
    if current_fingerprint != job.get('fingerprint'):
        job['status'] = 'STALE'
        job['message'] = "Geometry, UV, transform, source scope, or material changed; result was not applied"
        _write_job(job_file, job)
        _background_unlock(job)
        _set_background_settings(settings, job_file, job)
        raise RuntimeError(job['message'])
    target = bpy.data.objects.get(job.get('target', ''))
    if not target or target.type != 'MESH':
        raise RuntimeError("TargetObject no longer exists")
    bake_file = job.get('bake_file', '')
    if not os.path.isfile(bake_file):
        raise RuntimeError("Background bake snapshot is missing")
    material_names = list(dict.fromkeys(job.get('material_names', [])))
    with bpy.data.libraries.load(bake_file, link=False) as (data_from, data_to):
        missing = [name for name in material_names if name not in data_from.materials]
        if missing:
            raise RuntimeError(f"Baked materials are missing: {missing}")
        data_to.materials = material_names
    loaded = [material for material in data_to.materials if material]
    original_data = target.data
    original_materials = list(target.data.materials)
    old_bake_materials = [
        material for material in original_materials
        if material and material.get('faidlix_bake_material')
    ]
    old_bake_images = {
        node.image
        for material in old_bake_materials if material.use_nodes
        for node in material.node_tree.nodes
        if node.type == 'TEX_IMAGE' and node.image and node.get('faidlix_tag')
    }
    original_indices = [polygon.material_index for polygon in target.data.polygons]
    try:
        if target.data.users > 1:
            target.data = target.data.copy()
        workflow = job.get('workflow', 'PARTIAL')
        if workflow == 'MULTI':
            for material in loaded:
                slot_index = int(material.get('faidlix_target_slot', 0))
                while len(target.data.materials) <= slot_index:
                    target.data.materials.append(None)
                target.data.materials[slot_index] = material
        else:
            material = next(
                (item for item in loaded if item.get('faidlix_background_job') == job.get('job_id')),
                loaded[0],
            )
            target.data.materials.clear()
            target.data.materials.append(material)
            for polygon in target.data.polygons:
                polygon.material_index = 0
        for old_material in old_bake_materials:
            if old_material not in loaded and old_material.users == 0:
                bpy.data.materials.remove(old_material)
        for old_image in old_bake_images:
            if old_image.users == 0:
                bpy.data.images.remove(old_image)
        for material in loaded:
            desired_material_name = material.get('faidlix_desired_name', material.name)
            _claim_datablock_name(
                bpy.data.materials,
                material,
                desired_material_name,
                'faidlix_bake_material',
            )
            if not material.use_nodes:
                continue
            for node in material.node_tree.nodes:
                if node.type != 'TEX_IMAGE' or not node.image or not node.get('faidlix_tag'):
                    continue
                desired_image_name = node.image.get('faidlix_desired_name', node.image.name)
                _claim_datablock_name(
                    bpy.data.images,
                    node.image,
                    desired_image_name,
                    'faidlix_bake_image',
                )
    except Exception:
        if target.data != original_data:
            target.data = original_data
        target.data.materials.clear()
        for material in original_materials:
            target.data.materials.append(material)
        for polygon, material_index in zip(target.data.polygons, original_indices):
            polygon.material_index = material_index
        for material in loaded:
            if material.users == 0:
                bpy.data.materials.remove(material)
        raise
    job['status'] = 'APPLIED'
    job['message'] = f"Applied {job.get('completed', 0)} completed background map(s)"
    job['applied_at'] = time.time()
    _write_job(job_file, job)
    _background_unlock(job)
    _set_background_settings(settings, job_file, job)
    return job


def _background_timer():
    keep_running = False
    for scene in bpy.data.scenes:
        settings = getattr(scene, 'faidlix_bakemap', None)
        if not settings or not settings.background_job_file:
            continue
        job_file = settings.background_job_file
        job = _read_job(job_file)
        if not job:
            continue
        status = job.get('status', 'UNKNOWN')
        process = _BACKGROUND_PROCESSES.get(job.get('job_id'))
        if status in {'STARTING', 'RUNNING', 'CANCEL_REQUESTED'}:
            keep_running = True
            if process and process.poll() is not None and status != 'CANCEL_REQUESTED':
                job['status'] = 'INTERRUPTED'
                job['message'] = f"Background Blender stopped with exit code {process.returncode}"
                _write_job(job_file, job)
                status = 'INTERRUPTED'
            elif not process and not _pid_alive(job.get('pid')):
                job['status'] = 'INTERRUPTED'
                job['message'] = "Background Blender is no longer running"
                _write_job(job_file, job)
                status = 'INTERRUPTED'
        if status == 'COMPLETE':
            try:
                _apply_background_result(scene, job_file)
            except Exception as exc:
                job = _read_job(job_file) or job
                if job.get('status') != 'STALE':
                    job['status'] = 'ERROR'
                    job['message'] = f"Could not apply background result: {exc}"
                    _write_job(job_file, job)
        elif status in {'ERROR', 'CANCELLED', 'INTERRUPTED', 'STALE'}:
            _background_unlock(job)
        job = _read_job(job_file) or job
        _set_background_settings(settings, job_file, job)
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
    return 1.0 if keep_running else None


def _ensure_background_timer():
    if not bpy.app.timers.is_registered(_background_timer):
        bpy.app.timers.register(_background_timer, first_interval=0.5, persistent=True)


def _recover_background_job(scene):
    if not bpy.data.filepath or not os.path.isdir(BACKGROUND_ROOT):
        return
    matches = []
    main_file = os.path.normcase(os.path.abspath(bpy.data.filepath))
    for directory in os.scandir(BACKGROUND_ROOT):
        if not directory.is_dir():
            continue
        job_file = os.path.join(directory.path, 'job.json')
        job = _read_job(job_file)
        if not job:
            continue
        recorded = os.path.normcase(os.path.abspath(job.get('main_file', ''))) if job.get('main_file') else ''
        if recorded == main_file and job.get('status') not in {'APPLIED'}:
            matches.append((os.path.getmtime(job_file), job_file, job))
    if not matches:
        return
    _modified, job_file, job = max(matches, key=lambda item: item[0])
    if job.get('status') in {'STARTING', 'RUNNING', 'CANCEL_REQUESTED'} and not _pid_alive(job.get('pid')):
        job['status'] = 'INTERRUPTED'
        job['message'] = "Recovered after an interrupted background bake"
        _write_job(job_file, job)
        _background_unlock(job)
    _set_background_settings(scene.faidlix_bakemap, job_file, job)
    if job.get('status') in {'STARTING', 'RUNNING', 'CANCEL_REQUESTED', 'COMPLETE'}:
        _ensure_background_timer()


@persistent
def _background_load_post(_unused):
    for scene in bpy.data.scenes:
        if hasattr(scene, 'faidlix_bakemap'):
            _recover_background_job(scene)


class FAIDLIX_OT_bake(Operator):
    bl_idname = "faidlix.bake"
    bl_label = "BAKE"
    bl_description = "Bake selected maps from ReferenceObject to TargetObject"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        settings = getattr(context.scene, 'faidlix_bakemap', None)
        if not settings or not settings.target_object:
            return False
        return bool(settings.reference_object or any(item.object for item in settings.references))

    def execute(self, context):
        settings = _get_settings(context)
        reference_items = _valid_reference_items(settings)
        target = settings.target_object
        if not reference_items or not target or target.type != 'MESH':
            self.report({'ERROR'}, "Add at least one mesh ReferenceObject and a mesh TargetObject")
            return {'CANCELLED'}
        if any(item.object == target for item in reference_items):
            self.report({'ERROR'}, "ReferenceObject and TargetObject must be different")
            return {'CANCELLED'}
        if settings.workflow != 'PARTIAL' and not _supports_multi_workflows(settings):
            settings.workflow = 'PARTIAL'
        uv_layer = _get_target_uv(settings)
        if uv_layer is None:
            self.report({'ERROR'}, "TargetObject needs a UV Map")
            return {'CANCELLED'}
        if _report_missing_source_images(self, reference_items):
            return {'CANCELLED'}
        if settings.match_target_normals:
            try:
                flipped, matched = _align_target_normals(reference_items, target)
                uv_layer = _get_target_uv(settings)
                self.report({'INFO'}, f"Matched Target normals: flipped {flipped} of {matched} face(s)")
            except Exception as exc:
                self.report({'ERROR'}, f"Could not match Target normals: {exc}")
                return {'CANCELLED'}
        passes = _selected_passes(settings)
        if not passes:
            self.report({'ERROR'}, "Select at least one Bake Map")
            return {'CANCELLED'}
        if settings.bake_diffuse and not any((settings.diffuse_color, settings.diffuse_direct, settings.diffuse_indirect)):
            self.report({'ERROR'}, "Diffuse needs at least one Contribution")
            return {'CANCELLED'}
        if settings.workflow == 'ATLAS' and _uv_has_overlap(target, uv_layer):
            self.report({'ERROR'}, "Single Atlas requires a non-overlapping Target UV Map")
            return {'CANCELLED'}
        originals = _unique_objects([item.object for item in reference_items])
        state = _remember_context(context)
        visibility_state = _remember_visibility(context, [*originals, target])
        local_view_state = _remember_local_view(context)
        old_engine = context.scene.render.engine
        temporary_sources = []
        temporary_targets = []
        total_images = 0
        is_rebake = False
        try:
            context.scene.render.engine = 'CYCLES'
            sources, temporary_sources = _prepare_sources(context, reference_items)
            if settings.workflow == 'MULTI':
                if not settings.material_mappings:
                    _sync_material_mappings(settings)
                mapped = _ensure_multi_bake_materials(settings)
                if not mapped:
                    raise RuntimeError("No enabled material mappings")
                mapped_slots = {mapping.target_material_index for mapping, _material in mapped}
                used_slots = {poly.material_index for poly in target.data.polygons}
                missing = sorted(used_slots - mapped_slots)
                if missing:
                    raise RuntimeError(f"Target material slots need mapping: {missing}")
                proxy_records = []
                overlapping_slots = []
                for mapping, material in mapped:
                    uv_name = mapping.target_uv_name or uv_layer.name
                    source_uv = target.data.uv_layers.get(uv_name)
                    if source_uv is None:
                        raise RuntimeError(
                            f"Target slot {mapping.target_material_index}: UV Map '{uv_name}' was not found"
                        )
                    if _uv_has_overlap(target, source_uv, material_index=mapping.target_material_index):
                        overlapping_slots.append(mapping.target_material_index)
                    proxy = _make_target_slot_proxy(
                        context, target, mapping.target_material_index, material
                    )
                    temporary_targets.append(proxy)
                    proxy_uv = proxy.data.uv_layers.get(uv_name)
                    proxy_records.append((mapping, material, proxy, proxy_uv))
                if overlapping_slots:
                    self.report({'WARNING'}, f"UV overlap inside target material slots: {overlapping_slots}")
                is_rebake = any(
                    _existing_bake_image(material, pass_name)
                    for _mapping, material in mapped
                    for pass_name, _bake_type in passes
                )
                images_by_material = {material: {} for _mapping, material in mapped}
                for mapping, material, _proxy, _proxy_uv in proxy_records:
                    base_name = mapping.texture_name.strip() or f"{settings.texture_name}_{material.name}"
                    _normalize_bake_image_names(
                        material,
                        target,
                        base_name,
                        mapping.target_material_index,
                    )
                for pass_name, bake_type in passes:
                    for mapping, material, _proxy, _proxy_uv in proxy_records:
                        width, height = _mapping_map_size(mapping, pass_name, settings)
                        base_name = mapping.texture_name.strip() or f"{settings.texture_name}_{material.name}"
                        image_name = _bake_image_name(
                            target,
                            base_name,
                            pass_name,
                            mapping.target_material_index,
                        )
                        image = _resize_or_create_image(
                            material, pass_name, image_name, width, height
                        )
                        for node in material.node_tree.nodes:
                            node.select = False
                        bake_node = _image_node(material, image, pass_name)
                        for output in bake_node.outputs:
                            for link in list(output.links):
                                material.node_tree.links.remove(link)
                        images_by_material[material][pass_name] = image
                    scalar_channel = (
                        'Metallic' if bake_type == 'FAIDLIX_METALLIC'
                        else 'Roughness' if bake_type == 'FAIDLIX_ROUGHNESS'
                        else None
                    )
                    scalar_states = []
                    try:
                        if scalar_channel:
                            scalar_states = _prepare_scalar_sources(sources, scalar_channel)
                        for _mapping, material, proxy, proxy_uv in proxy_records:
                            _select_for_bake(context, sources, proxy, proxy_uv, local_view_state)
                            bpy.ops.object.bake(
                                **_bake_operator_kwargs(settings, proxy_uv.name, bake_type, scalar_channel)
                            )
                            _connect_selected_results([material], settings)
                    finally:
                        _restore_scalar_sources(scalar_states)
                for material, images in images_by_material.items():
                    total_images += len(images)
            else:
                workflow = settings.workflow
                bake_material = next(
                    (
                        slot.material for slot in target.material_slots
                        if slot.material
                        and slot.material.get('faidlix_bake_material')
                        and slot.material.get('faidlix_workflow', 'PARTIAL') == workflow
                    ),
                    None,
                )
                is_rebake = bake_material is not None
                source_material = _source_material_for_reference(reference_items[0])
                if bake_material is None:
                    bake_material = _create_bake_material(
                        reference_items[0].object,
                        target,
                        source_material=source_material,
                        workflow=workflow,
                    )
                    uv_layer = _get_target_uv(settings)
                else:
                    _claim_datablock_name(
                        bpy.data.materials,
                        bake_material,
                        _bake_material_name(target, source_material),
                        'faidlix_bake_material',
                    )
                images = {}
                base_name = settings.texture_name.strip() or "BakeMap"
                _normalize_bake_image_names(bake_material, target, base_name)
                for pass_name, bake_type in passes:
                    width, height = _settings_map_size(settings, pass_name)
                    image_name = _bake_image_name(target, base_name, pass_name)
                    image = _resize_or_create_image(
                        bake_material, pass_name, image_name, width, height
                    )
                    for node in bake_material.node_tree.nodes:
                        node.select = False
                    bake_node = _image_node(bake_material, image, pass_name)
                    for output in bake_node.outputs:
                        for link in list(output.links):
                            bake_material.node_tree.links.remove(link)
                    scalar_channel = (
                        'Metallic' if bake_type == 'FAIDLIX_METALLIC'
                        else 'Roughness' if bake_type == 'FAIDLIX_ROUGHNESS'
                        else None
                    )
                    scalar_states = []
                    try:
                        if scalar_channel:
                            scalar_states = _prepare_scalar_sources(sources, scalar_channel)
                        _select_for_bake(context, sources, target, uv_layer, local_view_state)
                        bpy.ops.object.bake(**_bake_operator_kwargs(settings, uv_layer.name, bake_type, scalar_channel))
                        images[pass_name] = image
                        _connect_selected_results([bake_material], settings)
                    finally:
                        _restore_scalar_sources(scalar_states)
                total_images = len(images)
        except Exception as exc:
            self.report({'ERROR'}, f"Bake failed: {exc}")
            return {'CANCELLED'}
        finally:
            try:
                context.scene.render.engine = old_engine
            except Exception:
                pass
            _restore_context(context, state)
            _restore_local_view(local_view_state)
            _restore_visibility(visibility_state)
            _remove_temporary_sources(temporary_sources)
            _remove_temporary_sources(temporary_targets)
        action = "Re-baked" if is_rebake else "Created bake material and baked"
        self.report({'INFO'}, f"{action} {total_images} image(s) with {len(reference_items)} source(s)")
        return {'FINISHED'}


class FAIDLIX_OT_background_bake(Operator):
    bl_idname = "faidlix.background_bake"
    bl_label = "Background Bake"
    bl_description = "Bake in a separate hidden Blender process while keeping this window available"

    @classmethod
    def poll(cls, context):
        settings = getattr(context.scene, 'faidlix_bakemap', None)
        return bool(settings and not settings.background_running)

    def execute(self, context):
        settings = _get_settings(context)
        reference_items = _valid_reference_items(settings)
        target = settings.target_object
        if not bpy.data.filepath:
            self.report({'ERROR'}, "Save the .blend file before starting Background Bake")
            return {'CANCELLED'}
        if not reference_items or not target or target.type != 'MESH':
            self.report({'ERROR'}, "Add at least one mesh ReferenceObject and a mesh TargetObject")
            return {'CANCELLED'}
        if any(item.object == target for item in reference_items):
            self.report({'ERROR'}, "ReferenceObject and TargetObject must be different")
            return {'CANCELLED'}
        if _get_target_uv(settings) is None:
            self.report({'ERROR'}, "TargetObject needs a UV Map")
            return {'CANCELLED'}
        if _report_missing_source_images(self, reference_items):
            return {'CANCELLED'}
        if settings.match_target_normals:
            try:
                flipped, matched = _align_target_normals(reference_items, target)
                self.report({'INFO'}, f"Matched Target normals: flipped {flipped} of {matched} face(s)")
            except Exception as exc:
                self.report({'ERROR'}, f"Could not match Target normals: {exc}")
                return {'CANCELLED'}
        passes = _selected_passes(settings)
        if not passes:
            self.report({'ERROR'}, "Select at least one Bake Map")
            return {'CANCELLED'}
        if settings.bake_diffuse and not any((settings.diffuse_color, settings.diffuse_direct, settings.diffuse_indirect)):
            self.report({'ERROR'}, "Diffuse needs at least one Contribution")
            return {'CANCELLED'}
        if settings.workflow == 'ATLAS' and _uv_has_overlap(target, _get_target_uv(settings)):
            self.report({'ERROR'}, "Single Atlas requires a non-overlapping Target UV Map")
            return {'CANCELLED'}
        job_id = uuid.uuid4().hex
        job_dir = os.path.join(BACKGROUND_ROOT, job_id)
        job_file = os.path.join(job_dir, 'job.json')
        bake_file = os.path.join(job_dir, 'background_bake.blend')
        output_dir = os.path.join(job_dir, 'maps')
        os.makedirs(output_dir, exist_ok=True)
        job = {
            'job_id': job_id,
            'status': 'STARTING',
            'message': 'Creating scene snapshot',
            'main_file': bpy.data.filepath,
            'bake_file': bake_file,
            'image_paths': {
                image.name: bpy.path.abspath(image.filepath, library=image.library)
                for image in bpy.data.images
                if image.source == 'FILE' and not image.packed_file and image.filepath
                and os.path.isfile(bpy.path.abspath(image.filepath, library=image.library))
            },
            'output_dir': output_dir,
            'target': target.name,
            'workflow': settings.workflow,
            'fingerprint': _background_fingerprint(settings),
            'passes': [name for name, _bake_type in passes],
            'current_pass': '',
            'completed': 0,
            'total': len(passes),
            'pid': 0,
            'locks': [],
            'material_names': [],
            'results': [],
            'created_at': time.time(),
            'cancel_requested': False,
        }
        try:
            _write_job(job_file, job)
            bpy.ops.wm.save_as_mainfile(filepath=bake_file, copy=True, check_existing=False)
            job['locks'] = _background_lock_objects(context, reference_items, target)
            job['message'] = 'Starting background Blender'
            _write_job(job_file, job)
            worker = os.path.join(os.path.dirname(__file__), 'background_worker.py')
            if not os.path.isfile(worker):
                raise RuntimeError("background_worker.py is missing")
            command = [
                bpy.app.binary_path,
                '--background',
                '--factory-startup',
                bake_file,
                '--python',
                worker,
                '--',
                job_file,
            ]
            creation_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags,
            )
            _BACKGROUND_PROCESSES[job_id] = process
            job['pid'] = process.pid
            job['status'] = 'RUNNING'
            job['message'] = 'Background Blender is preparing the first map'
            _write_job(job_file, job)
            _set_background_settings(settings, job_file, job)
            _ensure_background_timer()
        except Exception as exc:
            job['status'] = 'ERROR'
            job['message'] = f"Could not start Background Bake: {exc}"
            _write_job(job_file, job)
            _background_unlock(job)
            _set_background_settings(settings, job_file, job)
            self.report({'ERROR'}, job['message'])
            return {'CANCELLED'}
        self.report({'INFO'}, f"Background Bake started with {len(passes)} map(s)")
        return {'FINISHED'}


class FAIDLIX_OT_cancel_background_bake(Operator):
    bl_idname = "faidlix.cancel_background_bake"
    bl_label = "Cancel Background Bake"
    bl_description = "Stop the background Blender process and restore object locks"

    @classmethod
    def poll(cls, context):
        settings = getattr(context.scene, 'faidlix_bakemap', None)
        return bool(settings and settings.background_running and settings.background_job_file)

    def execute(self, context):
        settings = _get_settings(context)
        job_file = settings.background_job_file
        job = _read_job(job_file)
        if not job:
            settings.background_running = False
            self.report({'ERROR'}, "Background job record is missing")
            return {'CANCELLED'}
        job['cancel_requested'] = True
        job['status'] = 'CANCEL_REQUESTED'
        job['message'] = 'Stopping background Blender'
        _write_job(job_file, job)
        process = _BACKGROUND_PROCESSES.get(job.get('job_id'))
        try:
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
            elif _pid_alive(job.get('pid')):
                os.kill(int(job['pid']), signal.SIGTERM)
        except OSError:
            pass
        latest = _read_job(job_file) or job
        latest['status'] = 'CANCELLED'
        latest['message'] = (
            f"Cancelled; {latest.get('completed', 0)} completed map(s) remain recoverable"
            if latest.get('completed', 0)
            else "Cancelled before a map was completed"
        )
        latest['cancel_requested'] = True
        _write_job(job_file, latest)
        _background_unlock(latest)
        _set_background_settings(settings, job_file, latest)
        self.report({'INFO'}, latest['message'])
        return {'FINISHED'}


class FAIDLIX_OT_recover_background_bake(Operator):
    bl_idname = "faidlix.recover_background_bake"
    bl_label = "Recover Completed Maps"
    bl_description = "Apply maps completed before a cancellation or unexpected interruption"

    @classmethod
    def poll(cls, context):
        settings = getattr(context.scene, 'faidlix_bakemap', None)
        if not settings or not settings.background_job_file or settings.background_running:
            return False
        job = _read_job(settings.background_job_file)
        return bool(job and job.get('completed', 0) and job.get('status') in {'COMPLETE', 'CANCELLED', 'INTERRUPTED'})

    def execute(self, context):
        settings = _get_settings(context)
        try:
            job = _apply_background_result(context.scene, settings.background_job_file, allow_partial=True)
        except Exception as exc:
            self.report({'ERROR'}, f"Recovery was not applied: {exc}")
            return {'CANCELLED'}
        self.report({'INFO'}, job['message'])
        return {'FINISHED'}


class FAIDLIX_OT_pack_maps(Operator):
    bl_idname = "faidlix.pack_maps"
    bl_label = "Pack"
    bl_description = "Pack all images generated by this TargetObject bake material"

    @classmethod
    def poll(cls, context):
        settings = getattr(context.scene, 'faidlix_bakemap', None)
        return bool(settings and _find_bake_material(settings.target_object))

    def execute(self, context):
        target = _get_settings(context).target_object
        materials = [
            slot.material for slot in target.material_slots
            if slot.material and slot.material.get('faidlix_bake_material')
        ] if target else []
        images = []
        for material in materials:
            if not material.use_nodes:
                continue
            for node in material.node_tree.nodes:
                if (
                    node.type == 'TEX_IMAGE'
                    and node.image
                    and str(node.get('faidlix_tag', '')).startswith(f"{ADDON_TAG}:")
                    and not node.image.get('faidlix_intermediate_map')
                    and node.image not in images
                ):
                    images.append(node.image)
        if not images:
            self.report({'ERROR'}, "No generated Bake Map images found")
            return {'CANCELLED'}
        for image in images:
            image.pack()
        self.report({'INFO'}, f"Packed {len(images)} generated image(s)")
        return {'FINISHED'}


class FAIDLIX_PT_bakemap(Panel):
    bl_label = "Faidlix_BakeMap"
    bl_idname = "FAIDLIX_PT_bakemap"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Faidlix"
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, _context):
        row = self.layout.row(align=True)
        row.alignment = 'RIGHT'
        row.label(text=f"v{'.'.join(map(str, ADDON_VERSION))}")

    @staticmethod
    def _draw_enum_buttons(layout, owner, property_name, items, columns):
        grid = layout.grid_flow(
            row_major=True,
            columns=columns,
            even_columns=True,
            even_rows=True,
            align=True,
        )
        for value, label, _description in items:
            button = grid.operator(
                "wm.context_set_enum",
                text=label,
                depress=getattr(owner, property_name) == value,
            )
            button.data_path = f"scene.{owner.path_from_id()}.{property_name}"
            button.value = value

    @staticmethod
    def _draw_map_size(layout, owner, pass_name, property_prefix=None, label=None):
        prefix = property_prefix or pass_name.lower()
        size_property = f"{prefix}_size"
        layout.label(text=label or pass_name)
        FAIDLIX_PT_bakemap._draw_enum_buttons(layout, owner, size_property, SIZE_ITEMS, 3)
        if getattr(owner, size_property) == 'CUSTOM':
            custom = layout.row(align=True)
            custom.prop(owner, f"{prefix}_width", text="W")
            custom.prop(owner, f"{prefix}_height", text="H")

    @staticmethod
    def _draw_output_item(layout, output, label=None):
        layout.label(text=label or output.pass_name)
        FAIDLIX_PT_bakemap._draw_enum_buttons(layout, output, "size", SIZE_ITEMS, 3)
        if output.size == 'CUSTOM':
            custom = layout.row(align=True)
            custom.prop(output, "width", text="W")
            custom.prop(output, "height", text="H")

    def draw(self, context):
        layout = self.layout
        settings = _get_settings(context)
        supports_multi = _supports_multi_workflows(settings)
        workflow = settings.workflow if supports_multi else 'PARTIAL'

        top_controls = layout.row(align=True)
        top_controls.operator("faidlix.reset_all", text="全部重置", icon='FILE_REFRESH')
        if settings.update_status:
            update_status = top_controls.row(align=True)
            update_status.enabled = False
            update_status.operator(
                "faidlix.online_update",
                text=settings.update_status,
                icon='INFO',
            )
        else:
            top_controls.operator("faidlix.online_update", text="線上更新", icon='URL')
        layout.separator()

        box = layout.box()
        header = box.row(align=True)
        header.label(text="Reference Objects", icon='OUTLINER_OB_MESH')
        header.operator("faidlix.reference_reset", text="Reset ReferenceObjects", icon='LOOP_BACK')
        if not settings.references:
            group = box.box()
            group.label(text="ReferenceObject 1")
            row = group.row(align=True)
            row.prop(settings, "reference_object", text="")
            if settings.reference_object:
                picker = row.operator("faidlix.pick_viewport_object", text="", icon='EYEDROPPER')
                picker.role = 'REFERENCE'
                picker.reference_index = 0
            choose = row.operator("faidlix.choose_scene_object", text="", icon='VIEWZOOM')
            choose.role = 'REFERENCE'
            choose.reference_index = 0
            importer = row.operator("faidlix.import_external", text="", icon='FILE_FOLDER')
            importer.role = 'REFERENCE'
            importer.reference_index = 0
            group.label(text="Scope")
            self._draw_enum_buttons(group, settings, "initial_source_scope", SOURCE_SCOPE_ITEMS, 3)
            if settings.reference_object and settings.initial_source_scope == 'MATERIAL':
                group.prop_search(
                    settings,
                    "initial_source_material_name",
                    settings.reference_object.data,
                    "materials",
                    text="Material",
                )
            elif settings.reference_object and settings.initial_source_scope == 'VERTEX_GROUP':
                group.prop_search(
                    settings,
                    "initial_vertex_group_name",
                    settings.reference_object,
                    "vertex_groups",
                    text="Vertex Group",
                )
        for index, item in enumerate(settings.references):
            group = box.box()
            row = group.row(align=True)
            row.prop(item, "enabled", text="")
            row.label(text=f"ReferenceObject {index + 1}")
            remove = row.operator("faidlix.reference_remove", text="", icon='REMOVE')
            remove.index = index
            row = group.row(align=True)
            row.prop(item, "object", text="")
            if item.object:
                picker = row.operator("faidlix.pick_viewport_object", text="", icon='EYEDROPPER')
                picker.role = 'REFERENCE'
                picker.reference_index = index
            choose = row.operator("faidlix.choose_scene_object", text="", icon='VIEWZOOM')
            choose.role = 'REFERENCE'
            choose.reference_index = index
            importer = row.operator("faidlix.import_external", text="", icon='FILE_FOLDER')
            importer.role = 'REFERENCE'
            importer.reference_index = index
            group.label(text="Scope")
            self._draw_enum_buttons(group, item, "source_scope", SOURCE_SCOPE_ITEMS, 3)
            if item.object and item.source_scope == 'MATERIAL':
                group.prop_search(item, "source_material_name", item.object.data, "materials", text="Material")
            elif item.object and item.source_scope == 'VERTEX_GROUP':
                group.prop_search(item, "vertex_group_name", item.object, "vertex_groups", text="Vertex Group")
        box.operator("faidlix.reference_add", text="Add ReferenceObject + Scope", icon='ADD')

        box = layout.box()
        box.label(text="TargetObject", icon='OBJECT_DATA')
        row = box.row(align=True)
        row.prop(settings, "target_object", text="")
        if settings.target_object:
            picker = row.operator("faidlix.pick_viewport_object", text="", icon='EYEDROPPER')
            picker.role = 'TARGET'
        choose = row.operator("faidlix.choose_scene_object", text="", icon='VIEWZOOM')
        choose.role = 'TARGET'
        importer = row.operator("faidlix.import_external", text="", icon='FILE_FOLDER')
        importer.role = 'TARGET'

        tabs = layout.row(align=True)
        op = tabs.operator("faidlix.set_workflow", text="Partial Bake", depress=workflow == 'PARTIAL')
        op.workflow = 'PARTIAL'
        if supports_multi:
            op = tabs.operator("faidlix.set_workflow", text="Multi Material", depress=workflow == 'MULTI')
            op.workflow = 'MULTI'
            op = tabs.operator("faidlix.set_workflow", text="Single Atlas", depress=workflow == 'ATLAS')
            op.workflow = 'ATLAS'

        info = layout.box()
        if workflow == 'PARTIAL':
            info.label(text="Bake selected source surfaces to a re-UV target.", icon='INFO')
        elif workflow == 'MULTI':
            info.label(text="Keep target material slots and separate images.", icon='INFO')
            info.label(text="UV overlap is allowed between different materials.")
        else:
            info.label(text="Combine multiple objects or materials into one atlas.", icon='INFO')

        if workflow == 'MULTI':
            box = layout.box()
            row = box.row(align=True)
            row.label(text="Material Mapping", icon='MATERIAL')
            row.operator("faidlix.sync_material_mappings", text="Sync", icon='FILE_REFRESH')
            if not settings.material_mappings:
                box.label(text="Press Sync to detect source and target material slots.")
            for mapping in settings.material_mappings:
                group = box.box()
                row = group.row(align=True)
                row.prop(mapping, "enabled", text="")
                source_name = mapping.source_object.name if mapping.source_object else "Missing Object"
                material_name = mapping.source_material.name if mapping.source_material else "No Material"
                row.label(text=f"{source_name} / {material_name}")
                group.prop(mapping, "target_material_index", text="Target Slot")
                if settings.target_object:
                    group.prop_search(mapping, "target_uv_name", settings.target_object.data, "uv_layers", text="Target UV")
                group.prop(mapping, "texture_name", text="Texture Name")
                for pass_name, _bake_type, enabled_prop in BAKE_PASSES:
                    packed_pair = settings.bake_roughness and settings.roughness_output == 'METALLIC_ALPHA'
                    if pass_name == 'Metallic' and packed_pair:
                        continue
                    if getattr(settings, enabled_prop) or (pass_name == 'Metallic' and packed_pair):
                        output = next(
                            (item for item in mapping.outputs if item.pass_name == pass_name),
                            None,
                        )
                        output_label = "Metallic / Roughness" if pass_name == 'Roughness' and packed_pair else None
                        if output:
                            self._draw_output_item(group, output, output_label)
                        else:
                            group.label(text=f"{output_label or pass_name}: press Sync to initialize size")

        box = layout.box()
        box.label(text="Target UV Map", icon='GROUP_UVS')
        icon, message = _uv_status(settings)
        box.label(text=message, icon=icon)
        box.prop(settings, "target_uv_name", text="UV Map")
        row = box.row(align=True)
        row.prop(settings, "new_uv_name", text="New UV")
        row.operator("faidlix.add_uv", text="Add", icon='ADD')
        op = box.operator("faidlix.uv_action", text="Smart UV Project")
        op.action = 'SMART'
        row = box.row(align=True)
        op = row.operator("faidlix.uv_action", text="Lightmap Pack")
        op.action = 'LIGHTMAP'
        op = row.operator("faidlix.uv_action", text="Pack Islands")
        op.action = 'PACK'

        box = layout.box()
        box.label(text="Bake Maps", icon='RENDER_STILL')
        grid = box.grid_flow(columns=2, align=True)
        grid.prop(settings, "bake_diffuse", toggle=True)
        grid.prop(settings, "bake_normal", toggle=True)
        grid.prop(settings, "bake_emit", toggle=True)
        grid.prop(settings, "bake_metallic", toggle=True)
        grid.prop(settings, "bake_roughness", toggle=True)
        if settings.bake_roughness:
            box.label(text="Roughness Output")
            self._draw_enum_buttons(box, settings, "roughness_output", ROUGHNESS_OUTPUT_ITEMS, 2)
            if settings.roughness_output == 'METALLIC_ALPHA' and not settings.bake_metallic:
                box.label(text="Metallic will also be baked into RGB", icon='INFO')
        if workflow != 'MULTI':
            box.separator()
            box.prop(settings, "texture_name", text="Texture Name")
            for pass_name, _bake_type, enabled_prop in BAKE_PASSES:
                packed_pair = settings.bake_roughness and settings.roughness_output == 'METALLIC_ALPHA'
                if pass_name == 'Metallic' and packed_pair:
                    continue
                if getattr(settings, enabled_prop) or (pass_name == 'Metallic' and packed_pair):
                    size_label = "Metallic / Roughness" if pass_name == 'Roughness' and packed_pair else pass_name
                    self._draw_map_size(box, settings, pass_name, label=size_label)
        if settings.bake_diffuse:
            box.separator()
            box.label(text="Diffuse Contributions")
            row = box.row(align=True)
            row.prop(settings, "diffuse_color", toggle=True)
            row.prop(settings, "diffuse_direct", toggle=True)
            row.prop(settings, "diffuse_indirect", toggle=True)

        box = layout.box()
        box.label(text="Projection", icon='MOD_SHRINKWRAP')
        box.prop(settings, "selected_to_active")
        box.prop(settings, "cage_extrusion")
        box.prop(settings, "max_ray_distance")
        box.prop(settings, "margin")
        if settings.bake_normal:
            box.prop(settings, "normal_space")

        normal_match = layout.box()
        normal_match.prop(settings, "match_target_normals")
        if settings.match_target_normals:
            normal_match.label(text="Target face directions update before Bake.", icon='INFO')

        row = layout.row()
        row.scale_y = 1.5
        existing = False
        if settings.target_object:
            existing = any(
                slot.material
                and slot.material.get('faidlix_bake_material')
                and slot.material.get('faidlix_workflow', 'PARTIAL') == workflow
                for slot in settings.target_object.material_slots
            )
        button_text = "Re Bake Map" if existing else "New Bake Material"
        row.operator("faidlix.bake", text=button_text, icon='RENDER_STILL')

        background = layout.box()
        background.label(text="Background Bake", icon='CONSOLE')
        if settings.background_running:
            status = settings.background_current_pass or "Preparing"
            background.label(
                text=f"{status}: {settings.background_completed}/{settings.background_total}",
                icon='TIME',
            )
            if settings.background_message:
                background.label(text=settings.background_message)
            cancel = background.row()
            cancel.scale_y = 1.3
            cancel.operator("faidlix.cancel_background_bake", icon='CANCEL')
        else:
            start = background.row()
            start.scale_y = 1.3
            start.operator("faidlix.background_bake", icon='RENDER_ANIMATION')
            if settings.background_status not in {'', 'IDLE', 'APPLIED'} and settings.background_message:
                icon = 'ERROR' if settings.background_status in {'ERROR', 'INTERRUPTED', 'STALE'} else 'INFO'
                background.label(text=settings.background_message, icon=icon)
            job = _read_job(settings.background_job_file) if settings.background_job_file else None
            if (
                job
                and job.get('completed', 0)
                and job.get('status') in {'COMPLETE', 'CANCELLED', 'INTERRUPTED'}
            ):
                background.operator("faidlix.recover_background_bake", icon='RECOVER_LAST')
        layout.operator("faidlix.pack_maps", text="Pack", icon='PACKAGE')


classes = (
    FaidlixReferenceItem,
    FaidlixMapOutputItem,
    FaidlixMaterialMappingItem,
    FaidlixBakeMapSettings,
    FAIDLIX_OT_reset_all,
    FAIDLIX_OT_online_update,
    FAIDLIX_OT_reference_add,
    FAIDLIX_OT_reference_remove,
    FAIDLIX_OT_reference_reset,
    FAIDLIX_OT_set_workflow,
    FAIDLIX_OT_sync_material_mappings,
    FAIDLIX_OT_choose_scene_object,
    FAIDLIX_OT_pick_viewport_object,
    FAIDLIX_OT_import_external,
    FAIDLIX_OT_add_uv,
    FAIDLIX_OT_uv_action,
    FAIDLIX_OT_bake,
    FAIDLIX_OT_background_bake,
    FAIDLIX_OT_cancel_background_bake,
    FAIDLIX_OT_recover_background_bake,
    FAIDLIX_OT_pack_maps,
    FAIDLIX_PT_bakemap,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.faidlix_bakemap = PointerProperty(type=FaidlixBakeMapSettings)
    if _background_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_background_load_post)
    bpy.app.timers.register(
        lambda: [_recover_background_job(scene) for scene in bpy.data.scenes] and None,
        first_interval=0.5,
    )


def unregister():
    if _background_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_background_load_post)
    if bpy.app.timers.is_registered(_background_timer):
        bpy.app.timers.unregister(_background_timer)
    for scene in bpy.data.scenes:
        settings = getattr(scene, 'faidlix_bakemap', None)
        if settings and settings.background_job_file:
            job = _read_job(settings.background_job_file)
            if job:
                _background_unlock(job)
    del bpy.types.Scene.faidlix_bakemap
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()

