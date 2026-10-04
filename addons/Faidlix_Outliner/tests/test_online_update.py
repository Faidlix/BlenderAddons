import addon_utils
import bpy


module = next(
    module
    for module in addon_utils.modules()
    if getattr(module, "bl_info", {}).get("name") == "Faidlix_Outliner"
)
_default, enabled = addon_utils.check(module.__name__)
assert enabled, module.__name__

result = bpy.ops.faidlix_outliner.online_update()
assert result == {"FINISHED"}, result

repository_url = (
    "https://raw.githubusercontent.com/"
    "Faidlix/BlenderAddons/main/repository/index.json"
)
repo = next(
    repo
    for repo in bpy.context.preferences.extensions.repos
    if repo.remote_url.rstrip("/") == repository_url.rstrip("/")
)
assert repo.enabled
assert repo.use_sync_on_startup

print("FAIDLIX_OUTLINER_ONLINE_UPDATE=PASS")
print(f"ONLINE_REPOSITORY={repo.remote_url}")

