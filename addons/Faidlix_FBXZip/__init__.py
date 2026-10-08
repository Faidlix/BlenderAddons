bl_info = {
    "name": "Faidlix_Fbx ZipExporter",
    "author": "Faidlix",
    "version": (1, 7, 3),
    "blender": (5, 2, 0),
    "location": "View3D > Sidebar > Faidlix",
    "description": "Export FBX with adjustable Blender FBX options and package used textures into a ZIP.",
    "category": "Import-Export",
}

import hashlib
import json
import os
import shutil
import tempfile
import zipfile

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import Menu, Operator, Panel
from bpy_extras.io_utils import ExportHelper
from bl_operators.presets import AddPresetBase


ADDON_VERSION = (1, 7, 3)
PACKAGE_ID = "faidlix_fbx_zip_exporter"
REPOSITORY_URL = (
    "https://raw.githubusercontent.com/Faidlix/"
    "BlenderAddons/main/repository/index.json"
)
_UPDATE_STATUS = ""


def _repository(context):
    for index, repo in enumerate(context.preferences.extensions.repos):
        if repo.remote_url.rstrip("/") == REPOSITORY_URL.rstrip("/"):
            return index, repo
    return None, None


def _ensure_repository(context):
    index, repo = _repository(context)
    if repo is not None:
        repo.enabled = True
        repo.use_sync_on_startup = True
        return index, repo
    result = bpy.ops.preferences.extension_repo_add(
        name="Faidlix Blender Add-ons",
        remote_url=REPOSITORY_URL,
        use_sync_on_startup=True,
        type='REMOTE',
    )
    return _repository(context) if result == {'FINISHED'} else (None, None)


def _version(value):
    try:
        return tuple(int(part) for part in value.split("."))
    except (AttributeError, TypeError, ValueError):
        return ()


def _repository_index(repo):
    path = os.path.join(repo.directory, ".blender_ext", "index.json")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {"data": []}


def _latest_version(index_data):
    versions = [
        _version(item.get("version"))
        for item in index_data.get("data", [])
        if item.get("id") == PACKAGE_ID
    ]
    return max((version for version in versions if version), default=())


def _object_images(objects):
    return list(dict.fromkeys(node.image for node in _used_image_nodes(objects)))


def _used_image_nodes(objects):
    """Walk backwards from active material outputs, including nested groups."""
    result, visited = [], set()

    def socket_walk(socket, parents=()):
        for link in socket.links:
            if not getattr(link, 'is_valid', True) or getattr(link, 'is_muted', False):
                continue
            node, output = link.from_node, link.from_socket
            key = (node.as_pointer(), output.identifier, tuple(n.as_pointer() for n in parents))
            if key in visited:
                continue
            visited.add(key)
            if node.mute:
                for internal in node.internal_links:
                    if internal.to_socket == output:
                        socket_walk(internal.from_socket, parents)
                continue
            if node.type == 'GROUP' and node.node_tree:
                for group_output in node.node_tree.nodes:
                    if group_output.type == 'GROUP_OUTPUT' and group_output.is_active_output:
                        index = list(node.outputs).index(output)
                        if index < len(group_output.inputs):
                            socket_walk(group_output.inputs[index], parents + (node,))
                continue
            if node.type == 'GROUP_INPUT' and parents:
                index = list(node.outputs).index(output)
                if index < len(parents[-1].inputs):
                    socket_walk(parents[-1].inputs[index], parents[:-1])
                continue
            if getattr(node, 'image', None) and node not in result:
                result.append(node)
            for input_socket in node.inputs:
                socket_walk(input_socket, parents)

    for obj in objects:
        used_slots = None
        if obj.type == 'MESH' and obj.data.polygons:
            used_slots = {p.material_index for p in obj.data.polygons}
        for slot_index, slot in enumerate(getattr(obj, "material_slots", ())):
            if used_slots is not None and slot_index not in used_slots:
                continue
            material = slot.material
            if not material or not material.use_nodes or not material.node_tree:
                continue
            for node in material.node_tree.nodes:
                if node.type == 'OUTPUT_MATERIAL' and node.is_active_output:
                    for input_socket in node.inputs:
                        socket_walk(input_socket)
    return result


def _export_objects(context, operator):
    collection = (context.view_layer.active_layer_collection.collection
                  if operator.use_active_collection else bpy.data.collections.get(operator.collection))
    objects = list(collection.all_objects) if collection else list(context.view_layer.objects)
    if operator.use_selection:
        objects = [obj for obj in objects if obj.select_get()]
    if operator.use_visible:
        objects = [obj for obj in objects if obj.visible_get()]
    return [obj for obj in objects if obj.type in operator.object_types
            or (obj.type not in {'EMPTY', 'CAMERA', 'LIGHT', 'ARMATURE', 'MESH'} and 'OTHER' in operator.object_types)]


def _input(node, *names):
    for name in names:
        if node.inputs.get(name):
            return node.inputs.get(name)
    return None


def _linked_image(socket):
    if not socket or not socket.is_linked:
        return None
    node = socket.links[0].from_node
    image = getattr(node, "image", None)
    if image:
        return image
    if node.bl_idname == "ShaderNodeNormalMap":
        return _linked_image(node.inputs.get("Color"))
    return None


def _named_image(material, keywords):
    for node in material.node_tree.nodes:
        image = getattr(node, "image", None)
        label = f"{node.name} {node.label}".lower()
        if image and any(keyword in label for keyword in keywords):
            return image
    return None


def _prepare_unity_standard_materials(objects):
    """Temporarily replace object materials with Unity Standard-friendly nodes."""
    restore = []
    copied_by_material = {}
    for obj in objects:
        if not hasattr(obj, "material_slots"):
            continue
        for slot_index, slot in enumerate(obj.material_slots):
            source = slot.material
            if not source:
                continue
            if source.name not in copied_by_material:
                copied = source.copy()
                copied.use_nodes = True
                tree = copied.node_tree
                tree.nodes.clear()
                output = tree.nodes.new("ShaderNodeOutputMaterial")
                bsdf = tree.nodes.new("ShaderNodeBsdfPrincipled")
                tree.links.new(bsdf.outputs.get("BSDF"), output.inputs.get("Surface"))

                source_tree = source.node_tree if source.use_nodes and source.node_tree else None
                source_bsdf = next((n for n in source_tree.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled"), None) if source_tree else None
                mappings = {
                    "Base Color": (("Base Color",), ("base", "albedo", "diffuse", "color")),
                    "Metallic": (("Metallic",), ("metal",)),
                    "Roughness": (("Roughness",), ("rough",)),
                    "Emission Color": (("Emission Color", "Emission"), ("emission", "glow")),
                    "Alpha": (("Alpha",), ("alpha", "opacity")),
                }
                for target_name, (source_names, keywords) in mappings.items():
                    target = _input(bsdf, target_name)
                    image = _linked_image(_input(source_bsdf, *source_names)) if source_bsdf else None
                    if image and target:
                        tex = tree.nodes.new("ShaderNodeTexImage")
                        tex.image = image
                        tex.name = f"Unity_{target_name.replace(' ', '_')}"
                        tree.links.new(tex.outputs.get("Color"), target)
                    elif source_bsdf and target:
                        source_input = _input(source_bsdf, *source_names)
                        if source_input and not source_input.is_linked:
                            target.default_value = source_input.default_value

                normal_image = _linked_image(_input(source_bsdf, "Normal")) if source_bsdf else None
                normal_input = _input(bsdf, "Normal")
                if normal_image and normal_input:
                    tex = tree.nodes.new("ShaderNodeTexImage")
                    tex.image = normal_image
                    tex.name = "Unity_Normal"
                    normal = tree.nodes.new("ShaderNodeNormalMap")
                    tree.links.new(tex.outputs.get("Color"), normal.inputs.get("Color"))
                    tree.links.new(normal.outputs.get("Normal"), normal_input)
                copied_by_material[source.name] = copied
            restore.append((obj, slot_index, source))
            obj.material_slots[slot_index].material = copied_by_material[source.name]
    return restore


def _restore_materials(restore):
    for obj, slot_index, material in reversed(restore):
        if slot_index < len(obj.material_slots):
            obj.material_slots[slot_index].material = material


_SYNC_PROPERTIES = (
    "use_selection", "use_visible", "use_active_collection", "collection", "object_types", "global_scale",
    "apply_unit_scale", "apply_scale_options", "axis_forward", "axis_up", "use_space_transform",
    "bake_space_transform", "use_mesh_modifiers", "use_mesh_modifiers_render", "mesh_smooth_type",
    "colors_type", "prioritize_active_color", "use_subsurf", "use_mesh_edges", "use_tspace", "use_triangles",
    "use_custom_props", "add_leaf_bones", "primary_bone_axis", "secondary_bone_axis", "use_armature_deform_only",
    "armature_nodetype", "bake_anim", "bake_anim_use_all_bones", "bake_anim_use_nla_strips", "bake_anim_use_all_actions",
    "bake_anim_force_startend_keying", "bake_anim_step", "bake_anim_simplify_factor", "path_mode", "embed_textures",
    "batch_mode", "use_batch_own_dir", "use_metadata",
)


def _native_fbx_properties():
    return bpy.context.window_manager.operator_properties_last("EXPORT_SCENE_OT_fbx")


def _sync_from_native(operator):
    native = _native_fbx_properties()
    copied = 0
    for name in _SYNC_PROPERTIES:
        if hasattr(operator, name) and hasattr(native, name):
            try:
                setattr(operator, name, getattr(native, name))
                copied += 1
            except (TypeError, ValueError):
                pass
    return copied


def _sync_to_native(operator):
    native = _native_fbx_properties()
    copied = 0
    for name in _SYNC_PROPERTIES:
        if hasattr(operator, name) and hasattr(native, name):
            try:
                setattr(native, name, getattr(operator, name))
                copied += 1
            except (TypeError, ValueError):
                pass
    return copied


def _preset_dir():
    try:
        scripts = bpy.utils.user_resource("SCRIPTS", create=False)
        path = os.path.join(scripts, "presets", "fbx_zip")
        os.makedirs(path, exist_ok=True)
        return path
    except (OSError, PermissionError):
        # A portable/locked Blender install may not allow writing to its
        # scripts directory. Keep presets beside this add-on in that case.
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "presets")
        os.makedirs(path, exist_ok=True)
        return path


def _preset_path(name):
    safe = "".join(c for c in name.strip() if c.isalnum() or c in "-_ ").strip()
    if not safe:
        raise ValueError("預設集名稱不能為空")
    return os.path.join(_preset_dir(), safe + ".json")


def _preset_data(operator):
    data = {}
    for name in _SYNC_PROPERTIES:
        value = getattr(operator, name, None)
        if isinstance(value, set):
            value = sorted(value)
        data[name] = value
    data.update({
        "package_textures": getattr(operator, "package_textures", True),
        "keep_fbx": getattr(operator, "keep_fbx", True),
    })
    return data


def _apply_preset(operator, data):
    for name, value in data.items():
        if not hasattr(operator, name):
            continue
        try:
            if name == "object_types":
                value = set(value)
            setattr(operator, name, value)
        except (TypeError, ValueError):
            pass


def _safe_texture_name(image, used):
    raw = os.path.basename(bpy.path.abspath(image.filepath)) or image.name
    raw = raw.replace("\\", "_").replace("/", "_")
    if image.source in {'GENERATED', 'VIEWER'} or image.is_dirty:
        raw = os.path.splitext(raw)[0] + '.png'
    if not os.path.splitext(raw)[1]:
        raw += ".png"
    stem, ext = os.path.splitext(raw)
    candidate = raw
    if candidate.lower() in used:
        digest = hashlib.sha1(image.name.encode("utf-8")).hexdigest()[:8]
        candidate = f"{stem}_{digest}{ext}"
    used.add(candidate.lower())
    return candidate


def _write_packed_image(image, destination):
    copied = None
    try:
        if image.packed_file and not image.is_dirty:
            with open(destination, 'wb') as handle:
                handle.write(image.packed_file.data)
        else:
            copied = image.copy()
            copied.file_format = 'PNG'
            copied.filepath_raw = destination
            copied.save()
        return os.path.isfile(destination)
    finally:
        if copied:
            bpy.data.images.remove(copied)


class FBXZIP_OT_export(Operator, ExportHelper):
    bl_idname = "export_scene.fbx_zip"
    bl_label = "Export FBX + ZIP"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".zip"
    filter_glob: StringProperty(default="*.zip", options={"HIDDEN"})

    use_selection: BoolProperty(name="Selected Objects", default=True)
    use_visible: BoolProperty(name="Visible Objects", default=False)
    use_active_collection: BoolProperty(name="Active Collection", default=False)
    collection: StringProperty(name="Collection", default="")
    object_types: EnumProperty(
        name="Object Types",
        options={"ENUM_FLAG"},
        items=[
            ("EMPTY", "Empty", ""),
            ("CAMERA", "Camera", ""),
            ("LIGHT", "Light", ""),
            ("ARMATURE", "Armature", ""),
            ("MESH", "Mesh", ""),
            ("OTHER", "Other", ""),
        ],
        default={"ARMATURE", "MESH", "OTHER"},
    )
    global_scale: FloatProperty(name="Scale", default=1.0, min=0.001, max=1000.0)
    apply_unit_scale: BoolProperty(name="Apply Unit", default=False)
    apply_scale_options: EnumProperty(
        name="Apply Scalings",
        items=[
            ("FBX_SCALE_NONE", "All Local", ""),
            ("FBX_SCALE_UNITS", "FBX Units Scale", ""),
            ("FBX_SCALE_CUSTOM", "Custom", ""),
            ("FBX_SCALE_ALL", "FBX All", ""),
        ],
        default="FBX_SCALE_NONE",
    )
    axis_forward: EnumProperty(
        name="Forward", items=[("X", "X", ""), ("Y", "Y", ""), ("Z", "Z", ""), ("-X", "-X", ""), ("-Y", "-Y", ""), ("-Z", "-Z", "")], default="-Z"
    )
    axis_up: EnumProperty(
        name="Up", items=[("X", "X", ""), ("Y", "Y", ""), ("Z", "Z", ""), ("-X", "-X", ""), ("-Y", "-Y", ""), ("-Z", "-Z", "")], default="Y"
    )
    use_space_transform: BoolProperty(name="Use Space Transform", default=True)
    bake_space_transform: BoolProperty(name="Apply Transform", default=False)
    use_mesh_modifiers: BoolProperty(name="Apply Modifiers", default=True)
    use_mesh_modifiers_render: BoolProperty(name="Use Render Modifiers", default=False)
    mesh_smooth_type: EnumProperty(
        name="Smoothing",
        items=[("OFF", "Normals Only", ""), ("FACE", "Face", ""), ("EDGE", "Edge", "")],
        default="OFF",
    )
    colors_type: EnumProperty(
        name="Vertex Colors", items=[("NONE", "None", ""), ("SRGB", "sRGB", ""), ("LINEAR", "Linear", "")], default="SRGB"
    )
    prioritize_active_color: BoolProperty(name="Prioritize Active Color", default=False)
    use_subsurf: BoolProperty(name="Export Subdivision Surface", default=False)
    use_mesh_edges: BoolProperty(name="Loose Edges", default=False)
    use_tspace: BoolProperty(name="Tangent Space", default=False)
    use_triangles: BoolProperty(name="Triangulate", default=False)
    use_custom_props: BoolProperty(name="Custom Properties", default=False)
    add_leaf_bones: BoolProperty(name="Add Leaf Bones", default=True)
    primary_bone_axis: EnumProperty(name="Primary Bone Axis", items=[(x, x, "") for x in ("X", "Y", "Z", "-X", "-Y", "-Z")], default="Y")
    secondary_bone_axis: EnumProperty(name="Secondary Bone Axis", items=[(x, x, "") for x in ("X", "Y", "Z", "-X", "-Y", "-Z")], default="X")
    use_armature_deform_only: BoolProperty(name="Only Deform Bones", default=False)
    armature_nodetype: EnumProperty(name="Armature Node", items=[("NULL", "Null", ""), ("ROOT", "Root", ""), ("LIMBNODE", "Limb Node", "")], default="NULL")
    bake_anim: BoolProperty(name="Bake Animation", default=True)
    bake_anim_use_all_bones: BoolProperty(name="Key All Bones", default=True)
    bake_anim_use_nla_strips: BoolProperty(name="NLA Strips", default=True)
    bake_anim_use_all_actions: BoolProperty(name="All Actions", default=True)
    bake_anim_force_startend_keying: BoolProperty(name="Force Start/End Keying", default=True)
    bake_anim_step: FloatProperty(name="Sampling Rate", default=1.0, min=0.01)
    bake_anim_simplify_factor: FloatProperty(name="Simplify", default=1.0, min=0.0)
    path_mode: EnumProperty(
        name="Path Mode",
        items=[("AUTO", "Auto", ""), ("ABSOLUTE", "Absolute", ""), ("RELATIVE", "Relative", ""), ("MATCH", "Match", ""), ("STRIP", "Strip Path", ""), ("COPY", "Copy", "")],
        default="AUTO",
    )
    embed_textures: BoolProperty(name="Embed Textures", default=False)
    batch_mode: EnumProperty(name="Batch Mode", items=[("OFF", "Off", ""), ("GROUP", "Group", ""), ("SCENE", "Scene", "")], default="OFF")
    use_batch_own_dir: BoolProperty(name="Batch Own Directory", default=False)
    use_metadata: BoolProperty(name="Metadata", default=True)
    package_textures: BoolProperty(name="Collect Used Textures", default=True)
    keep_fbx: BoolProperty(name="Keep FBX in ZIP", default=True)

    def invoke(self, context, event):
        _sync_from_native(self)
        return ExportHelper.invoke(self, context, event)

    def draw(self, context):
        layout = self.layout
        row = layout.row(align=True)
        row.menu("FBXZIP_MT_presets", text=FBXZIP_MT_presets.bl_label)
        row.operator("export_scene.fbx_zip_preset_add", text="", icon="ADD")
        remove = row.operator("export_scene.fbx_zip_preset_add", text="", icon="REMOVE")
        remove.remove_active = True
        layout.operator("export_scene.fbx_zip_sync_native", icon="FILE_REFRESH")
        box = layout.box()
        box.label(text="Package")
        box.prop(self, "package_textures")
        box.prop(self, "keep_fbx")
        box = layout.box()
        box.label(text="FBX: Include / Transform")
        box.prop(self, "use_selection")
        box.prop(self, "use_visible")
        box.prop(self, "use_active_collection")
        box.prop(self, "object_types")
        box.prop(self, "global_scale")
        box.prop(self, "apply_unit_scale")
        box.prop(self, "apply_scale_options")
        box.prop(self, "axis_forward")
        box.prop(self, "axis_up")
        box.prop(self, "use_space_transform")
        box.prop(self, "bake_space_transform")
        box = layout.box()
        box.label(text="FBX: Mesh / Armature")
        for name in ("use_mesh_modifiers", "use_mesh_modifiers_render", "mesh_smooth_type", "colors_type", "prioritize_active_color", "use_subsurf", "use_mesh_edges", "use_tspace", "use_triangles", "use_custom_props", "add_leaf_bones", "primary_bone_axis", "secondary_bone_axis", "use_armature_deform_only", "armature_nodetype"):
            box.prop(self, name)
        box = layout.box()
        box.label(text="FBX: Animation")
        for name in ("bake_anim", "bake_anim_use_all_bones", "bake_anim_use_nla_strips", "bake_anim_use_all_actions", "bake_anim_force_startend_keying", "bake_anim_step", "bake_anim_simplify_factor"):
            box.prop(self, name)
        box = layout.box()
        box.label(text="FBX: Files")
        box.prop(self, "path_mode")
        box.prop(self, "embed_textures")
        box.prop(self, "batch_mode")
        box.prop(self, "use_batch_own_dir")
        box.prop(self, "use_metadata")

    def _fbx_options(self, filepath):
        names = (
            "use_selection", "use_visible", "use_active_collection", "collection", "object_types", "global_scale", "apply_unit_scale", "apply_scale_options", "axis_forward", "axis_up",
            "use_space_transform", "bake_space_transform", "use_mesh_modifiers", "use_mesh_modifiers_render", "mesh_smooth_type",
            "use_subsurf", "colors_type", "prioritize_active_color", "use_mesh_edges", "use_tspace", "use_triangles", "use_custom_props", "add_leaf_bones", "primary_bone_axis",
            "secondary_bone_axis", "use_armature_deform_only", "armature_nodetype", "bake_anim", "bake_anim_use_all_bones",
            "bake_anim_use_nla_strips", "bake_anim_use_all_actions", "bake_anim_force_startend_keying", "bake_anim_step",
            "bake_anim_simplify_factor", "path_mode", "embed_textures", "batch_mode", "use_batch_own_dir", "use_metadata",
        )
        return {name: getattr(self, name) for name in names} | {"filepath": filepath}

    def execute(self, context):
        if not self.filepath.lower().endswith(".zip"):
            self.filepath += ".zip"
        if self.batch_mode != 'OFF':
            self.report({'ERROR'}, 'ZIP 暫不支援批次匯出，請使用 Batch Mode: Off')
            return {'CANCELLED'}
        objects = _export_objects(context, self)
        if not objects:
            self.report({"ERROR"}, "沒有可輸出的物件")
            return {"CANCELLED"}
        output_zip = os.path.abspath(self.filepath)
        os.makedirs(os.path.dirname(output_zip), exist_ok=True)
        # Keep Blender's native FBX exporter defaults in sync with the settings
        # used for this package export.
        _sync_to_native(self)
        node_restore, temporary_images = [], []
        with tempfile.TemporaryDirectory(prefix="faidlix_fbxzip_") as temp_dir:
            fbx_path = os.path.join(temp_dir, os.path.splitext(os.path.basename(output_zip))[0] + ".fbx")
            try:
                nodes = _used_image_nodes(objects)
                export_images = _object_images(objects) if self.package_textures else []
                packaged = []
                if self.package_textures:
                    used = set()
                    for image in export_images:
                        name = _safe_texture_name(image, used)
                        destination = os.path.join(temp_dir, name)
                        source = bpy.path.abspath(image.filepath, library=image.library) if image.filepath else ""
                        if image.packed_file or image.source in {"GENERATED", "VIEWER"}:
                            ok = _write_packed_image(image, destination)
                        elif image.is_dirty or (not source or not os.path.isfile(source)) and image.has_data:
                            ok = _write_packed_image(image, destination)
                        elif source and os.path.isfile(source):
                            shutil.copy2(source, destination)
                            ok = True
                        else:
                            ok = False
                        if not ok:
                            raise RuntimeError(f'無法收集貼圖：{image.name}（{source or image.source}）')
                        packaged.append(destination)
                        staged = bpy.data.images.load(destination, check_existing=False)
                        staged.colorspace_settings.name = image.colorspace_settings.name
                        staged.alpha_mode = image.alpha_mode
                        temporary_images.append(staged)
                        for node in nodes:
                            if node.image == image:
                                node_restore.append((node, image))
                                node.image = staged
                options = self._fbx_options(fbx_path)
                if self.package_textures:
                    # Portable references; the original graph and image datablocks are restored.
                    options['path_mode'] = 'COPY' if self.embed_textures else 'STRIP'
                result = bpy.ops.export_scene.fbx(**options)
                if "FINISHED" not in result or not os.path.isfile(fbx_path):
                    raise RuntimeError("FBX 匯出失敗")
                temporary_zip = output_zip + '.partial'
                with zipfile.ZipFile(temporary_zip, "w", zipfile.ZIP_DEFLATED) as archive:
                    for full in ([fbx_path] if self.keep_fbx else []) + packaged:
                        archive.write(full, os.path.basename(full))
                    # Native COPY references the companion .fbm directory.
                    if self.package_textures and self.embed_textures:
                        media_dir = os.path.splitext(fbx_path)[0] + '.fbm'
                        if os.path.isdir(media_dir):
                            for directory, _, filenames in os.walk(media_dir):
                                for filename in filenames:
                                    full = os.path.join(directory, filename)
                                    archive.write(full, os.path.relpath(full, temp_dir))
                os.replace(temporary_zip, output_zip)
            except Exception as exc:
                self.report({"ERROR"}, f"FBX ZIP 匯出失敗：{exc}")
                return {"CANCELLED"}
            finally:
                for node, image in reversed(node_restore):
                    node.image = image
                for image in temporary_images:
                    bpy.data.images.remove(image)
        self.report({"INFO"}, f"已輸出：{output_zip}")
        return {"FINISHED"}


class FBXZIP_MT_presets(Menu):
    bl_idname = "FBXZIP_MT_presets"
    bl_label = "Operator Presets"
    preset_subdir = "operator/export_scene.fbx"
    preset_operator = "script.execute_preset"

    @staticmethod
    def post_cb(context, filepath):
        operator = context.active_operator
        if operator and operator.bl_idname == 'EXPORT_SCENE_OT_fbx_zip':
            _sync_to_native(operator)

    def draw(self, context):
        self.layout.operator("wm.operator_defaults")
        self.layout.separator()
        self.draw_preset(context)


class FBXZIP_OT_preset_add(AddPresetBase, Operator):
    bl_idname = 'export_scene.fbx_zip_preset_add'
    bl_label = 'Save FBX Preset'
    preset_menu = 'FBXZIP_MT_presets'
    preset_subdir = 'operator/export_scene.fbx'
    preset_defines = ['op = bpy.context.active_operator']
    preset_values = ['op.' + name for name in _SYNC_PROPERTIES]


def _preset_items(self, context):
    items = [("", "Choose Preset", "")]
    for filename in sorted(os.listdir(_preset_dir())):
        if filename.lower().endswith(".json"):
            name = os.path.splitext(filename)[0]
            items.append((name, name, ""))
    return items


class FBXZIP_OT_save_preset(Operator):
    bl_idname = "export_scene.fbx_zip_save_preset"
    bl_label = "Save FBX Preset"

    name: StringProperty(name="Preset Name", default="My FBX Preset")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        try:
            native = _native_fbx_properties()
            with open(_preset_path(self.name), "w", encoding="utf-8") as handle:
                json.dump(_preset_data(native), handle, ensure_ascii=False, indent=2)
        except Exception as exc:
            self.report({"ERROR"}, f"儲存預設集失敗：{exc}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"已儲存 FBX 預設集：{self.name}")
        return {"FINISHED"}


class FBXZIP_OT_load_preset(Operator):
    bl_idname = "export_scene.fbx_zip_load_preset"
    bl_label = "Load FBX Preset"

    preset: EnumProperty(name="Preset", items=_preset_items)

    def execute(self, context):
        if not self.preset:
            self.report({"ERROR"}, "請先選擇預設集")
            return {"CANCELLED"}
        try:
            with open(_preset_path(self.preset), "r", encoding="utf-8") as handle:
                data = json.load(handle)
            native = _native_fbx_properties()
            _apply_preset(native, data)
        except Exception as exc:
            self.report({"ERROR"}, f"載入預設集失敗：{exc}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"已載入 FBX 預設集：{self.preset}")
        return {"FINISHED"}


class FBXZIP_OT_sync_native(Operator):
    bl_idname = "export_scene.fbx_zip_sync_native"
    bl_label = "Sync FBX Defaults"

    def execute(self, context):
        operator = context.space_data.active_operator if context.area and context.area.type == 'FILE_BROWSER' else context.active_operator
        if operator and operator.bl_idname == 'EXPORT_SCENE_OT_fbx_zip':
            count = _sync_from_native(operator)
        else:
            count = len([name for name in _SYNC_PROPERTIES if hasattr(_native_fbx_properties(), name)])
        self.report({"INFO"}, f"已同步 Blender 原生 FBX 選項：{count} 項")
        return {"FINISHED"}


class FBXZIP_OT_online_update(Operator):
    bl_idname = "export_scene.fbx_zip_online_update"
    bl_label = "線上更新"
    bl_description = "從 Faidlix/BlenderAddons 檢查並安裝最新版"
    bl_options = {'INTERNAL'}

    force: BoolProperty(default=False, options={'HIDDEN'})

    def execute(self, context):
        global _UPDATE_STATUS
        context.preferences.system.use_online_access = True
        repo_index, repo = _ensure_repository(context)
        if repo is None:
            _UPDATE_STATUS = "無法建立 Faidlix Blender Add-ons 更新來源"
            self.report({'ERROR'}, _UPDATE_STATUS)
            return {'CANCELLED'}
        try:
            sync_result = bpy.ops.extensions.repo_sync(repo_index=repo_index)
        except RuntimeError as exc:
            _UPDATE_STATUS = f"GitHub 同步失敗：{exc}"
            self.report({'ERROR'}, _UPDATE_STATUS)
            return {'CANCELLED'}
        if sync_result != {'FINISHED'}:
            _UPDATE_STATUS = "GitHub 同步未完成"
            self.report({'ERROR'}, _UPDATE_STATUS)
            return {'CANCELLED'}
        latest = _latest_version(_repository_index(repo))
        if not latest:
            _UPDATE_STATUS = "共用索引中找不到 Faidlix_Fbx ZipExporter"
            self.report({'ERROR'}, _UPDATE_STATUS)
            return {'CANCELLED'}
        if latest <= ADDON_VERSION and not self.force:
            _UPDATE_STATUS = f"目前已是最新版 {'.'.join(map(str, ADDON_VERSION))}"
            bpy.ops.wm.save_userpref()
            self.report({'INFO'}, _UPDATE_STATUS)
            return {'FINISHED'}

        version_text = ".".join(map(str, latest))

        def install_after_operator_returns():
            global _UPDATE_STATUS
            try:
                result = bpy.ops.extensions.package_install(
                    repo_index=repo_index,
                    pkg_id=PACKAGE_ID,
                    enable_on_install=True,
                )
                if result != {'FINISHED'}:
                    raise RuntimeError(str(result))
                _UPDATE_STATUS = f"已安裝 {version_text}"
                bpy.ops.wm.save_userpref()
            except Exception as exc:
                _UPDATE_STATUS = f"更新失敗：{exc}"
                print(f"Faidlix_Fbx ZipExporter update failed: {exc}")
            return None

        bpy.app.timers.register(install_after_operator_returns, first_interval=0.1)
        _UPDATE_STATUS = f"已找到 {version_text}，準備從集中倉庫安裝"
        self.report({'INFO'}, _UPDATE_STATUS)
        return {'FINISHED'}


class FBXZIP_PT_panel(Panel):
    bl_label = "Faidlix_Fbx ZipExporter"
    bl_idname = "FBXZIP_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Faidlix"
    bl_order = 20
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header_preset(self, _context):
        row = self.layout.row(align=True)
        row.alignment = "RIGHT"
        row.label(text=f"v{'.'.join(map(str, ADDON_VERSION))}")

    def draw(self, context):
        layout = self.layout
        layout.operator(FBXZIP_OT_export.bl_idname, icon="EXPORT")
        layout.separator()
        layout.operator(FBXZIP_OT_online_update.bl_idname, icon="FILE_REFRESH")
        layout.label(text=f"版本 {'.'.join(map(str, ADDON_VERSION))}")
        if _UPDATE_STATUS:
            layout.label(text=_UPDATE_STATUS, icon="INFO")


classes = (FBXZIP_MT_presets, FBXZIP_OT_preset_add, FBXZIP_OT_export, FBXZIP_OT_save_preset, FBXZIP_OT_load_preset, FBXZIP_OT_sync_native, FBXZIP_OT_online_update, FBXZIP_PT_panel)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
