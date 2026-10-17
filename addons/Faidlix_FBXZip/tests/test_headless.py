"""Run in Blender --background --factory-startup --python tests/test_headless.py.

FBXZIP_ADDON_PARENT and FBXZIP_ADDON_MODULE select a downloaded/installed add-on.
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
addon_parent = os.environ.get('FBXZIP_ADDON_PARENT', str(root.parent))
addon_module = os.environ.get('FBXZIP_ADDON_MODULE', 'Faidlix_FBXZip')
sys.path.insert(0, addon_parent)
addon = importlib.import_module(addon_module)
addon.register()
assert getattr(addon,'bl_info',{'version':addon.ADDON_VERSION})['version'] == (1, 8, 10)
assert addon.ADDON_VERSION == (1, 8, 10)
assert addon.PACKAGE_ID == 'faidlix_fbx_zip_exporter'
assert getattr(addon,'bl_info',{'name':addon.FBXZIP_PT_panel.bl_label})['name'] == 'Faidlix_Fbx ZipExporter'
assert addon.FBXZIP_PT_panel.bl_label == 'Faidlix_Fbx ZipExporter'
assert hasattr(addon.FBXZIP_PT_panel, 'draw_header_preset')
assert addon.FBXZIP_PT_panel.bl_category == 'Faidlix'
assert addon.FBXZIP_PT_panel.bl_order == 20
assert 'DEFAULT_CLOSED' in addon.FBXZIP_PT_panel.bl_options
action_properties = addon.FBXZIP_PG_action_item.bl_rna.properties
assert 'unity_loop_time' not in action_properties
assert action_properties['unity_loop_pose'].default is False
assert hasattr(bpy.types, 'EXPORT_SCENE_OT_fbx_zip_online_update')
assert addon.REPOSITORY_URL == 'https://raw.githubusercontent.com/Faidlix/BlenderAddons/main/repository/index.json'
assert addon._normalized_url(addon._fresh_repository_url()) == addon._normalized_url(addon.REPOSITORY_URL)


class _ProgressWindowManagerProbe:
    def __init__(self):
        self.events = []

    def progress_begin(self, minimum, maximum):
        self.events.append(('begin', minimum, maximum))

    def progress_update(self, value):
        self.events.append(('update', value))

    def progress_end(self):
        self.events.append(('end',))


class _ProgressWorkspaceProbe:
    def __init__(self):
        self.texts = []

    def status_text_set(self, text):
        self.texts.append(text)


progress_wm = _ProgressWindowManagerProbe()
progress_workspace = _ProgressWorkspaceProbe()
progress_context = type(
    '_ProgressContextProbe', (),
    {'window_manager': progress_wm, 'workspace': progress_workspace},
)()
progress = addon._ExportProgress(progress_context)
progress.begin('準備')
progress.update(42, '輸出 FBX')
progress.end()
assert progress_wm.events == [
    ('begin', 0, 100), ('update', 0), ('update', 42), ('end',),
]
assert progress_workspace.texts == [
    'Faidlix FBX ZIP：準備  0%', 'Faidlix FBX ZIP：輸出 FBX  42%', None,
]


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
legacy_info = getattr(addon,'bl_info',None)
if legacy_info is not None: del addon.bl_info
try:
    addon.FBXZIP_PT_panel.draw(panel_probe, bpy.context)
finally:
    if legacy_info is not None: addon.bl_info = legacy_info
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

    addon._refresh_material_items(bpy.context.window_manager, [obj], preserve=False)
    assert len(bpy.context.window_manager.fbxzip_material_items) == 1
    material_item = bpy.context.window_manager.fbxzip_material_items[0]
    assert material_item.material == material
    assert material_item.default_name == 'ExportSmoke'
    material_item.output_name = 'Unity_Character_Material'
    assert material.name == 'Unity_Character_Material'
    material_package = Path(folder)/'material_renamed.zip'
    result = bpy.ops.export_scene.fbx_zip(filepath=str(material_package), use_selection=True, bake_anim=False)
    assert result == {'FINISHED'}, result
    with zipfile.ZipFile(material_package) as archive:
        assert b'Unity_Character_Material' in archive.read('material_renamed.fbx')
    bpy.ops.export_scene.fbx_zip_material_names_reset()
    assert material.name == 'ExportSmoke'

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
actions[0][addon.ACTION_LOOP_KEY] = True
actions[0].use_cyclic = True
actions[1][addon.ACTION_LOOP_KEY] = False
actions[1].use_cyclic = False
armature.animation_data.action = original_action
bpy.ops.object.mode_set(mode='OBJECT')
existing_track = armature.animation_data.nla_tracks.new()
existing_track.name = 'ExistingTrack'
existing_track.strips.new('Fairy_Run', 1, actions[1])
existing_track.mute = False
# A valid slot-owned Action must remain selectable even when the rig no longer
# contains every animated bone.
run_channelbag = actions[1].layers[0].strips[0].channelbags[0]
run_channelbag.fcurves.new('pose.bones["RemovedBone"].location', index=0)
addon._refresh_action_items(bpy.context.window_manager, [armature], preserve=False)
assert {item.action_name for item in bpy.context.window_manager.fbxzip_action_items} == {'Fairy_Idle', 'Fairy_Run'}
assert {item.action_name: item.unity_loop_pose for item in bpy.context.window_manager.fbxzip_action_items} == {
    'Fairy_Idle': True,
    'Fairy_Run': False,
}
accessory_data = bpy.data.armatures.new('AccessoryRigData')
accessory = bpy.data.objects.new('AccessoryRig', accessory_data)
bpy.context.scene.collection.objects.link(accessory)
accessory_slot = actions[1].slots.new('OBJECT', 'AccessoryRig')
actions[1].layers[0].strips[0].channelbags.new(accessory_slot)
addon._refresh_action_items(bpy.context.window_manager, [armature, accessory], preserve=False)
run_rows = [item for item in bpy.context.window_manager.fbxzip_action_items if item.action_name == 'Fairy_Run']
assert {(item.object_name, item.slot_identifier) for item in run_rows} == {
    ('ActionRig', actions[1].slots[0].identifier),
    ('AccessoryRig', accessory_slot.identifier),
}
run_rows[0].unity_loop_pose = True
assert actions[1][addon.ACTION_LOOP_KEY] is True and actions[1].use_cyclic is True
assert all(item.unity_loop_pose for item in run_rows)
run_rows[1].unity_loop_pose = False
assert actions[1][addon.ACTION_LOOP_KEY] is False and actions[1].use_cyclic is False
assert not any(item.unity_loop_pose for item in run_rows)
for item in bpy.context.window_manager.fbxzip_action_items:
    item.include = item.action_name == 'Fairy_Run'
addon._refresh_action_items(bpy.context.window_manager, [armature], preserve=False)
assert {item.action_name: item.unity_loop_pose for item in bpy.context.window_manager.fbxzip_action_items} == {
    'Fairy_Idle': True,
    'Fairy_Run': False,
}
for item in bpy.context.window_manager.fbxzip_action_items:
    item.include = True
    item.export_name = item.action_name
    item.unity_loop_pose = item.action_name == 'Fairy_Run'
with tempfile.TemporaryDirectory(prefix='fbxzip_action_') as folder:
    package = Path(folder)/'actions_all.zip'
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
        fbx_bytes = archive.read('actions_all.fbx')
        unity_meta = archive.read('actions_all.fbx.meta').decode('utf8')
        unity_validation = root/'validation-output'/'unity-import'/'Assets'
        unity_validation.mkdir(parents=True, exist_ok=True)
        (unity_validation/'actions_all.fbx').write_bytes(fbx_bytes)
        (unity_validation/'actions_all.fbx.meta').write_text(unity_meta, encoding='utf8')
        assert b'Fairy_Idle' in fbx_bytes
        assert b'Fairy_Run' in fbx_bytes
        assert b'ActionRig|Fairy_Idle' not in fbx_bytes
        assert b'ActionRig|Fairy_Run' not in fbx_bytes
        assert 'name: "Fairy_Idle"' in unity_meta
        assert 'name: "Fairy_Run"' in unity_meta
        idle_meta = unity_meta.split('name: "Fairy_Idle"', 1)[1].split('name: "Fairy_Run"', 1)[0]
        run_meta = unity_meta.split('name: "Fairy_Run"', 1)[1]
        assert 'loopTime: 0' in idle_meta and 'loopBlend: 0' in idle_meta
        assert 'loopTime: 1' in run_meta and 'loopBlend: 1' in run_meta
    for item in bpy.context.window_manager.fbxzip_action_items:
        item.include = item.action_name == 'Fairy_Idle'
    selected_package = Path(folder)/'actions_selected.zip'
    result = bpy.ops.export_scene.fbx_zip(
        filepath=str(selected_package),
        use_selection=True,
        object_types={'ARMATURE'},
        package_textures=False,
        bake_anim=True,
        select_actions=True,
    )
    assert result == {'FINISHED'}, result
    with zipfile.ZipFile(selected_package) as archive:
        fbx_bytes = archive.read('actions_selected.fbx')
        unity_meta = archive.read('actions_selected.fbx.meta').decode('utf8')
        assert b'Fairy_Idle' in fbx_bytes
        assert b'Fairy_Run' not in fbx_bytes
        assert 'name: "Fairy_Idle"' in unity_meta
        assert 'name: "Fairy_Run"' not in unity_meta
    no_unity_package = Path(folder)/'actions_without_unity.zip'
    result = bpy.ops.export_scene.fbx_zip(
        filepath=str(no_unity_package),
        use_selection=True,
        object_types={'ARMATURE'},
        package_textures=False,
        bake_anim=True,
        select_actions=True,
        unity_settings=False,
    )
    assert result == {'FINISHED'}, result
    with zipfile.ZipFile(no_unity_package) as archive:
        assert 'actions_without_unity.fbx.meta' not in archive.namelist()
    actions[0][addon.ACTION_LOOP_KEY]=True
    actions[0].use_cyclic=True
    actions[1][addon.ACTION_LOOP_KEY]=False
    copied=actions[0].copy(); copied.name='Fairy_Idle_Copy'; copied.use_fake_user=True
    addon._refresh_action_items(bpy.context.window_manager,[armature],preserve=False)
    items=bpy.context.window_manager.fbxzip_action_items
    assert len(items)==3
    assert {i.action_name:i.unity_loop_pose for i in items}=={'Fairy_Idle':True,'Fairy_Idle_Copy':True,'Fairy_Run':False}
    for i in items: i.include=True; i.unity_loop_pose=not i.unity_loop_pose
    assert actions[0][addon.ACTION_LOOP_KEY] is False and actions[0].use_cyclic is False
    assert copied[addon.ACTION_LOOP_KEY] is False and copied.use_cyclic is False
    assert actions[1][addon.ACTION_LOOP_KEY] is True and actions[1].use_cyclic is True
    addon._refresh_action_items(bpy.context.window_manager,[armature],preserve=True)
    assert {i.action_name:i.unity_loop_pose for i in bpy.context.window_manager.fbxzip_action_items}=={'Fairy_Idle':False,'Fairy_Idle_Copy':False,'Fairy_Run':True}
    tagged_package=Path(folder)/'actions_tagged.zip'
    assert bpy.ops.export_scene.fbx_zip(filepath=str(tagged_package),use_selection=True,object_types={'ARMATURE'},package_textures=False,bake_anim=True,select_actions=True)=={'FINISHED'}
    with zipfile.ZipFile(tagged_package) as archive:
        meta=archive.read('actions_tagged.fbx.meta').decode('utf8')
        for name,value in [('Fairy_Idle',0),('Fairy_Idle_Copy',0),('Fairy_Run',1)]:
            block=meta.split('name: "'+name+'"',1)[1].split('    - serializedVersion:',1)[0]
            assert f'loopTime: {value}' in block and f'loopBlend: {value}' in block,block
    bpy.data.actions.remove(copied)
    for action in actions:
        del action[addon.ACTION_LOOP_KEY]; action.use_cyclic=False
    addon._refresh_action_items(bpy.context.window_manager,[armature],preserve=False)
assert armature.animation_data.action == original_action
assert len(armature.animation_data.nla_tracks) == 1
assert armature.animation_data.nla_tracks[0].name == 'ExistingTrack'
assert armature.animation_data.nla_tracks[0].mute is False
assert armature.animation_data.nla_tracks[0].strips[0].name == 'Fairy_Run'

for item in bpy.context.window_manager.fbxzip_action_items:
    item.include = True
    item.export_name = 'Duplicate'
assert addon._action_conflicts(bpy.context.window_manager.fbxzip_action_items)
addon._dedupe_action_names(bpy.context.window_manager.fbxzip_action_items)
assert [item.export_name for item in bpy.context.window_manager.fbxzip_action_items] == ['Duplicate', 'Duplicate_001']

report = {'result':'PASS','version':list(addon.ADDON_VERSION),'module':addon.__file__,'panel':addon.FBXZIP_PT_panel.bl_label,'category':'Faidlix','generated_texture':'PASS','dead_branch_excluded':'PASS','all_material_textures':'PASS','renamed_fbx_reference':'PASS','selected_action_only':'PASS','unity_clip_action_name':'PASS','unity_loop_settings':'PASS','action_editor_loop_tags':'PASS','unity_settings_optional':'PASS','state_restored':'PASS'}
output = root/'validation-output'
output.mkdir(exist_ok=True)
(output/'smoke.json').write_text(json.dumps(report, indent=2), encoding='utf8')
print('FBXZIP_SMOKE_PASS', json.dumps(report))
addon.unregister()
