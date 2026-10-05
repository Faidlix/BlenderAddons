import importlib.util
import pathlib
import sys

import bpy


root = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("faidlix_manager", root / "__init__.py")
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)

assert addon.ADDON_VERSION == (1, 1, 4)
assert addon.PACKAGE_ID == "faidlix_manager"
assert addon.REPOSITORY_URL.endswith("Faidlix/BlenderAddons/main/repository/index.json")
registry = addon._addon_registry()
assert registry["faidlix_manager"]["common_features"] == ["update_all"]
assert registry["blander_texture_marge"]["display_name"] == "Faidlix Texture Marge"
addon.register()
assert hasattr(bpy.ops.faidlix_manager, "update_all")
assert hasattr(bpy.types, "FAIDLIXMANAGER_PT_update_all")
assert addon.FAIDLIXMANAGER_PT_update_all.bl_options == {'HIDE_HEADER'}
assert addon.FAIDLIXMANAGER_PT_update_all.bl_order == -1000
addon.unregister()
assert not hasattr(bpy.types, "FAIDLIXMANAGER_PT_update_all")
print("FAIDLIX_MANAGER_HEADLESS_OK")
