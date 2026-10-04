bl_info = {
    "name": "Faidlix Texture Marge",
    "author": "Faidlix",
    "version": (1, 5, 8),
    "blender": (5, 2, 0),
    "location": "3D Viewport > N-panel > Faidlix",
    "description": "Merge image channels and build a copied material without changing source data",
    "category": "Material",
}

import hashlib
import json
import math
import os
import re
import subprocess
from array import array

import bpy
from bpy.app.handlers import persistent
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import Operator, Panel, PropertyGroup
from bpy_extras.io_utils import ExportHelper, ImportHelper

ADDON_VERSION = (1, 5, 8)
PACKAGE_ID = "blander_texture_marge"
GITHUB_REPOSITORY_URL = (
    "https://raw.githubusercontent.com/"
    "Faidlix/BlenderAddons/main/repository/index.json"
)

try:
    import numpy as np
except ImportError:
    np = None


CHANNELS = ("R", "G", "B", "A")
CHANNEL_INDEX = {name: index for index, name in enumerate(CHANNELS)}

SOURCE_TYPES = [
    ('DIFFUSE', "Diffuse / Base Color", "Color texture"),
    ('NORMAL', "Normal", "Normal map"),
    ('ROUGHNESS', "Roughness", "Roughness data"),
    ('METALLIC', "Metallic", "Metallic data"),
    ('EMISSION', "Emission", "Emission color"),
    ('EMISSION_STRENGTH', "Emission Strength", "Emission strength data"),
    ('AO', "AO", "Ambient occlusion"),
    ('ALPHA', "Alpha", "Transparency data"),
    ('HEIGHT', "Height", "Height or bump data"),
    ('SPECULAR', "Specular", "Specular data"),
    ('PACKED', "Packed", "Source channels have different meanings"),
    ('CUSTOM', "Custom", "Custom data"),
]

USAGE_ITEMS = [
    ('NONE', "None", "No material connection"),
    ('DIFFUSE', "Diffuse / Base Color", "Connect as base color"),
    ('NORMAL_X', "Normal X", "First tangent normal component"),
    ('NORMAL_Y', "Normal Y", "Second tangent normal component"),
    ('NORMAL_Z', "Normal Z", "Third tangent normal component"),
    ('METALLIC', "Metallic", "Connect to Metallic"),
    ('ROUGHNESS', "Roughness", "Connect to Roughness"),
    ('EMISSION', "Emission", "Connect as emission color"),
    ('EMISSION_STRENGTH', "Emission Strength", "Connect as emission strength"),
    ('AO', "AO", "Multiply with base color"),
    ('ALPHA', "Alpha", "Connect to Alpha"),
    ('HEIGHT', "Height", "Connect through a Bump node"),
    ('SPECULAR', "Specular", "Connect to Specular IOR Level"),
    ('CUSTOM', "Custom", "Keep in the image without an automatic connection"),
]

BLEND_ITEMS = [
    ('ADD', "Add", "Add selected source channels and clamp to 0-1"),
    ('AVERAGE', "Average", "Average selected source channels"),
    ('MULTIPLY', "Multiply", "Multiply selected source channels"),
    ('MAX', "Maximum", "Use the largest selected value"),
    ('MIN', "Minimum", "Use the smallest selected value"),
]

SIZE_ITEMS = [
    ('256', "256", "256 x 256"),
    ('512', "512", "512 x 512"),
    ('1024', "1024", "1024 x 1024"),
    ('2048', "2048", "2048 x 2048"),
    ('4096', "4096", "4096 x 4096"),
    ('CUSTOM', "Custom", "Set width and height manually"),
]

FORMAT_ITEMS = [
    ('PNG', "PNG", "Portable Network Graphics"),
    ('TARGA', "TGA", "Targa"),
    ('TIFF', "TIFF", "Tagged Image File Format"),
    ('OPEN_EXR', "OpenEXR", "OpenEXR"),
]

FORMAT_EXTENSIONS = {'PNG': '.png', 'TARGA': '.tga', 'TIFF': '.tif', 'OPEN_EXR': '.exr'}
TYPE_ABBR = {
    'DIFFUSE': 'Dif', 'NORMAL_X': 'Nor', 'NORMAL_Y': 'Nor', 'NORMAL_Z': 'Nor',
    'METALLIC': 'Met', 'ROUGHNESS': 'Rou', 'EMISSION': 'Emi',
    'EMISSION_STRENGTH': 'EmiStr', 'AO': 'AO', 'ALPHA': 'Alp',
    'HEIGHT': 'Hei', 'SPECULAR': 'Spe', 'CUSTOM': 'Cus', 'NONE': 'Cus',
}


def _settings(context=None):
    context = context or bpy.context
    scene = getattr(context, "scene", None)
    return getattr(scene, "ftm_settings", None) if scene else None


def _mark_dirty(_self=None, context=None):
    settings = _settings(context)
    if settings:
        settings.generation_valid = False
        _refresh_alpha_format(settings)
        _refresh_output_name(settings)


def _output_name_updated(_self=None, context=None):
    settings = _settings(context)
    if settings:
        settings.generation_valid = False


def _set_operation_status(settings, message, is_error=False):
    settings.operation_status_token += 1
    token = settings.operation_status_token
    scene_name = settings.id_data.name
    settings.operation_status = message
    settings.operation_status_error = is_error

    def clear_status():
        scene = bpy.data.scenes.get(scene_name)
        current = getattr(scene, "ftm_settings", None) if scene else None
        if current and current.operation_status_token == token:
            current.operation_status = ""
        return None

    bpy.app.timers.register(clear_status, first_interval=3.0)


def _set_update_status(settings, message):
    settings.update_status_token += 1
    token = settings.update_status_token
    scene_name = settings.id_data.name
    settings.update_status = message

    def clear_status():
        scene = bpy.data.scenes.get(scene_name)
        current = getattr(scene, "ftm_settings", None) if scene else None
        if current and current.update_status_token == token:
            current.update_status = ""
        return None

    bpy.app.timers.register(clear_status, first_interval=3.0)


def _new_uid(settings):
    settings.uid_counter += 1
    return f"source_{settings.uid_counter:04d}"


def _detect_source_type(*names):
    text = " ".join(str(value) for value in names if value).lower()
    if "normal" in text or " nor" in text:
        return 'NORMAL'
    if "rough" in text:
        return 'ROUGHNESS'
    if "metal" in text:
        return 'METALLIC'
    if "emission strength" in text or "emit strength" in text:
        return 'EMISSION_STRENGTH'
    if "emission" in text or "emissive" in text or "emit" in text:
        return 'EMISSION'
    if "ambient occlusion" in text or re.search(r"(^|[_.\-\s])ao($|[_.\-\s])", text):
        return 'AO'
    if "alpha" in text or "opacity" in text:
        return 'ALPHA'
    if "height" in text or "bump" in text or "displacement" in text:
        return 'HEIGHT'
    if "specular" in text or "spec" in text:
        return 'SPECULAR'
    if "base color" in text or "diffuse" in text or "albedo" in text:
        return 'DIFFUSE'
    return 'CUSTOM'


def _node_semantic(material, image_node):
    candidates = [image_node.name, image_node.label, image_node.image.name]
    for link in material.node_tree.links:
        if link.from_node != image_node:
            continue
        candidates.extend((link.to_node.name, link.to_node.label, link.to_socket.name))
        if link.to_node.type == 'NORMAL_MAP':
            return 'NORMAL'
        detected = _detect_source_type(*candidates)
        if detected != 'CUSTOM':
            return detected
    return _detect_source_type(*candidates)


def _add_source(settings, image=None, source_type='CUSTOM', node_name="", external=False, from_material=False, uid=""):
    item = settings.sources.add()
    item.uid = uid or _new_uid(settings)
    item.image = image
    item.source_type = source_type
    item.node_name = node_name
    item.external_import = external
    item.from_material = from_material
    return item


def _ensure_channels(settings):
    existing = {item.channel: item for item in settings.channels}
    if len(existing) == 4 and all(channel in existing for channel in CHANNELS):
        return
    settings.channels.clear()
    for channel in CHANNELS:
        item = settings.channels.add()
        item.channel = channel
        item.usage = 'NONE'
        item.blend_mode = 'ADD'


def _ensure_defaults(settings):
    _ensure_channels(settings)
    if not settings.sources:
        _add_source(settings)


def _channel(settings, channel_name):
    return next((item for item in settings.channels if item.channel == channel_name), None)


def _sync_terms(settings, channel_item):
    old = {(term.source_uid, term.source_channel): term.enabled for term in channel_item.terms}
    channel_item.terms.clear()
    for source in settings.sources:
        if not source.image:
            continue
        for source_channel in CHANNELS:
            term = channel_item.terms.add()
            term.source_uid = source.uid
            term.source_channel = source_channel
            term.enabled = old.get((source.uid, source_channel), False)


def _source_by_uid(settings, uid):
    return next((item for item in settings.sources if item.uid == uid), None)


def _enabled_terms(settings, channel_item):
    result = []
    for term in channel_item.terms:
        if not term.enabled:
            continue
        source = _source_by_uid(settings, term.source_uid)
        if source and source.image:
            result.append((source, term.source_channel))
    return result


def _term_summary(settings, channel_item):
    grouped = []
    positions = {}
    for source, source_channel in _enabled_terms(settings, channel_item):
        if source.uid not in positions:
            positions[source.uid] = len(grouped)
            grouped.append([source.image.name, []])
        grouped[positions[source.uid]][1].append(source_channel)
    values = [name + "".join(f"({channel})" for channel in channels) for name, channels in grouped]
    if not values:
        return "選擇內容"
    return " + ".join(values)


def _suggest_usage(source_type, source_channel):
    if source_type == 'NORMAL':
        return {'R': 'NORMAL_X', 'G': 'NORMAL_Y', 'B': 'NORMAL_Z'}.get(source_channel, 'CUSTOM')
    return source_type if source_type in {item[0] for item in USAGE_ITEMS} else 'CUSTOM'


def _refresh_alpha_format(settings):
    alpha_channel = _channel(settings, 'A')
    has_alpha = bool(alpha_channel and _enabled_terms(settings, alpha_channel))
    if has_alpha and not settings.alpha_content_active:
        settings.output_format = 'TARGA'
    settings.alpha_content_active = has_alpha


def _refresh_channel_usage(settings, channel_item):
    terms = _enabled_terms(settings, channel_item)
    channel_item.usage = _suggest_usage(terms[0][0].source_type, terms[0][1]) if terms else 'NONE'


def _source_type_updated(_self, context):
    settings = _settings(context)
    if settings:
        for channel_item in settings.channels:
            terms = _enabled_terms(settings, channel_item)
            if terms and terms[0][0].uid == _self.uid:
                _refresh_channel_usage(settings, channel_item)
    _mark_dirty(context=context)


def _term_updated(_self, context):
    settings = _settings(context)
    if settings:
        for channel_item in settings.channels:
            if any(term.as_pointer() == _self.as_pointer() for term in channel_item.terms):
                _refresh_channel_usage(settings, channel_item)
                break
    _mark_dirty(context=context)


def _output_size(settings):
    if settings.output_size == 'CUSTOM':
        return settings.custom_width, settings.custom_height
    size = int(settings.output_size)
    return size, size


def _semantic_group(usage):
    return 'NORMAL' if usage.startswith('NORMAL_') else usage


def _generated_suffix(settings):
    groups = []
    seen = set()
    for item in settings.channels:
        semantic = _semantic_group(item.usage)
        if semantic in ('NONE',):
            semantic = 'CUSTOM'
        if semantic in seen:
            continue
        channels = "".join(other.channel for other in settings.channels if _semantic_group(other.usage) == semantic)
        if channels:
            groups.append(f"{channels}_{TYPE_ABBR.get(item.usage, TYPE_ABBR.get(semantic, 'Cus'))}")
            seen.add(semantic)
    return "_".join(groups) or "RGBA_Custom"


def _suggested_output_name(settings):
    if settings.source_mode == 'MATERIAL' and settings.source_material_name:
        base = settings.source_material_name
    else:
        first = next((source.image for source in settings.sources if source.image), None)
        base = os.path.splitext(first.name)[0] if first else "Texture"
    base = re.sub(r"[^A-Za-z0-9_\-]+", "_", base).strip("_") or "Texture"
    suffix = _generated_suffix(settings)
    return f"{base}_{suffix}"


def _refresh_output_name(settings, force=False):
    suggested = _suggested_output_name(settings)
    current = settings.output_name.strip()
    previous_auto = settings.output_name_auto
    settings.output_name_auto = suggested
    if force or not current or current == previous_auto:
        settings.output_name = suggested


def _base_output_name(settings):
    name = settings.output_name.strip() or _suggested_output_name(settings)
    return re.sub(r"[^A-Za-z0-9_\-]+", "_", name).strip("_") or "Texture"


def _configuration_signature(settings):
    payload = {
        'mode': settings.source_mode,
        'sources': [(item.uid, item.image.name if item.image else None, item.source_type) for item in settings.sources],
        'channels': [
            (item.channel, item.usage, item.blend_mode,
             [(term.source_uid, term.source_channel) for term in item.terms if term.enabled])
            for item in settings.channels
        ],
        'color': settings.output_color_type,
        'size': _output_size(settings),
        'resample': settings.resample_mode,
        'name': settings.output_name,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode('utf-8')).hexdigest()


def _read_pixels(image):
    width, height = map(int, image.size[:])
    if width <= 0 or height <= 0:
        raise ValueError(f"圖片沒有有效像素：{image.name}")
    if np is not None:
        values = np.empty(width * height * 4, dtype=np.float32)
        image.pixels.foreach_get(values)
        return values.reshape((height, width, 4)), width, height
    values = array('f', [0.0]) * (width * height * 4)
    image.pixels.foreach_get(values)
    return values, width, height


def _resample_channel(image, source_channel, width, height, mode):
    values, source_width, source_height = _read_pixels(image)
    channel_index = CHANNEL_INDEX[source_channel]
    if np is None:
        result = array('f', [0.0]) * (width * height)
        for y in range(height):
            source_y = min(source_height - 1, int(y * source_height / max(1, height)))
            for x in range(width):
                source_x = min(source_width - 1, int(x * source_width / max(1, width)))
                result[y * width + x] = values[(source_y * source_width + source_x) * 4 + channel_index]
        return result

    source = values[:, :, channel_index]
    if (source_width, source_height) == (width, height):
        return source.copy()
    if mode == 'NEAREST':
        xs = np.rint(np.linspace(0, source_width - 1, width)).astype(np.int32)
        ys = np.rint(np.linspace(0, source_height - 1, height)).astype(np.int32)
        return source[ys[:, None], xs[None, :]]

    xs = np.linspace(0, source_width - 1, width, dtype=np.float32)
    ys = np.linspace(0, source_height - 1, height, dtype=np.float32)
    x0 = np.floor(xs).astype(np.int32)
    y0 = np.floor(ys).astype(np.int32)
    x1 = np.minimum(x0 + 1, source_width - 1)
    y1 = np.minimum(y0 + 1, source_height - 1)
    wx = xs - x0
    result = np.empty((height, width), dtype=np.float32)
    chunk_size = 128
    for start in range(0, height, chunk_size):
        end = min(height, start + chunk_size)
        rows0 = source[y0[start:end], :]
        rows1 = source[y1[start:end], :]
        top = rows0[:, x0] * (1.0 - wx) + rows0[:, x1] * wx
        bottom = rows1[:, x0] * (1.0 - wx) + rows1[:, x1] * wx
        wy = (ys[start:end] - y0[start:end])[:, None]
        result[start:end] = top * (1.0 - wy) + bottom * wy
    return result


def _mix_arrays(arrays, mode):
    if len(arrays) == 1:
        return arrays[0]
    if np is None:
        count = len(arrays[0])
        result = array('f', arrays[0])
        for index in range(count):
            values = [source[index] for source in arrays]
            if mode == 'AVERAGE':
                result[index] = sum(values) / len(values)
            elif mode == 'MULTIPLY':
                result[index] = math.prod(values)
            elif mode == 'MAX':
                result[index] = max(values)
            elif mode == 'MIN':
                result[index] = min(values)
            else:
                result[index] = min(1.0, max(0.0, sum(values)))
        return result
    stack = np.stack(arrays, axis=0)
    if mode == 'AVERAGE':
        return stack.mean(axis=0)
    if mode == 'MULTIPLY':
        return stack.prod(axis=0)
    if mode == 'MAX':
        return stack.max(axis=0)
    if mode == 'MIN':
        return stack.min(axis=0)
    return np.clip(stack.sum(axis=0), 0.0, 1.0)


def _build_pixels(settings, width, height):
    if np is not None:
        output = np.zeros((height, width, 4), dtype=np.float32)
        output[:, :, 3] = 1.0
    else:
        output = array('f', [0.0]) * (width * height * 4)
        for index in range(3, len(output), 4):
            output[index] = 1.0
    for channel_item in settings.channels:
        terms = _enabled_terms(settings, channel_item)
        if not terms:
            continue
        arrays = [
            _resample_channel(source.image, source_channel, width, height, settings.resample_mode)
            for source, source_channel in terms
        ]
        mixed = _mix_arrays(arrays, channel_item.blend_mode)
        target_index = CHANNEL_INDEX[channel_item.channel]
        if np is not None:
            output[:, :, target_index] = mixed
        else:
            for pixel_index, value in enumerate(mixed):
                output[pixel_index * 4 + target_index] = value
    return output.reshape(-1) if np is not None else output


def _safe_colorspace(image, name):
    try:
        image.colorspace_settings.name = name
    except TypeError:
        pass


def _socket(node, names):
    for name in names:
        if name in node.inputs:
            return node.inputs[name]
    return None


def _channel_socket(tree, texture_node, separate_node, channel_name):
    if channel_name == 'A':
        return texture_node.outputs['Alpha']
    return separate_node.outputs[{'R': 'Red', 'G': 'Green', 'B': 'Blue'}[channel_name]]


def _combine_rgb(tree, sockets, location):
    node = tree.nodes.new('ShaderNodeCombineColor')
    node.mode = 'RGB'
    node.location = location
    for channel_name, input_name in (('R', 'Red'), ('G', 'Green'), ('B', 'Blue')):
        if channel_name in sockets:
            tree.links.new(sockets[channel_name], node.inputs[input_name])
    return node.outputs['Color']


def _normal_from_channels(tree, sockets, location):
    if all(channel in sockets for channel in ('R', 'G', 'B')):
        color = _combine_rgb(tree, sockets, location)
    elif 'R' in sockets and 'G' in sockets:
        x_decode = tree.nodes.new('ShaderNodeMath'); x_decode.operation = 'MULTIPLY_ADD'; x_decode.inputs[1].default_value = 2.0; x_decode.inputs[2].default_value = -1.0
        y_decode = tree.nodes.new('ShaderNodeMath'); y_decode.operation = 'MULTIPLY_ADD'; y_decode.inputs[1].default_value = 2.0; y_decode.inputs[2].default_value = -1.0
        x_sq = tree.nodes.new('ShaderNodeMath'); x_sq.operation = 'MULTIPLY'
        y_sq = tree.nodes.new('ShaderNodeMath'); y_sq.operation = 'MULTIPLY'
        add = tree.nodes.new('ShaderNodeMath'); add.operation = 'ADD'
        subtract = tree.nodes.new('ShaderNodeMath'); subtract.operation = 'SUBTRACT'; subtract.inputs[0].default_value = 1.0
        maximum = tree.nodes.new('ShaderNodeMath'); maximum.operation = 'MAXIMUM'; maximum.inputs[1].default_value = 0.0
        sqrt = tree.nodes.new('ShaderNodeMath'); sqrt.operation = 'SQRT'
        encode = tree.nodes.new('ShaderNodeMath'); encode.operation = 'MULTIPLY_ADD'; encode.inputs[1].default_value = 0.5; encode.inputs[2].default_value = 0.5
        for index, node in enumerate((x_decode, y_decode, x_sq, y_sq, add, subtract, maximum, sqrt, encode)):
            node.location = (location[0] + (index // 3) * 150, location[1] - (index % 3) * 120)
        tree.links.new(sockets['R'], x_decode.inputs[0]); tree.links.new(sockets['G'], y_decode.inputs[0])
        tree.links.new(x_decode.outputs[0], x_sq.inputs[0]); tree.links.new(x_decode.outputs[0], x_sq.inputs[1])
        tree.links.new(y_decode.outputs[0], y_sq.inputs[0]); tree.links.new(y_decode.outputs[0], y_sq.inputs[1])
        tree.links.new(x_sq.outputs[0], add.inputs[0]); tree.links.new(y_sq.outputs[0], add.inputs[1])
        tree.links.new(add.outputs[0], subtract.inputs[1]); tree.links.new(subtract.outputs[0], maximum.inputs[0])
        tree.links.new(maximum.outputs[0], sqrt.inputs[0]); tree.links.new(sqrt.outputs[0], encode.inputs[0])
        combine_sockets = {'R': sockets['R'], 'G': sockets['G'], 'B': encode.outputs[0]}
        color = _combine_rgb(tree, combine_sockets, (location[0] + 500, location[1]))
    else:
        return None
    normal = tree.nodes.new('ShaderNodeNormalMap')
    normal.location = (location[0] + 700, location[1])
    tree.links.new(color, normal.inputs['Color'])
    return normal.outputs['Normal']


class FTMSource(PropertyGroup):
    uid: StringProperty()
    image: PointerProperty(name="Image", type=bpy.types.Image, update=_mark_dirty)
    source_type: EnumProperty(name="Type", items=SOURCE_TYPES, default='CUSTOM', update=_source_type_updated)
    node_name: StringProperty()
    external_import: BoolProperty(default=False)
    from_material: BoolProperty(default=False)


class FTMTerm(PropertyGroup):
    source_uid: StringProperty()
    source_channel: EnumProperty(name="Channel", items=[(c, c, "") for c in CHANNELS])
    enabled: BoolProperty(name="", default=False, update=_term_updated)


class FTMOutputChannel(PropertyGroup):
    channel: StringProperty()
    terms: CollectionProperty(type=FTMTerm)
    blend_mode: EnumProperty(name="Mix", items=BLEND_ITEMS, default='ADD', update=_mark_dirty)
    usage: EnumProperty(name="Purpose", items=USAGE_ITEMS, default='NONE', update=_mark_dirty)


class FTMSettings(PropertyGroup):
    source_mode: EnumProperty(
        name="Source",
        items=[('MATERIAL', "Material Scan", "Scan the active material"), ('MANUAL', "Manual Images", "Choose Blender or external images")],
        default='MATERIAL', update=_mark_dirty,
    )
    sources: CollectionProperty(type=FTMSource)
    active_source_index: IntProperty(default=0, min=0)
    sources_expanded: BoolProperty(default=True)
    editing_channel: StringProperty()
    edit_snapshot: StringProperty()
    channels: CollectionProperty(type=FTMOutputChannel)
    uid_counter: IntProperty(default=0, min=0)
    source_material_name: StringProperty()
    output_color_type: EnumProperty(
        name="Output Type",
        items=[('COLOR', "Color", "sRGB color image"), ('DATA', "Data", "Non-Color numeric data image")],
        default='DATA', update=_mark_dirty,
    )
    output_size: EnumProperty(name="Size", items=SIZE_ITEMS, default='1024', update=_mark_dirty)
    custom_width: IntProperty(name="Width", default=1024, min=1, max=16384, update=_mark_dirty)
    custom_height: IntProperty(name="Height", default=1024, min=1, max=16384, update=_mark_dirty)
    resample_mode: EnumProperty(
        name="Resize",
        items=[('BILINEAR', "Bilinear", "Smooth resize"), ('NEAREST', "Nearest", "Nearest-pixel resize")],
        default='BILINEAR', update=_mark_dirty,
    )
    output_format: EnumProperty(name="Format", items=FORMAT_ITEMS, default='PNG')
    output_name: StringProperty(name="Name", update=_output_name_updated)
    output_name_auto: StringProperty(options={'HIDDEN'})
    generated_image_name: StringProperty()
    generated_material_name: StringProperty()
    last_export_path: StringProperty()
    update_status: StringProperty()
    update_status_token: IntProperty(default=0)
    operation_status: StringProperty()
    operation_status_error: BoolProperty(default=False)
    operation_status_token: IntProperty(default=0)
    alpha_content_active: BoolProperty(default=False, options={'HIDDEN'})
    generation_signature: StringProperty()
    generation_valid: BoolProperty(default=False)


class FTM_OT_reset(Operator):
    bl_idname = "ftm.reset_all"
    bl_label = "Reset All"
    bl_description = "Reset the panel without deleting generated images or materials"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        settings = context.scene.ftm_settings
        settings.sources.clear(); settings.channels.clear()
        settings.uid_counter = 0
        settings.sources_expanded = True
        settings.editing_channel = ""; settings.edit_snapshot = ""
        settings.source_mode = 'MATERIAL'
        settings.source_material_name = ""
        settings.output_color_type = 'DATA'
        settings.output_size = '1024'
        settings.custom_width = 1024; settings.custom_height = 1024
        settings.resample_mode = 'BILINEAR'; settings.output_format = 'PNG'; settings.output_name = ""
        settings.output_name_auto = ""
        settings.generated_image_name = ""; settings.generated_material_name = ""
        settings.last_export_path = ""
        settings.update_status = ""
        settings.operation_status = ""; settings.operation_status_error = False
        settings.alpha_content_active = False
        settings.generation_signature = ""; settings.generation_valid = False
        _ensure_defaults(settings)
        _refresh_output_name(settings, force=True)
        return {'FINISHED'}


class FTM_OT_add_source(Operator):
    bl_idname = "ftm.add_source"
    bl_label = "Add Image"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        settings = context.scene.ftm_settings
        _add_source(settings)
        settings.sources_expanded = True
        _mark_dirty(context=context)
        return {'FINISHED'}


class FTM_OT_clear_sources(Operator):
    bl_idname = "ftm.clear_sources"
    bl_label = "清空圖片"
    bl_description = "清空圖片欄並保留一個不可刪除的空白欄位"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        settings = context.scene.ftm_settings
        settings.sources.clear()
        settings.channels.clear()
        settings.uid_counter = 0
        settings.source_material_name = ""
        settings.alpha_content_active = False
        _ensure_defaults(settings)
        _refresh_output_name(settings, force=True)
        settings.generation_valid = False
        return {'FINISHED'}


class FTM_OT_remove_source(Operator):
    bl_idname = "ftm.remove_source"
    bl_label = "Remove Image"
    bl_options = {'REGISTER', 'UNDO'}
    index: IntProperty(default=-1)

    def execute(self, context):
        settings = context.scene.ftm_settings
        if len(settings.sources) > 1 and 0 <= self.index < len(settings.sources):
            settings.sources.remove(self.index)
            _mark_dirty(context=context)
        return {'FINISHED'}


class FTM_OT_clear_source_image(Operator):
    bl_idname = "ftm.clear_source_image"
    bl_label = "Clear Image"
    bl_description = "清除這個欄位的圖片"
    bl_options = {'REGISTER', 'UNDO'}
    index: IntProperty(default=-1)

    def execute(self, context):
        settings = context.scene.ftm_settings
        if not (0 <= self.index < len(settings.sources)):
            return {'CANCELLED'}
        source = settings.sources[self.index]
        source.image = None
        source.source_type = 'CUSTOM'
        source.node_name = ""
        source.external_import = False
        source.from_material = False
        _mark_dirty(context=context)
        return {'FINISHED'}


class FTM_OT_open_external(Operator, ImportHelper):
    bl_idname = "ftm.open_external_image"
    bl_label = "Open External Image"
    filename_ext = ""
    filter_glob: StringProperty(default="*.png;*.jpg;*.jpeg;*.tga;*.tif;*.tiff;*.exr;*.hdr;*.bmp", options={'HIDDEN'})
    index: IntProperty(default=-1)

    def execute(self, context):
        settings = context.scene.ftm_settings
        if not (0 <= self.index < len(settings.sources)):
            return {'CANCELLED'}
        try:
            image = bpy.data.images.load(self.filepath, check_existing=False)
            image.name = os.path.basename(self.filepath)
            image.pack()
        except Exception as exc:
            self.report({'ERROR'}, f"無法開啟圖片：{exc}")
            return {'CANCELLED'}
        source = settings.sources[self.index]
        source.image = image
        source.source_type = _detect_source_type(image.name)
        source.external_import = True
        _mark_dirty(context=context)
        return {'FINISHED'}


class FTM_OT_scan_material(Operator):
    bl_idname = "ftm.scan_material"
    bl_label = "Scan Material Images"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.object
        material = obj.active_material if obj and obj.type == 'MESH' else None
        if not material or not material.use_nodes:
            self.report({'ERROR'}, "請先選取使用節點材質的 Mesh")
            return {'CANCELLED'}
        image_nodes = [node for node in material.node_tree.nodes if node.type == 'TEX_IMAGE' and node.image]
        if not image_nodes:
            self.report({'ERROR'}, "目前材質沒有 Image Texture")
            return {'CANCELLED'}
        settings = context.scene.ftm_settings
        settings.source_mode = 'MATERIAL'
        manual_sources = [
            (source.uid, source.image, source.source_type, source.node_name, source.external_import)
            for source in settings.sources if not source.from_material and source.image
        ]
        reusable_uids = {}
        for source in settings.sources:
            if source.from_material:
                reusable_uids.setdefault(source.source_type, []).append(source.uid)
        settings.sources.clear()
        settings.alpha_content_active = False
        settings.source_material_name = material.name
        for node in image_nodes:
            source_type = _node_semantic(material, node)
            uid_pool = reusable_uids.get(source_type, [])
            uid = uid_pool.pop(0) if uid_pool else ""
            _add_source(settings, node.image, source_type, node.name, from_material=True, uid=uid)
        for uid, image, source_type, node_name, external in manual_sources:
            _add_source(settings, image, source_type, node_name, external, uid=uid)
        _ensure_channels(settings)
        _refresh_output_name(settings)
        settings.generation_valid = False
        self.report({'INFO'}, f"已添加 {len(image_nodes)} 張模型貼圖")
        return {'FINISHED'}


class FTM_OT_edit_channel(Operator):
    bl_idname = "ftm.edit_channel"
    bl_label = "Select Source Channels"
    bl_options = {'REGISTER', 'UNDO'}
    target_channel: StringProperty()

    def execute(self, context):
        settings = context.scene.ftm_settings
        channel_item = _channel(settings, self.target_channel)
        if channel_item is None:
            return {'CANCELLED'}
        snapshot = {
            "terms": [(term.source_uid, term.source_channel) for term in channel_item.terms if term.enabled],
            "usage": channel_item.usage,
            "format": settings.output_format,
            "alpha": settings.alpha_content_active,
            "name": settings.output_name,
            "auto_name": settings.output_name_auto,
            "valid": settings.generation_valid,
            "signature": settings.generation_signature,
        }
        _sync_terms(settings, channel_item)
        settings.edit_snapshot = json.dumps(snapshot)
        settings.editing_channel = self.target_channel
        return {'FINISHED'}


class FTM_OT_confirm_channel(Operator):
    bl_idname = "ftm.confirm_channel"
    bl_label = "OK"

    def execute(self, context):
        settings = context.scene.ftm_settings
        channel_item = _channel(settings, settings.editing_channel)
        if channel_item:
            _refresh_channel_usage(settings, channel_item)
        settings.editing_channel = ""
        settings.edit_snapshot = ""
        settings.generation_valid = False
        return {'FINISHED'}


class FTM_OT_cancel_channel(Operator):
    bl_idname = "ftm.cancel_channel"
    bl_label = "Cancel"

    def execute(self, context):
        settings = context.scene.ftm_settings
        channel_item = _channel(settings, settings.editing_channel)
        try:
            snapshot = json.loads(settings.edit_snapshot or "{}")
        except json.JSONDecodeError:
            snapshot = {}
        if channel_item:
            enabled = {tuple(value) for value in snapshot.get("terms", [])}
            for term in channel_item.terms:
                term.enabled = (term.source_uid, term.source_channel) in enabled
            channel_item.usage = snapshot.get("usage", channel_item.usage)
        settings.output_format = snapshot.get("format", settings.output_format)
        settings.alpha_content_active = snapshot.get("alpha", settings.alpha_content_active)
        settings.output_name_auto = snapshot.get("auto_name", settings.output_name_auto)
        settings.output_name = snapshot.get("name", settings.output_name)
        settings.generation_signature = snapshot.get("signature", settings.generation_signature)
        settings.generation_valid = snapshot.get("valid", settings.generation_valid)
        settings.editing_channel = ""
        settings.edit_snapshot = ""
        return {'FINISHED'}


class FTM_OT_reset_channel(Operator):
    bl_idname = "ftm.reset_channel"
    bl_label = "Reset"
    bl_description = "清空目前輸出通道選取的所有來源通道"

    def execute(self, context):
        settings = context.scene.ftm_settings
        channel_item = _channel(settings, settings.editing_channel)
        if not channel_item:
            return {'CANCELLED'}
        for term in channel_item.terms:
            term.enabled = False
        channel_item.usage = 'NONE'
        return {'FINISHED'}


class FTM_OT_merge_texture(Operator):
    bl_idname = "ftm.merge_texture"
    bl_label = "Merge Texture"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        settings = _settings(context)
        return bool(settings and any(_enabled_terms(settings, item) for item in settings.channels))

    def execute(self, context):
        settings = context.scene.ftm_settings
        width, height = _output_size(settings)
        try:
            pixels = _build_pixels(settings, width, height)
            requested_name = _base_output_name(settings)
            image = bpy.data.images.new(requested_name, width=width, height=height, alpha=True, float_buffer=settings.output_format == 'OPEN_EXR')
            image.generated_color = (0.0, 0.0, 0.0, 1.0)
            # Blender 5.2 reallocates a generated image's pixel buffer when its
            # color space changes, so choose the color space before writing.
            _safe_colorspace(image, 'sRGB' if settings.output_color_type == 'COLOR' else 'Non-Color')
            image.pixels.foreach_set(pixels)
            image.update()
        except Exception as exc:
            _set_operation_status(settings, f"合併失敗：{exc}", True)
            self.report({'ERROR'}, f"合併失敗：{exc}")
            return {'CANCELLED'}
        settings.generated_image_name = image.name
        settings.generated_material_name = ""
        settings.last_export_path = ""
        settings.generation_signature = _configuration_signature(settings)
        settings.generation_valid = True
        _set_operation_status(settings, "貼圖合併成功")
        self.report({'INFO'}, f"已在 Blender 建立合併圖：{image.name}")
        return {'FINISHED'}


def _generation_is_current(settings):
    if not settings.generation_valid or not settings.generated_image_name:
        return False
    if bpy.data.images.get(settings.generated_image_name) is None:
        return False
    return settings.generation_signature == _configuration_signature(settings)


class FTM_OT_connect_material(Operator):
    bl_idname = "ftm.connect_material"
    bl_label = "建立串接材質"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        settings = _settings(context)
        return bool(
            settings and _generation_is_current(settings) and
            not (settings.generated_material_name and bpy.data.materials.get(settings.generated_material_name))
        )

    def execute(self, context):
        settings = context.scene.ftm_settings
        image = bpy.data.images.get(settings.generated_image_name)
        if not image or not _generation_is_current(settings):
            self.report({'ERROR'}, "請先重新合併貼圖")
            return {'CANCELLED'}
        source_material = bpy.data.materials.get(settings.source_material_name) if settings.source_mode == 'MATERIAL' else None
        material = source_material.copy() if source_material else bpy.data.materials.new(f"{image.name}_Mat")
        material.name = f"{image.name}_Mat"
        material.use_nodes = True
        tree = material.node_tree
        tree.nodes.clear()
        output = tree.nodes.new('ShaderNodeOutputMaterial'); output.location = (900, 0)
        principled = tree.nodes.new('ShaderNodeBsdfPrincipled'); principled.location = (620, 0)
        tree.links.new(principled.outputs['BSDF'], output.inputs['Surface'])
        texture = tree.nodes.new('ShaderNodeTexImage'); texture.image = image; texture.label = image.name; texture.location = (-700, 0)
        separate = tree.nodes.new('ShaderNodeSeparateColor'); separate.mode = 'RGB'; separate.location = (-470, 0)
        tree.links.new(texture.outputs['Color'], separate.inputs['Color'])
        sockets = {item.channel: _channel_socket(tree, texture, separate, item.channel) for item in settings.channels}
        usages = {item.channel: item.usage for item in settings.channels}

        diffuse = {channel: sockets[channel] for channel in CHANNELS if usages.get(channel) == 'DIFFUSE' and channel != 'A'}
        base_color = None
        if diffuse:
            base_color = _combine_rgb(tree, diffuse, (-180, 240))
            target = _socket(principled, ('Base Color',))
            if target: tree.links.new(base_color, target)

        emission = {channel: sockets[channel] for channel in CHANNELS if usages.get(channel) == 'EMISSION' and channel != 'A'}
        if emission:
            emission_color = _combine_rgb(tree, emission, (-180, -360))
            target = _socket(principled, ('Emission Color', 'Emission'))
            if target: tree.links.new(emission_color, target)

        normal_channels = {}
        for channel, usage in usages.items():
            if usage == 'NORMAL_X': normal_channels['R'] = sockets[channel]
            elif usage == 'NORMAL_Y': normal_channels['G'] = sockets[channel]
            elif usage == 'NORMAL_Z': normal_channels['B'] = sockets[channel]
        normal_output = _normal_from_channels(tree, normal_channels, (-180, -40)) if normal_channels else None
        normal_target = _socket(principled, ('Normal',))
        if normal_output and normal_target: tree.links.new(normal_output, normal_target)

        scalar_targets = {
            'METALLIC': ('Metallic',), 'ROUGHNESS': ('Roughness',),
            'EMISSION_STRENGTH': ('Emission Strength',), 'ALPHA': ('Alpha',),
            'SPECULAR': ('Specular IOR Level', 'Specular'),
        }
        for channel, usage in usages.items():
            if usage in scalar_targets:
                target = _socket(principled, scalar_targets[usage])
                if target: tree.links.new(sockets[channel], target)
            elif usage == 'HEIGHT':
                bump = tree.nodes.new('ShaderNodeBump'); bump.location = (350, -220)
                tree.links.new(sockets[channel], bump.inputs['Height'])
                if normal_output: tree.links.new(normal_output, bump.inputs['Normal'])
                if normal_target: tree.links.new(bump.outputs['Normal'], normal_target)
            elif usage == 'AO' and base_color:
                multiply = tree.nodes.new('ShaderNodeMixRGB'); multiply.blend_type = 'MULTIPLY'; multiply.inputs[0].default_value = 1.0; multiply.location = (350, 240)
                tree.links.new(base_color, multiply.inputs[1]); tree.links.new(sockets[channel], multiply.inputs[2])
                target = _socket(principled, ('Base Color',))
                if target: tree.links.new(multiply.outputs['Color'], target)

        settings.generated_material_name = material.name
        self.report({'INFO'}, f"已建立新材質：{material.name}（未替換模型原材質）")
        return {'FINISHED'}


class FTM_OT_apply_material(Operator):
    bl_idname = "ftm.apply_material"
    bl_label = "套用材質"
    bl_description = "用新材質替換掃描時指定的原材質；找不到時新增材質槽"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        settings = _settings(context)
        obj = getattr(context, "object", None)
        return bool(
            settings and settings.generated_material_name and
            bpy.data.materials.get(settings.generated_material_name) and
            obj and obj.type == 'MESH' and
            (
                any(slot.material and slot.material.name == settings.source_material_name for slot in obj.material_slots) or
                not any(slot.material and slot.material.name == settings.generated_material_name for slot in obj.material_slots)
            )
        )

    def execute(self, context):
        settings = context.scene.ftm_settings
        material = bpy.data.materials.get(settings.generated_material_name)
        obj = context.object
        replaced = 0
        for slot in obj.material_slots:
            if slot.material and slot.material.name == settings.source_material_name:
                slot.material = material
                replaced += 1
        if replaced:
            self.report({'INFO'}, f"已替換 {replaced} 個原材質槽：{material.name}")
            return {'FINISHED'}
        if any(slot.material == material for slot in obj.material_slots):
            self.report({'INFO'}, "模型已經套用這個新材質")
            return {'FINISHED'}
        obj.data.materials.append(material)
        self.report({'INFO'}, f"已新增材質到模型：{material.name}")
        return {'FINISHED'}


class FTM_OT_export_texture(Operator, ExportHelper):
    bl_idname = "ftm.export_texture"
    bl_label = "Export Texture"
    filename_ext = ".png"
    filter_glob: StringProperty(default="*.png;*.tga;*.tif;*.tiff;*.exr", options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        settings = _settings(context)
        return bool(settings and _generation_is_current(settings))

    def invoke(self, context, event):
        settings = context.scene.ftm_settings
        extension = FORMAT_EXTENSIONS[settings.output_format]
        self.filename_ext = extension
        self.filepath = bpy.path.abspath("//" + settings.generated_image_name + extension)
        return ExportHelper.invoke(self, context, event)

    def execute(self, context):
        settings = context.scene.ftm_settings
        image = bpy.data.images.get(settings.generated_image_name)
        if not image:
            return {'CANCELLED'}
        old_path, old_format = image.filepath_raw, image.file_format
        try:
            image.filepath_raw = self.filepath
            image.file_format = settings.output_format
            image.save()
        except Exception as exc:
            _set_operation_status(settings, f"輸出失敗：{exc}", True)
            self.report({'ERROR'}, f"輸出失敗：{exc}")
            return {'CANCELLED'}
        finally:
            image.filepath_raw = old_path
            image.file_format = old_format
        settings.last_export_path = self.filepath
        _set_operation_status(settings, "貼圖輸出成功")
        self.report({'INFO'}, f"已輸出：{self.filepath}")
        return {'FINISHED'}


class FTM_OT_open_export_location(Operator):
    bl_idname = "ftm.open_export_location"
    bl_label = "Open File Location"
    bl_description = "開啟最後匯出貼圖所在的資料夾"

    @classmethod
    def poll(cls, context):
        settings = _settings(context)
        return bool(settings and settings.last_export_path and os.path.isfile(settings.last_export_path))

    def execute(self, context):
        filepath = context.scene.ftm_settings.last_export_path
        folder = os.path.dirname(filepath)
        if not folder or not os.path.isdir(folder):
            self.report({'ERROR'}, "找不到匯出資料夾")
            return {'CANCELLED'}
        try:
            if os.name == 'nt':
                subprocess.Popen(
                    ["explorer.exe", "/select,", os.path.normpath(filepath)],
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:
                bpy.ops.wm.path_open(filepath=folder)
        except OSError as exc:
            self.report({'ERROR'}, f"無法開啟輸出位置：{exc}")
            return {'CANCELLED'}
        return {'FINISHED'}


def _github_repository(context):
    for index, repo in enumerate(context.preferences.extensions.repos):
        if repo.remote_url.rstrip("/") == GITHUB_REPOSITORY_URL.rstrip("/"):
            return index, repo
    return None, None


def _ensure_github_repository(context):
    index, repo = _github_repository(context)
    if repo is not None:
        repo.enabled = True
        repo.use_sync_on_startup = True
        return index, repo
    result = bpy.ops.preferences.extension_repo_add(
        name="Faidlix Blender Add-ons",
        remote_url=GITHUB_REPOSITORY_URL,
        use_sync_on_startup=True,
        type='REMOTE',
    )
    return _github_repository(context) if result == {'FINISHED'} else (None, None)


def _version_tuple(version):
    try:
        return tuple(int(part) for part in version.split('.'))
    except (AttributeError, TypeError, ValueError):
        return ()


def _latest_version_from_index(index_data):
    versions = [
        _version_tuple(item.get('version'))
        for item in index_data.get('data', [])
        if item.get('id') == PACKAGE_ID
    ]
    return max((version for version in versions if version), default=())


def _cached_repository_index(repo):
    path = os.path.join(repo.directory, '.blender_ext', 'index.json')
    try:
        with open(path, 'r', encoding='utf8') as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


class FTM_OT_online_update(Operator):
    bl_idname = "ftm.online_update"
    bl_label = "線上更新"
    bl_description = "從 Faidlix/BlenderAddons 檢查並安裝較新版本"
    bl_options = {'INTERNAL'}

    force: BoolProperty(default=False, options={'HIDDEN'})

    def execute(self, context):
        settings = context.scene.ftm_settings
        context.preferences.system.use_online_access = True
        repo_index, repo = _ensure_github_repository(context)
        if repo is None:
            _set_update_status(settings, "無法建立 Faidlix 集中更新來源")
            self.report({'ERROR'}, settings.update_status)
            return {'CANCELLED'}
        try:
            if bpy.ops.extensions.repo_sync(repo_index=repo_index) != {'FINISHED'}:
                raise RuntimeError("同步未完成")
        except RuntimeError as exc:
            _set_update_status(settings, f"GitHub 同步失敗：{exc}")
            self.report({'ERROR'}, settings.update_status)
            return {'CANCELLED'}
        latest = _latest_version_from_index(_cached_repository_index(repo) or {})
        if not latest:
            _set_update_status(settings, "集中索引中找不到 Texture Marge")
            self.report({'ERROR'}, settings.update_status)
            return {'CANCELLED'}
        if latest <= ADDON_VERSION and not self.force:
            bpy.ops.wm.save_userpref()
            _set_update_status(settings, "已是最新版本")
            self.report({'INFO'}, settings.update_status)
            return {'FINISHED'}
        version_text = '.'.join(map(str, latest))

        def install_after_operator_returns():
            try:
                result = bpy.ops.extensions.package_install(
                    repo_index=repo_index,
                    pkg_id=PACKAGE_ID,
                    enable_on_install=True,
                )
                if result == {'FINISHED'}:
                    bpy.ops.wm.save_userpref()
                    print(f"Faidlix Texture Marge {version_text} installed from GitHub")
                else:
                    print("Faidlix Texture Marge online update did not finish")
            except Exception as exc:
                print(f"Faidlix Texture Marge online update failed: {exc}")
            return None

        bpy.app.timers.register(install_after_operator_returns, first_interval=0.1)
        _set_update_status(settings, f"已找到 {version_text}，準備安裝")
        self.report({'INFO'}, settings.update_status)
        return {'FINISHED'}


class FTM_PT_panel(Panel):
    bl_label = "Faidlix Texture Marge"
    bl_idname = "FTM_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Faidlix'
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header_preset(self, _context):
        row = self.layout.row(align=True)
        row.alignment = 'RIGHT'
        row.label(text=f"v{'.'.join(map(str, ADDON_VERSION))}")

    def draw(self, context):
        layout = self.layout
        settings = context.scene.ftm_settings
        editing = bool(settings.editing_channel)

        def labeled_prop(container, label, data, property_name, *, expand=False):
            row = container.row(align=True)
            split = row.split(factor=0.13, align=True)
            split.label(text=label)
            controls = split.row(align=True)
            if expand:
                controls.prop(data, property_name, expand=True)
            else:
                controls.prop(data, property_name, text="")
            return controls

        top_controls = layout.row(align=True)
        top_controls.enabled = not editing
        top_controls.operator(FTM_OT_reset.bl_idname, text="全部重置", icon='FILE_REFRESH')
        if settings.update_status:
            update_status = top_controls.row(align=True)
            update_status.enabled = False
            update_status.operator(FTM_OT_online_update.bl_idname, text=settings.update_status, icon='INFO')
        else:
            top_controls.operator(FTM_OT_online_update.bl_idname, text="線上更新", icon='URL')
        source_layout = layout.column()
        source_layout.enabled = not editing

        source_box = source_layout.box()
        obj = context.object
        material = obj.active_material if obj and obj.type == 'MESH' else None
        scan_info = source_box.row(align=True)
        scan_split = scan_info.split(factor=0.38, align=True)
        scan_button = scan_split.column(align=True)
        scan_button.scale_y = 2.0
        scan_button.operator(FTM_OT_scan_material.bl_idname, text="添加模型貼圖", icon='VIEWZOOM')
        info_column = scan_split.column(align=True)
        info_column.label(text=f"模型：{obj.name if obj else '未選到'}")
        info_column.label(text=f"材質：{material.name if material else '未選到'}")
        source_controls = source_box.row(align=True)
        source_controls.prop(settings, "sources_expanded", text="", icon='TRIA_DOWN' if settings.sources_expanded else 'TRIA_RIGHT', emboss=False)
        source_controls.operator(FTM_OT_add_source.bl_idname, text="新增圖片", icon='ADD')
        source_controls.operator(FTM_OT_clear_sources.bl_idname, text="清空", icon='TRASH')
        if settings.sources_expanded:
            for index, source in enumerate(settings.sources):
                item = source_box.box()
                row = item.row(align=True)
                if len(settings.sources) > 1:
                    remove = row.operator(FTM_OT_remove_source.bl_idname, text="", icon='REMOVE')
                    remove.index = index
                image_field = row.row(align=True)
                image_field.prop_search(source, "image", bpy.data, "images", text="", icon='IMAGE_DATA')
                clear_image = image_field.row(align=True)
                clear_image.enabled = source.image is not None
                clear_op = clear_image.operator(FTM_OT_clear_source_image.bl_idname, text="", icon='X')
                clear_op.index = index
                open_op = row.operator(FTM_OT_open_external.bl_idname, text="", icon='FILE_FOLDER')
                open_op.index = index
                labeled_prop(item, "類型", source, "source_type")

        map_box = layout.box()
        map_box.label(text="輸出通道", icon='NODETREE')
        for channel_item in settings.channels:
            box = map_box.box()
            row = box.row(align=True)
            row.enabled = not editing
            channel_split = row.split(factor=0.07, align=True)
            channel_split.label(text=channel_item.channel)
            channel_controls = channel_split.row(align=True)
            content_split = channel_controls.split(factor=0.50, align=True)
            select = content_split.operator(FTM_OT_edit_channel.bl_idname, text=_term_summary(settings, channel_item))
            select.target_channel = channel_item.channel
            usage = content_split.row(align=True)
            usage_label = usage.row(align=True)
            usage_label.ui_units_x = 3.0
            usage_label.label(text="用途")
            usage.prop(channel_item, "usage", text="")
            if len(_enabled_terms(settings, channel_item)) > 1 and not editing:
                mix_row = box.row(align=True)
                mix_row.enabled = not editing
                mix_split = mix_row.split(factor=0.13, align=True)
                mix_split.label(text="混合")
                mix_split.row(align=True).prop(channel_item, "blend_mode", expand=True)
            if settings.editing_channel == channel_item.channel:
                editor = box.box()
                for source in settings.sources:
                    if not source.image:
                        continue
                    type_label = dict((item[0], item[1]) for item in SOURCE_TYPES).get(source.source_type, source.source_type)
                    source_row = editor.row(align=True)
                    type_column = source_row.row(align=True)
                    type_column.ui_units_x = 10.0
                    type_column.label(text=type_label)
                    source_row.label(text=source.image.name)
                    buttons = source_row.row(align=True)
                    buttons.ui_units_x = 8.0
                    for source_channel in CHANNELS:
                        term = next((term for term in channel_item.terms if term.source_uid == source.uid and term.source_channel == source_channel), None)
                        if term:
                            buttons.prop(term, "enabled", text=source_channel, toggle=True)
                confirm_row = editor.row(align=True)
                confirm_row.operator(FTM_OT_reset_channel.bl_idname)
                confirm_row.operator(FTM_OT_cancel_channel.bl_idname)
                confirm_row.operator(FTM_OT_confirm_channel.bl_idname)

        output_box = layout.box()
        output_box.enabled = not editing
        output_box.label(text="輸出設定", icon='OUTPUT')
        labeled_prop(output_box, "名稱", settings, "output_name")
        labeled_prop(output_box, "類型", settings, "output_color_type", expand=True)
        labeled_prop(output_box, "尺寸", settings, "output_size", expand=True)
        if settings.output_size == 'CUSTOM':
            row = output_box.row(align=True)
            split = row.split(factor=0.13, align=True)
            split.label(text="")
            dimensions = split.row(align=True)
            dimensions.prop(settings, "custom_width", text="W")
            dimensions.prop(settings, "custom_height", text="H")
        labeled_prop(output_box, "縮放", settings, "resample_mode", expand=True)
        labeled_prop(output_box, "格式", settings, "output_format", expand=True)
        alpha_channel = _channel(settings, 'A')
        if settings.output_format == 'PNG' and alpha_channel and _enabled_terms(settings, alpha_channel):
            output_box.label(text="A 通道有內容：建議使用 TGA 保留色版", icon='ERROR')

        row = layout.row(align=True)
        row.enabled = not editing
        row.operator(FTM_OT_merge_texture.bl_idname, icon='IMAGE')
        row.operator(FTM_OT_export_texture.bl_idname, icon='EXPORT')
        status_row = layout.row(align=True)
        status_row.enabled = not editing
        if settings.operation_status:
            status_row.label(text=settings.operation_status, icon='ERROR' if settings.operation_status_error else 'CHECKMARK')
        elif _generation_is_current(settings):
            status_row.label(text=f"合併圖：{settings.generated_image_name}", icon='CHECKMARK')
        else:
            status_row.label(text="未合併貼圖", icon='ERROR')
        if settings.last_export_path and os.path.isfile(settings.last_export_path):
            status_row.operator(FTM_OT_open_export_location.bl_idname, text="開啟輸出位置", icon='FILE_FOLDER')

        material_row = layout.row(align=True)
        material_row.enabled = not editing
        material_row.operator(FTM_OT_connect_material.bl_idname, icon='MATERIAL')
        if settings.generated_material_name:
            row = layout.row(align=True)
            row.enabled = not editing
            row.label(text=f"新材質：{settings.generated_material_name}", icon='MATERIAL')
            row.operator(FTM_OT_apply_material.bl_idname, text="套用材質")


PROPERTY_CLASSES = (FTMSource, FTMTerm, FTMOutputChannel, FTMSettings)
OPERATOR_CLASSES = (
    FTM_OT_reset, FTM_OT_add_source, FTM_OT_clear_sources, FTM_OT_remove_source, FTM_OT_clear_source_image, FTM_OT_open_external,
    FTM_OT_scan_material, FTM_OT_edit_channel, FTM_OT_confirm_channel, FTM_OT_cancel_channel, FTM_OT_reset_channel, FTM_OT_merge_texture,
    FTM_OT_connect_material, FTM_OT_apply_material, FTM_OT_export_texture, FTM_OT_open_export_location,
    FTM_OT_online_update,
)
UI_CLASSES = (FTM_PT_panel,)
CLASSES = PROPERTY_CLASSES + OPERATOR_CLASSES + UI_CLASSES


@persistent
def _load_defaults(_dummy):
    for scene in bpy.data.scenes:
        if hasattr(scene, "ftm_settings"):
            _ensure_defaults(scene.ftm_settings)


def _initialize_current_scenes():
    scenes = getattr(getattr(bpy, "data", None), "scenes", None)
    if scenes is None:
        return 0.1
    for scene in scenes:
        if hasattr(scene, "ftm_settings"):
            _ensure_defaults(scene.ftm_settings)
    return None


def register():
    for cls in PROPERTY_CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.ftm_settings = PointerProperty(type=FTMSettings)
    for cls in OPERATOR_CLASSES + UI_CLASSES:
        bpy.utils.register_class(cls)
    if _load_defaults not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_load_defaults)
    if not bpy.app.timers.is_registered(_initialize_current_scenes):
        bpy.app.timers.register(_initialize_current_scenes, first_interval=0.1)


def unregister():
    if bpy.app.timers.is_registered(_initialize_current_scenes):
        bpy.app.timers.unregister(_initialize_current_scenes)
    if _load_defaults in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_load_defaults)
    for cls in reversed(OPERATOR_CLASSES + UI_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
    if hasattr(bpy.types.Scene, "ftm_settings"):
        del bpy.types.Scene.ftm_settings
    for cls in reversed(PROPERTY_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass

