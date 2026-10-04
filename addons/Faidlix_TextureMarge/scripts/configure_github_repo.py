import os

import addon_utils
import bpy


REPOSITORY_NAME = "Faidlix Blender Add-ons"
REPOSITORY_URL = (
    "https://raw.githubusercontent.com/"
    "Faidlix/BlenderAddons/main/repository/index.json"
)
PACKAGE_ID = "blander_texture_marge"


def find_repo():
    for index, repo in enumerate(bpy.context.preferences.extensions.repos):
        if repo.remote_url.rstrip("/") == REPOSITORY_URL.rstrip("/"):
            return index, repo
    return None, None


bpy.context.preferences.system.use_online_access = True
index, repo = find_repo()
if repo is None:
    result = bpy.ops.preferences.extension_repo_add(
        name=REPOSITORY_NAME,
        remote_url=REPOSITORY_URL,
        use_sync_on_startup=True,
        type='REMOTE',
    )
    assert result == {'FINISHED'}, result
    index, repo = find_repo()
else:
    repo.enabled = True
    repo.use_sync_on_startup = True
assert repo is not None
assert bpy.ops.extensions.repo_sync(repo_index=index) == {'FINISHED'}

module_name = f"bl_ext.{repo.module}.{PACKAGE_ID}"
package_dir = os.path.join(repo.directory, PACKAGE_ID)
if addon_utils.check(module_name)[1]:
    bpy.ops.preferences.addon_disable(module=module_name)
if os.path.isdir(package_dir):
    assert bpy.ops.extensions.package_uninstall(
        repo_index=index, pkg_id=PACKAGE_ID) == {'FINISHED'}
assert bpy.ops.extensions.package_install(
    repo_index=index, pkg_id=PACKAGE_ID, enable_on_install=True) == {'FINISHED'}
bpy.ops.wm.save_userpref()
assert addon_utils.check(module_name)[1]
print(f"FAIDLIX_TEXTURE_MARGE_REPOSITORY={repo.remote_url}")
print(f"FAIDLIX_TEXTURE_MARGE_MODULE={module_name}")
print("FAIDLIX_TEXTURE_MARGE_GITHUB_INSTALL=PASS")
