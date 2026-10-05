import importlib
import os

import addon_utils
import bpy


repository_url = os.environ["FAIDLIX_TEST_REPO_URL"]
bpy.context.preferences.system.use_online_access = True
result = bpy.ops.preferences.extension_repo_add(
    name="Faidlix Outliner Upgrade Test",
    remote_url=repository_url,
    use_sync_on_startup=False,
    type="REMOTE",
)
assert result == {"FINISHED"}, result
repo_index = len(bpy.context.preferences.extensions.repos) - 1
result = bpy.ops.extensions.repo_sync(repo_index=repo_index)
assert result == {"FINISHED"}, result

module = next(
    module
    for module in addon_utils.modules()
    if getattr(module, "bl_info", {}).get("name") == "Faidlix_Outliner"
)
expected_old = tuple(
    int(part) for part in os.environ.get("FAIDLIX_OLD_VERSION", "0.2.3").split(".")
)
assert tuple(module.bl_info["version"]) == expected_old
module = importlib.import_module(module.__name__)
preferences = bpy.context.preferences.addons[module.__name__].preferences
preferences.checkbox_x = 4

module._PENDING_UPDATE = {
    "module_name": module.__name__,
    "repo_index": repo_index,
    "preferences": {
        "show_overlay": preferences.show_overlay,
        "batch_selected_restrictions": preferences.batch_selected_restrictions,
        "checkbox_x": preferences.checkbox_x,
    },
    "target_module_name": f"bl_ext.{bpy.context.preferences.extensions.repos[repo_index].module}.faidlix_outliner",
    "version": "0.2.17",
}
module._apply_pending_update()

importlib.invalidate_caches()
updated = next(
    module
    for module in addon_utils.modules(refresh=True)
    if getattr(module, "bl_info", {}).get("name") == "Faidlix_Outliner"
)
assert tuple(updated.bl_info["version"]) == (0, 2, 17), updated.bl_info["version"]
_default, enabled = addon_utils.check(updated.__name__)
assert enabled
updated_preferences = bpy.context.preferences.addons[updated.__name__].preferences
assert updated_preferences.checkbox_x == 4

# Exercise the exact failure mode: the updated package must call the reloaded
# core.selection_state implementation in this same Blender process.
updated_module = importlib.import_module(updated.__name__)
probe = bpy.data.objects.new("SafeUpgradeProbe", None)
bpy.context.scene.collection.objects.link(probe)
result = bpy.ops.faidlix_outliner.toggle_target(
    target_kind="OBJECT",
    target_name=probe.name,
    action="AUTO",
)
assert result == {"FINISHED"}, result
assert updated_module._effective_target_state(probe, bpy.context.view_layer) == "ALL"

print("FAIDLIX_OUTLINER_SAFE_UPGRADE=PASS")
print(f"SAFE_UPGRADED_MODULE={updated.__name__}")

