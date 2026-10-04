import importlib.util
import pathlib
import sys

import bpy


root = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("blander_peferance", root / "__init__.py")
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)

assert addon.ADDON_VERSION == (1, 0, 0)
assert addon.PACKAGE_ID == "blander_peferance"

bpy.context.preferences.filepaths.use_load_ui = True
addon.register()
assert bpy.context.preferences.filepaths.use_load_ui is False
assert addon.keep_load_ui_disabled in bpy.app.handlers.load_post
assert hasattr(bpy.ops.blander_peferance, "apply")

bpy.context.preferences.filepaths.use_load_ui = True
addon.keep_load_ui_disabled("")
assert bpy.context.preferences.filepaths.use_load_ui is False

addon.unregister()
assert addon.keep_load_ui_disabled not in bpy.app.handlers.load_post
print("BLANDER_PEFERANCE_HEADLESS_OK")
