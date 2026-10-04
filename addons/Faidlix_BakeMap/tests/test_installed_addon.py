import importlib
import os

import addon_utils
import bpy


REPOSITORY_URL = (
    "https://raw.githubusercontent.com/"
    "Faidlix/BlenderAddons/main/repository/index.json"
)
PACKAGE_ID = "faidlix_bakemap"


repo = next(
    repo
    for repo in bpy.context.preferences.extensions.repos
    if repo.remote_url.split('?', 1)[0].rstrip("/") == REPOSITORY_URL.rstrip("/")
)
addon_module = f"bl_ext.{repo.module}.{PACKAGE_ID}"
_default, enabled = addon_utils.check(addon_module)
assert enabled, addon_module

addon = importlib.import_module(addon_module)
assert addon.ADDON_VERSION == (2, 3, 11)
assert addon.GITHUB_REPOSITORY_URL == REPOSITORY_URL
assert hasattr(bpy.types.Scene, "faidlix_bakemap")
assert hasattr(bpy.types, "FAIDLIX_OT_online_update")
assert not hasattr(bpy.types, "FAIDLIX_PT_bakemap_updates")
assert 'DEFAULT_CLOSED' in addon.FAIDLIX_PT_bakemap.bl_options
assert not hasattr(addon, "_schedule_updated_addon_reload")
found_index, found_repo = addon._github_update_repo()
assert found_index >= 0
assert found_repo.module == repo.module
assert found_repo.directory == repo.directory
assert os.path.isfile(os.path.join(repo.directory, PACKAGE_ID, "blender_manifest.toml"))
assert bpy.ops.faidlix.online_update() == {'FINISHED'}
assert bpy.context.scene.faidlix_bakemap.update_status == "已是最新版"

print("FAIDLIX_BAKEMAP_INSTALLED_TEST=PASS")
print(f"INSTALLED_MODULE={addon_module}")
print("ONLINE_UPDATE_OPERATOR=True")
print("ONLINE_UPDATE_CHECK=True")
