import addon_utils
import bpy


URL = "https://raw.githubusercontent.com/Faidlix/BlenderAddons/main/repository/index.json"
repo = next(repo for repo in bpy.context.preferences.extensions.repos
            if repo.remote_url.rstrip("/") == URL.rstrip("/"))

paint_name = f"bl_ext.{repo.module}.faidlix_paint"
outliner_name = f"bl_ext.{repo.module}.faidlix_outliner"
manager_name = f"bl_ext.{repo.module}.faidlix_manager"
assert addon_utils.check(paint_name)[1]
assert addon_utils.check(outliner_name)[1]
assert addon_utils.check(manager_name)[1]

paint = __import__(paint_name, fromlist=['*'])
outliner = __import__(outliner_name, fromlist=['*'])
manager = __import__(manager_name, fromlist=['*'])
assert paint.ADDON_VERSION == (0, 4, 8)
assert paint.GITHUB_REPOSITORY_URL == URL
assert outliner.ADDON_VERSION == (0, 2, 14)
assert outliner.GITHUB_REPOSITORY_URL == URL
assert manager.ADDON_VERSION == (1, 0, 1)
assert manager.REPOSITORY_URL == URL
assert hasattr(bpy.ops.faidlix_paint, "online_update")
assert hasattr(bpy.ops.faidlix_outliner, "online_update")
assert hasattr(bpy.ops.faidlix_manager, "update_all")
assert bpy.ops.faidlix_paint.online_update() == {'FINISHED'}
assert bpy.ops.faidlix_outliner.online_update() == {'FINISHED'}
assert bpy.ops.faidlix_manager.update_all() == {'FINISHED'}
print("FAIDLIX_CENTRAL_INSTALLED_TEST=PASS")
