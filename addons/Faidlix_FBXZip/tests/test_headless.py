"""Run in Blender --background --factory-startup --python tests/smoke_blender.py.

FBXZIP_ADDON_PARENT can point to a downloaded/installed add-on's parent directory.
"""
import bpy
import importlib
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root.parent))
addon = importlib.import_module('Faidlix_FBXZip')
addon.register()
assert addon.bl_info['version'] == (1, 8, 0)
assert addon.ADDON_VERSION == (1, 8, 0)
assert addon.PACKAGE_ID == 'faidlix_fbx_zip_exporter'
assert addon.bl_info['name'] == 'Faidlix_Fbx ZipExporter'
assert addon.FBXZIP_PT_panel.bl_label == 'Faidlix_Fbx ZipExporter'
assert hasattr(addon.FBXZIP_PT_panel, 'draw_header_preset')
assert addon.FBXZIP_PT_panel.bl_category == 'Faidlix'
assert addon.FBXZIP_PT_panel.bl_order == 20
assert 'DEFAULT_CLOSED' in addon.FBXZIP_PT_panel.bl_options
assert hasattr(bpy.types, 'EXPORT_SCENE_OT_fbx_zip_online_update')
assert addon.REPOSITORY_URL == 'https://raw.githubusercontent.com/Faidlix/BlenderAddons/main/repository/index.json'


class _PanelLayoutProbe:
    def __init__(self):
        self.labels = []
        self.operators = []

    def row(self, **_kwargs):
        return self

    def operator(self, operator_id, **kwargs):
        self.operators.append((operator_id, kwargs.get('text', '')))
        return type('_OperatorProbe', (), {})()

    def separator(self):
        return None

    def label(self, *, text='', **_kwargs):
        self.labels.append(text)


panel_probe = type('_PanelProbe', (), {'layout': _PanelLayoutProbe()})()
legacy_info = addon.bl_info
del addon.bl_info
try:
    addon.FBXZIP_PT_panel.draw(panel_probe, bpy.context)
finally:
    addon.bl_info = legacy_info
assert panel_probe.layout.labels == []
assert panel_probe.layout.operators == [
    ('export_scene.fbx_zip', 'Export FBX + ZIP'),
    ('export_scene.fbx_zip_online_update', '線上更新'),
]

bpy.ops.mesh.primitive_cube_add()
obj = bpy.context.object
material = bpy.data.materials.new('ExportSmoke')
material.use_nodes = True
obj.data.materials.append(material)
tree = material.node_tree
bsdf = next(n for n in tree.nodes if n.type == 'BSDF_PRINCIPLED')
used = bpy.data.images.new('UsedGenerated', width=32, height=32)
tex = tree.nodes.new('ShaderNodeTexImage'); tex.image = used
tree.links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
unused = bpy.data.images.new('UnusedGenerated', width=32, height=32)
dead = tree.nodes.new('ShaderNodeTexImage'); dead.image = unused
math = tree.nodes.new('ShaderNodeMath')
tree.links.new(dead.outputs['Color'], math.inputs[0])
assert addon._object_images([obj]) == [used]
assert addon._all_material_images([obj]) == [used, unused]
assert addon._safe_output_name('Renamed.jpg', 'Original.png') == 'Renamed.png'
with tempfile.TemporaryDirectory(prefix='fbxzip_smoke_') as folder:
    package = Path(folder)/'smoke.zip'
    result = bpy.ops.export_scene.fbx_zip(filepath=str(package), use_selection=True, bake_anim=False)
    assert result == {'FINISHED'}, result
    with zipfile.ZipFile(package) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == {'smoke.fbx', 'UsedGenerated.png'}, archive.namelist()
    assert tex.image == used and obj.active_material == material

    addon._refresh_texture_items(bpy.context.window_manager, [obj], include_all=False, preserve=False)
    texture_item = bpy.context.window_manager.fbxzip_texture_items[0]
    texture_item.output_name = 'Unity_BaseColor.png'
    renamed_package = Path(folder)/'renamed.zip'
    result = bpy.ops.export_scene.fbx_zip(filepath=str(renamed_package), use_selection=True, bake_anim=False)
    assert result == {'FINISHED'}, result
    with zipfile.ZipFile(renamed_package) as archive:
        assert set(archive.namelist()) == {'renamed.fbx', 'Unity_BaseColor.png'}
        fbx_bytes = archive.read('renamed.fbx')
        assert b'Unity_BaseColor.png' in fbx_bytes

    addon._refresh_texture_items(bpy.context.window_manager, [obj], include_all=True, preserve=False)
    all_package = Path(folder)/'all_textures.zip'
    result = bpy.ops.export_scene.fbx_zip(
        filepath=str(all_package), use_selection=True, bake_anim=False, package_all_textures=True
    )
    assert result == {'FINISHED'}, result
    with zipfile.ZipFile(all_package) as archive:
        assert set(archive.namelist()) == {'all_textures.fbx', 'UsedGenerated.png', 'UnusedGenerated.png'}

    unused.filepath = '//Left/Duplicate.png'
    duplicate = bpy.data.images.new('DuplicateGenerated', width=64, height=16)
    duplicate.filepath = '//Right/Duplicate.png'
    duplicate_node = tree.nodes.new('ShaderNodeTexImage'); duplicate_node.image = duplicate
    addon._refresh_texture_items(bpy.context.window_manager, [obj], include_all=True, preserve=False)
    conflicts = addon._texture_conflicts(bpy.context.window_manager.fbxzip_texture_items)
    assert len(conflicts) == 1 and {item.image_name for item in conflicts[0]} == {unused.name, duplicate.name}
    conflicts[0][1].include = False
    assert addon._texture_conflicts(bpy.context.window_manager.fbxzip_texture_items) == []

armature_data = bpy.data.armatures.new('ActionRigData')
armature = bpy.data.objects.new('ActionRig', armature_data)
bpy.context.scene.collection.objects.link(armature)
bpy.context.view_layer.objects.active = armature
obj.select_set(False)
armature.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
edit_bone = armature_data.edit_bones.new('Bone')
edit_bone.head = (0.0, 0.0, 0.0)
edit_bone.tail = (0.0, 0.0, 1.0)
bpy.ops.object.mode_set(mode='POSE')
pose_bone = armature.pose.bones['Bone']
actions = []
for name, value in [('Fairy_Idle', 0.25), ('Fairy_Run', 1.0)]:
    if armature.animation_data:
        armature.animation_data.action = None
    pose_bone.location.x = 0.0
    pose_bone.keyframe_insert(data_path='location', index=0, frame=1)
    pose_bone.location.x = value
    pose_bone.keyframe_insert(data_path='location', index=0, frame=12)
    action = armature.animation_data.action
    action.name = name
    actions.append(action)
original_action = actions[0]
armature.animation_data.action = original_action
bpy.ops.object.mode_set(mode='OBJECT')
existing_track = armature.animation_data.nla_tracks.new()
existing_track.name = 'ExistingTrack'
existing_track.strips.new('ExistingStrip', 1, actions[1])
existing_track.mute = False
addon._refresh_action_items(bpy.context.window_manager, [armature], preserve=False)
assert {item.action_name for item in bpy.context.window_manager.fbxzip_action_items} == {'Fairy_Idle', 'Fairy_Run'}
for item in bpy.context.window_manager.fbxzip_action_items:
    item.include = item.action_name == 'Fairy_Idle'
    if item.include:
        item.export_name = 'Fairy_Idle'
with tempfile.TemporaryDirectory(prefix='fbxzip_action_') as folder:
    package = Path(folder)/'actions.zip'
    result = bpy.ops.export_scene.fbx_zip(
        filepath=str(package),
        use_selection=True,
        object_types={'ARMATURE'},
        package_textures=False,
        bake_anim=True,
        select_actions=True,
    )
    assert result == {'FINISHED'}, result
    with zipfile.ZipFile(package) as archive:
        fbx_bytes = archive.read('actions.fbx')
        assert b'Fairy_Idle' in fbx_bytes
        assert b'ActionRig|Fairy_Idle' not in fbx_bytes
        assert b'Fairy_Run' not in fbx_bytes
assert armature.animation_data.action == original_action
assert len(armature.animation_data.nla_tracks) == 1
assert armature.animation_data.nla_tracks[0].name == 'ExistingTrack'
assert armature.animation_data.nla_tracks[0].mute is False

for item in bpy.context.window_manager.fbxzip_action_items:
    item.include = True
    item.export_name = 'Duplicate'
assert addon._action_conflicts(bpy.context.window_manager.fbxzip_action_items)
addon._dedupe_action_names(bpy.context.window_manager.fbxzip_action_items)
assert [item.export_name for item in bpy.context.window_manager.fbxzip_action_items] == ['Duplicate', 'Duplicate_001']

report = {'result':'PASS','version':list(addon.bl_info['version']),'module':addon.__file__,'panel':addon.FBXZIP_PT_panel.bl_label,'category':'Faidlix','generated_texture':'PASS','dead_branch_excluded':'PASS','all_material_textures':'PASS','renamed_fbx_reference':'PASS','selected_action_only':'PASS','unity_clip_action_name':'PASS','state_restored':'PASS'}
output = root/'validation-output'
output.mkdir(exist_ok=True)
(output/'smoke.json').write_text(json.dumps(report, indent=2), encoding='utf8')
print('FBXZIP_SMOKE_PASS', json.dumps(report))
addon.unregister()
