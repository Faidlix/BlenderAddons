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
assert addon.bl_info['version'] == (1, 7, 0)
assert addon.ADDON_VERSION == (1, 7, 0)
assert addon.PACKAGE_ID == 'faidlix_fbx_zip_exporter'
assert addon.bl_info['name'] == 'Faidlix_Fbx ZipExporter'
assert addon.FBXZIP_PT_panel.bl_label == 'Faidlix_Fbx ZipExporter'
assert addon.FBXZIP_PT_panel.bl_category == 'Faidlix'
assert addon.FBXZIP_PT_panel.bl_order == 20
assert 'DEFAULT_CLOSED' in addon.FBXZIP_PT_panel.bl_options
assert hasattr(bpy.types, 'EXPORT_SCENE_OT_fbx_zip_online_update')
assert addon.REPOSITORY_URL == 'https://raw.githubusercontent.com/Faidlix/BlenderAddons/main/repository/index.json'
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
with tempfile.TemporaryDirectory(prefix='fbxzip_smoke_') as folder:
    package = Path(folder)/'smoke.zip'
    result = bpy.ops.export_scene.fbx_zip(filepath=str(package), use_selection=True, bake_anim=False)
    assert result == {'FINISHED'}, result
    with zipfile.ZipFile(package) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == {'smoke.fbx', 'UsedGenerated.png'}, archive.namelist()
    assert tex.image == used and obj.active_material == material
report = {'result':'PASS','version':list(addon.bl_info['version']),'module':addon.__file__,'panel':addon.FBXZIP_PT_panel.bl_label,'category':'Faidlix','generated_texture':'PASS','dead_branch_excluded':'PASS','original_material_restored':'PASS'}
output = root/'validation-output'
output.mkdir(exist_ok=True)
(output/'smoke.json').write_text(json.dumps(report, indent=2), encoding='utf8')
print('FBXZIP_SMOKE_PASS', json.dumps(report))
addon.unregister()
