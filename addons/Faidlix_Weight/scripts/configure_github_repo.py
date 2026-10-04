import os

import addon_utils
import bpy


REPOSITORY_NAME = "Faidlix Blender Add-ons"
REPOSITORY_URL = (
    "https://raw.githubusercontent.com/"
    "Faidlix/BlenderAddons/main/repository/index.json"
)
PACKAGE_ID = "faidlix_weight"


def find_target_repo():
    for index, repo in enumerate(bpy.context.preferences.extensions.repos):
        if repo.remote_url.rstrip("/") == REPOSITORY_URL.rstrip("/"):
            return index, repo
    return None, None


def package_directory(repo):
    return os.path.join(repo.directory, PACKAGE_ID)


bpy.context.preferences.system.use_online_access = True

index, target_repo = find_target_repo()
if target_repo is None:
    result = bpy.ops.preferences.extension_repo_add(
        name=REPOSITORY_NAME,
        remote_url=REPOSITORY_URL,
        use_sync_on_startup=True,
        type='REMOTE',
    )
    assert result == {'FINISHED'}, result
    index, target_repo = find_target_repo()
    assert target_repo is not None
else:
    target_repo.enabled = True
    target_repo.use_sync_on_startup = True

sync_result = bpy.ops.extensions.repo_sync(repo_index=index)
assert sync_result == {'FINISHED'}, sync_result

# Migrate away from copies installed from another repository. Keeping two
# enabled packages with the same operators would make the test meaningless.
for old_index in reversed(range(len(bpy.context.preferences.extensions.repos))):
    old_repo = bpy.context.preferences.extensions.repos[old_index]
    if old_repo.module == target_repo.module:
        continue
    old_module = f"bl_ext.{old_repo.module}.{PACKAGE_ID}"
    _default, enabled = addon_utils.check(old_module)
    if enabled:
        bpy.ops.preferences.addon_disable(module=old_module)
    if os.path.isdir(package_directory(old_repo)):
        result = bpy.ops.extensions.package_uninstall(
            repo_index=old_index,
            pkg_id=PACKAGE_ID,
        )
        assert result == {'FINISHED'}, (old_repo.name, result)

module_name = f"bl_ext.{target_repo.module}.{PACKAGE_ID}"
_default, enabled = addon_utils.check(module_name)
installed = os.path.isdir(package_directory(target_repo))
if installed and enabled:
    bpy.ops.preferences.addon_disable(module=module_name)
if installed:
    result = bpy.ops.extensions.package_uninstall(
        repo_index=index,
        pkg_id=PACKAGE_ID,
    )
    assert result == {'FINISHED'}, result

install_result = bpy.ops.extensions.package_install(
    repo_index=index,
    pkg_id=PACKAGE_ID,
    enable_on_install=True,
)
assert install_result == {'FINISHED'}, install_result

bpy.ops.wm.save_userpref()

_default, enabled = addon_utils.check(module_name)
assert enabled
assert os.path.isdir(package_directory(target_repo))

print(f"FAIDLIX_REPOSITORY={target_repo.remote_url}")
print(f"FAIDLIX_REPOSITORY_MODULE={target_repo.module}")
print(f"FAIDLIX_PACKAGE_MODULE={module_name}")
print("FAIDLIX_GITHUB_INSTALL=PASS")
