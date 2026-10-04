import addon_utils
import bpy


matches = []
for module in addon_utils.modules():
    info = getattr(module, "bl_info", {})
    if info.get("name") == "Faidlix_Outliner":
        matches.append(module.__name__)

assert len(matches) == 1, matches
module_name = matches[0]
_default, enabled = addon_utils.check(module_name)
assert enabled, module_name
assert hasattr(bpy.ops.faidlix_outliner, "toggle_target")
assert hasattr(bpy.ops.faidlix_outliner, "toggle_restriction")
assert hasattr(bpy.ops.faidlix_outliner, "online_update")

print("FAIDLIX_OUTLINER_INSTALLED=PASS")
print(f"INSTALLED_MODULE={module_name}")

