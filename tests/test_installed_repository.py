import addon_utils
import bpy


URL = "https://raw.githubusercontent.com/Faidlix/BlenderAddons/main/repository/index.json"
repo = next(repo for repo in bpy.context.preferences.extensions.repos
            if repo.remote_url.rstrip("/") == URL.rstrip("/"))

paint_name = f"bl_ext.{repo.module}.faidlix_paint"
preference_name = f"bl_ext.{repo.module}.blander_peferance"
bone_remap_name = f"bl_ext.{repo.module}.faidlix_bone_remap"
outliner_name = f"bl_ext.{repo.module}.faidlix_outliner"
weight_name = f"bl_ext.{repo.module}.faidlix_weight"
manager_name = f"bl_ext.{repo.module}.faidlix_manager"
fbx_zip_name = f"bl_ext.{repo.module}.faidlix_fbx_zip_exporter"
texture_marge_name = f"bl_ext.{repo.module}.blander_texture_marge"
assert addon_utils.check(paint_name)[1]
assert addon_utils.check(preference_name)[1]
assert addon_utils.check(bone_remap_name)[1]
assert addon_utils.check(outliner_name)[1]
assert addon_utils.check(weight_name)[1]
assert addon_utils.check(manager_name)[1]
assert addon_utils.check(fbx_zip_name)[1]
assert addon_utils.check(texture_marge_name)[1]

paint = __import__(paint_name, fromlist=['*'])
preference = __import__(preference_name, fromlist=['*'])
bone_remap = __import__(bone_remap_name, fromlist=['*'])
outliner = __import__(outliner_name, fromlist=['*'])
weight = __import__(weight_name, fromlist=['*'])
manager = __import__(manager_name, fromlist=['*'])
fbx_zip = __import__(fbx_zip_name, fromlist=['*'])
texture_marge = __import__(texture_marge_name, fromlist=['*'])
assert paint.ADDON_VERSION == (0, 4, 8)
assert preference.ADDON_VERSION == (1, 1, 0)
assert paint.GITHUB_REPOSITORY_URL == URL
assert bone_remap.bl_info["version"] == (0, 6, 3)
assert bone_remap.updater.GITHUB_REPOSITORY_URL == URL
assert outliner.ADDON_VERSION == (0, 2, 15)
assert outliner.GITHUB_REPOSITORY_URL == URL
assert weight.ADDON_VERSION == (1, 3, 0)
assert weight.GITHUB_REPOSITORY_URL == URL
assert manager.ADDON_VERSION == (1, 1, 3)
assert manager.REPOSITORY_URL == URL
assert fbx_zip.ADDON_VERSION == (1, 7, 2)
assert fbx_zip.PACKAGE_ID == "faidlix_fbx_zip_exporter"
assert fbx_zip.REPOSITORY_URL == URL
assert texture_marge.ADDON_VERSION == (1, 5, 8)
assert texture_marge.GITHUB_REPOSITORY_URL == URL
assert hasattr(bpy.ops.faidlix_paint, "online_update")
assert hasattr(bpy.ops.fbr, "online_update")
assert hasattr(bpy.ops.faidlix_outliner, "online_update")
assert hasattr(bpy.ops.faidlix_weight, "online_update")
assert hasattr(bpy.ops.faidlix_manager, "update_all")
assert hasattr(bpy.ops.export_scene, "fbx_zip_online_update")
assert hasattr(bpy.ops.ftm, "online_update")
assert bpy.ops.faidlix_paint.online_update() == {'FINISHED'}
assert bpy.ops.faidlix_outliner.online_update() == {'FINISHED'}
assert bpy.ops.faidlix_weight.online_update() == {'FINISHED'}
assert bpy.ops.export_scene.fbx_zip_online_update() == {'FINISHED'}
assert bpy.ops.ftm.online_update() == {'FINISHED'}
assert bpy.ops.faidlix_weight.online_update() == {'FINISHED'}
assert bpy.ops.faidlix_manager.update_all() == {'FINISHED'}
print("FAIDLIX_CENTRAL_INSTALLED_TEST=PASS")
