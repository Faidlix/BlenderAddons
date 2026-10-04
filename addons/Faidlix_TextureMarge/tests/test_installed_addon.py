import addon_utils
import bpy


URL = "https://raw.githubusercontent.com/Faidlix/BlenderAddons/main/repository/index.json"
repo = next(
    repo for repo in bpy.context.preferences.extensions.repos
    if repo.remote_url.rstrip("/") == URL.rstrip("/")
)
module_name = f"bl_ext.{repo.module}.blander_texture_marge"
assert addon_utils.check(module_name)[1]
addon = __import__(module_name, fromlist=['*'])
assert addon.ADDON_VERSION == (1, 5, 8)
assert addon.PACKAGE_ID == "blander_texture_marge"
assert addon.GITHUB_REPOSITORY_URL == URL
assert hasattr(bpy.ops.ftm, "online_update")
assert bpy.ops.ftm.online_update() == {'FINISHED'}
print("FAIDLIX_TEXTURE_MARGE_INSTALLED_TEST=PASS")
