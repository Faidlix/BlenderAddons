import os

import addon_utils
import bpy


repository_url = os.environ["FAIDLIX_TEST_REPO_URL"]
old_module = "bl_ext.user_default.faidlix_outliner"
bpy.context.preferences.system.use_online_access = True
_default, old_enabled = addon_utils.check(old_module)
assert old_enabled, old_module

result = bpy.ops.preferences.extension_repo_add(
    name="Faidlix Outliner Duplicate Test",
    remote_url=repository_url,
    use_sync_on_startup=False,
    type="REMOTE",
)
assert result == {"FINISHED"}, result
repo_index = len(bpy.context.preferences.extensions.repos) - 1
repo = bpy.context.preferences.extensions.repos[repo_index]
result = bpy.ops.extensions.repo_sync(repo_index=repo_index)
assert result == {"FINISHED"}, result
result = bpy.ops.extensions.package_install(
    repo_index=repo_index,
    pkg_id="faidlix_outliner",
    enable_on_install=True,
)
assert result == {"FINISHED"}, result

new_module = f"bl_ext.{repo.module}.faidlix_outliner"
_default, old_enabled = addon_utils.check(old_module)
_default, new_enabled = addon_utils.check(new_module)
assert old_enabled is False
assert new_enabled is True

enabled_matches = []
for module in addon_utils.modules(refresh=True):
    if getattr(module, "bl_info", {}).get("name") != "Faidlix_Outliner":
        continue
    if addon_utils.check(module.__name__)[1]:
        enabled_matches.append(module.__name__)
assert enabled_matches == [new_module], enabled_matches

print("FAIDLIX_OUTLINER_DUPLICATE_GUARD=PASS")
print(f"ACTIVE_MODULE={new_module}")

